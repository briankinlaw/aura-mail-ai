"""
Unit and Security Tests for Phase 5.2 Deterministic Canonical Grounding Remediation.
Verifies multi-dimensional factual tuple validation, strict contextual isolation,
preservation of precision modifiers ('+'), separation of held titles vs target titles,
rejection of unapproved employers/titles/dates, fail-closed behavior on unparsed/indeterminate
career assertions, Scribe fallback revalidation, monotonic Risk Sentinel integration,
and mail transmission isolation.
"""

import pytest
from unittest.mock import MagicMock, patch

from backend.canonical_grounding import (
    validate_canonical_grounding,
    generate_canonical_claim,
    CANONICAL_CLAIM_TEMPLATES,
    extract_monetary_claims,
    extract_percentage_claims,
    extract_first_person_employment_claims,
    detect_unparsed_career_assertions,
    match_claim_to_fact,
    GroundingValidationResult,
    GroundingStatus,
    ClaimCategory,
    ClaimStatus,
    TitleCategory,
    PrecisionPolicy,
    ScopePolicy,
    CanonicalFactDefinition,
    CANONICAL_FACT_REGISTRY,
    CANONICAL_EMPLOYMENT_RECORDS,
    TARGET_ROLE_TITLES,
    POSITIONING_DESCRIPTORS,
    APPROVED_TITLES,
    APPROVED_PAST_EMPLOYERS
)
from backend.canonical_engine import LOCKED_FACTS
from backend.radar.risk_evaluator import (
    analyze_risk_heuristics,
    evaluate_second_opinion_risk,
    merge_risk_assessments,
    RiskCategory,
    RiskSeverity,
    RiskAssessmentResult
)
from backend.models import (
    EmailMessage,
    UserProfile,
    RecruiterDetails,
    ClassificationResult,
    ReplyDraftRequest
)
from backend.radar.scribe_service import generate_executive_reply, compose_grounded_response
from backend.safety_policy import MailAction, ExecutionContext


# ===========================================================================
# 14.1 Authoritative Career Ledger Integrity Tests
# ===========================================================================

def test_ledger_google_direct_employment():
    """Google is recorded as direct employment from Oct 2019 to Nov 2021."""
    assert "google" in CANONICAL_EMPLOYMENT_RECORDS
    rec = CANONICAL_EMPLOYMENT_RECORDS["google"]
    assert rec.employer_canonical == "Google"
    assert rec.engagement_type == "DIRECT_EMPLOYMENT"
    assert rec.start_year == 2019 and rec.start_month == 10
    assert rec.end_year == 2021 and rec.end_month == 11
    assert rec.is_current is False
    assert any("cloud customer engineer" in t for t in rec.held_titles)


def test_ledger_promevo_tenure():
    """Promevo tenure is recorded as March 2026 to August 2026 (ended)."""
    assert "promevo" in CANONICAL_EMPLOYMENT_RECORDS
    rec = CANONICAL_EMPLOYMENT_RECORDS["promevo"]
    assert rec.employer_canonical == "Promevo"
    assert rec.start_year == 2026 and rec.start_month == 3
    assert rec.end_year == 2026 and rec.end_month == 8
    assert rec.is_current is False


def test_ledger_cdw_tenure():
    """CDW tenure is recorded as November 2023 to October 2024."""
    assert "cdw" in CANONICAL_EMPLOYMENT_RECORDS
    rec = CANONICAL_EMPLOYMENT_RECORDS["cdw"]
    assert rec.employer_canonical == "CDW"
    assert rec.start_year == 2023 and rec.start_month == 11
    assert rec.end_year == 2024 and rec.end_month == 10


def test_ledger_dxc_tenure():
    """DXC Technology tenure is recorded as March 2015 to October 2019."""
    assert "dxc" in CANONICAL_EMPLOYMENT_RECORDS
    rec = CANONICAL_EMPLOYMENT_RECORDS["dxc"]
    assert rec.employer_canonical == "DXC Technology"
    assert rec.start_year == 2015 and rec.start_month == 3
    assert rec.end_year == 2019 and rec.end_month == 10


def test_ledger_pythian_present():
    """Pythian is present in the employment ledger (Nov 2021 to May 2023)."""
    assert "pythian" in CANONICAL_EMPLOYMENT_RECORDS
    rec = CANONICAL_EMPLOYMENT_RECORDS["pythian"]
    assert rec.employer_canonical == "Pythian"
    assert rec.start_year == 2021 and rec.start_month == 11
    assert rec.end_year == 2023 and rec.end_month == 5


def test_ledger_ibm_start_2002():
    """IBM employment begins January 2002 and runs through March 2015."""
    assert "ibm" in CANONICAL_EMPLOYMENT_RECORDS
    rec = CANONICAL_EMPLOYMENT_RECORDS["ibm"]
    assert rec.employer_canonical == "IBM"
    assert rec.start_year == 2002 and rec.start_month == 1
    assert rec.end_year == 2015 and rec.end_month == 3


def test_ledger_mavencode_two_tenures():
    """MavenCode has two distinct tenures: current advisory (Sep 2026-present) and prior director (Oct 2024-Feb 2026)."""
    assert "mavencode_advisory" in CANONICAL_EMPLOYMENT_RECORDS
    assert "mavencode_director" in CANONICAL_EMPLOYMENT_RECORDS
    adv = CANONICAL_EMPLOYMENT_RECORDS["mavencode_advisory"]
    direc = CANONICAL_EMPLOYMENT_RECORDS["mavencode_director"]

    assert adv.engagement_type == "CONTRACT_ADVISORY"
    assert adv.start_year == 2026 and adv.start_month == 9
    assert adv.is_current is True

    assert direc.engagement_type == "DIRECT_EMPLOYMENT"
    assert direc.start_year == 2024 and direc.start_month == 10
    assert direc.end_year == 2026 and direc.end_month == 2
    assert direc.is_current is False


def test_ledger_target_titles_not_held_titles():
    """Target and positioning titles (Field CTO, Practice Director, TPM, CEO, VP) are not held titles."""
    for target in TARGET_ROLE_TITLES:
        for rec in CANONICAL_EMPLOYMENT_RECORDS.values():
            assert target not in rec.held_titles, f"Target title '{target}' was improperly listed as held at {rec.employer_canonical}"


def test_ledger_and_locked_facts_consistency():
    """LOCKED_FACTS does not contradict structured CANONICAL_EMPLOYMENT_RECORDS."""
    assert "FACT_GOOGLE_REVENUE" in LOCKED_FACTS
    assert "FACT_CAREER_IMPACT" in LOCKED_FACTS
    assert "FACT_DXC_PORTFOLIO" in LOCKED_FACTS
    assert "FACT_EMPLOYMENT_GOOGLE" in LOCKED_FACTS
    assert "Oct 2019-Nov 2021" in LOCKED_FACTS["FACT_EMPLOYMENT_GOOGLE"]
    assert "Mar 2026-Aug 2026" in LOCKED_FACTS["FACT_EMPLOYMENT_PROMEVO"]


# ===========================================================================
# 14.2 Schema Integrity Tests
# ===========================================================================

def test_schema_stable_fact_ids():
    """Every fact in CANONICAL_FACT_REGISTRY has a stable fact_id matching its registry key."""
    for key, fact in CANONICAL_FACT_REGISTRY.items():
        assert fact.fact_id == key
        assert len(fact.fact_id) > 0
        assert fact.canonical_text is not None


def test_schema_required_fields_enforced():
    """Every quantitative fact defines required metric aliases, required attribution aliases, and scope policy."""
    for fact in CANONICAL_FACT_REGISTRY.values():
        assert len(fact.required_metric_aliases) > 0, f"Fact {fact.fact_id} lacks required metric aliases"
        assert len(fact.required_attribution_aliases) > 0, f"Fact {fact.fact_id} lacks required attribution aliases"
        assert fact.precision_policy in [PrecisionPolicy.EXACT_REQUIRED, PrecisionPolicy.PLUS_REQUIRED, PrecisionPolicy.PLUS_PERMITTED]
        assert fact.scope_policy in [ScopePolicy.CAREER_WIDE_REQUIRED, ScopePolicy.EMPLOYER_BOUND_REQUIRED, ScopePolicy.EMPLOYER_OPTIONAL]


def test_schema_employer_bound_facts_declare_employer():
    """All employer-bound facts declare required_employer and allowed_employer_aliases."""
    for fact in CANONICAL_FACT_REGISTRY.values():
        if fact.scope_policy == ScopePolicy.EMPLOYER_BOUND_REQUIRED:
            assert fact.required_employer is not None, f"Fact {fact.fact_id} is employer bound but has no required_employer"
            assert len(fact.allowed_employer_aliases) > 0, f"Fact {fact.fact_id} lacks allowed_employer_aliases"


def test_schema_matcher_enforces_all_declared_dimensions():
    """The schema-driven matcher rejects claims missing precision, metric, attribution, or scope."""
    fact = CANONICAL_FACT_REGISTRY["FACT_GOOGLE_REVENUE"]
    # 1. Missing precision (adding '+' to exact fact)
    ok, st, reas = match_claim_to_fact("$8M+", 8_000_000, True, "at Google I influenced $8M+ in revenue", "at Google I influenced $8M+ in revenue", fact)
    assert not ok
    assert st == ClaimStatus.DISALLOWED_QUALIFIER

    # 2. Missing attribution (saying 'generated' instead of 'influenced')
    ok, st, reas = match_claim_to_fact("$8M", 8_000_000, False, "at Google I generated $8M in Google Cloud revenue", "at Google I generated $8M in Google Cloud revenue", fact)
    assert not ok
    assert st == ClaimStatus.DISALLOWED_QUALIFIER

    # 3. Missing metric (saying 'lottery winnings')
    ok, st, reas = match_claim_to_fact("$8M", 8_000_000, False, "at Google I influenced $8M in lottery winnings", "at Google I influenced $8M in lottery winnings", fact)
    assert not ok
    assert st == ClaimStatus.MISATTRIBUTED

    # 4. Missing employer (omitting Google)
    ok, st, reas = match_claim_to_fact("$8M", 8_000_000, False, "I influenced $8M in cloud revenue", "I influenced $8M in cloud revenue", fact)
    assert not ok
    assert st == ClaimStatus.UNSUPPORTED


# ===========================================================================
# 14.3 Monetary Mutation Tests (Independently Reproduced Attack Strings)
# ===========================================================================

@pytest.mark.parametrize("attack_text,expected_reason_substr", [
    ("I influenced $8M in lottery winnings.", "unapproved metric"),
    ("I stole $8M in Google Cloud revenue.", "disallowed term 'stole'"),
    ("I influenced $4M in cryptocurrency revenue.", "unapproved metric"),
    ("I influenced $4M in annual revenue at Stripe.", "misattributes"),
    ("I closed $2.1M in professional services at Stripe.", "misattributes"),
    ("I managed a $22M portfolio at Stripe.", "misattributes"),
    ("I delivered $2M+ in pipeline at Stripe.", "misattributes"),
    ("I delivered $100M+ in lottery winnings over my career.", "unapproved metric"),
    ("At Amazon, I influenced $8M in cloud revenue.", "misattributes"),
    ("I influenced $8M in revenue.", "omits required canonical employer 'google'"),
    ("I generated $8M in Google Cloud revenue.", "disallowed term 'generated'"),
    ("I closed $8M in Google Cloud revenue.", "disallowed term 'closed'"),
    ("I earned $2.1M at CDW.", "disallowed term 'earned'"),
    ("I influenced $2.1M in annual revenue at CDW.", "attribution"),
    ("I closed $2M+ in revenue at Promevo.", "disallowed term 'closed'"),
    ("I contributed $2M in pipeline at Promevo.", "lacks required canonical '+' precision"),
    ("I carried a $22M sales quota at DXC.", "disallowed term"),
    ("I personally generated $22M at DXC.", "disallowed term"),
    ("I delivered $100M in enterprise revenue.", "lacks required canonical '+' precision"),
    ("I won $100M+ in contracts at Promevo.", "disallowed term 'won'"),
    ("I earned $100M+ over my career.", "disallowed term 'earned'"),
    ("I personally booked $100M+ at Google.", "disallowed term 'booked'"),
])
def test_monetary_attack_strings_fail_closed(attack_text, expected_reason_substr):
    """All 8 independently reproduced monetary attacks and mutations must fail validation."""
    res = validate_canonical_grounding(attack_text)
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED, GroundingStatus.UNVERIFIED]
    assert res.requires_human_review is True
    assert len(res.unsupported_claims) >= 1
    assert any(expected_reason_substr.lower() in u.reason.lower() for u in res.unsupported_claims)


def test_approved_monetary_claims_pass():
    """Affirmatively complete canonical monetary claims pass validation with provenance, and fail-closed without."""
    did = "draft_monetary_1"
    # Google $8M
    c_google = generate_canonical_claim("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    res_google = validate_canonical_grounding(c_google["rendered_text"], provenance_claims=[c_google], draft_id=did)
    assert res_google.is_grounded is True
    assert "FACT_GOOGLE_REVENUE" in res_google.verified_fact_ids

    # Unprovenanced raw text returns UNVERIFIED
    raw_google = validate_canonical_grounding("At Google, I influenced $8M in new Google Cloud revenue.")
    assert raw_google.is_grounded is False
    assert raw_google.status == GroundingStatus.UNVERIFIED

    # Career-wide $100M+
    c_career = generate_canonical_claim("FACT_CAREER_IMPACT", "TPL_CAREER_ENTERPRISE_REVENUE_CONCISE", draft_id=did)
    res_career = validate_canonical_grounding(c_career["rendered_text"], provenance_claims=[c_career], draft_id=did)
    assert res_career.is_grounded is True
    assert "FACT_CAREER_IMPACT" in res_career.verified_fact_ids

    # CDW $2.1M
    c_cdw_serv = generate_canonical_claim("FACT_CDW_SERVICES", "TPL_CDW_SERVICES_CONCISE", draft_id=did)
    res_cdw_serv = validate_canonical_grounding(c_cdw_serv["rendered_text"], provenance_claims=[c_cdw_serv], draft_id=did)
    assert res_cdw_serv.is_grounded is True
    assert "FACT_CDW_SERVICES" in res_cdw_serv.verified_fact_ids

    # CDW $4M
    c_cdw_rev = generate_canonical_claim("FACT_CDW_REVENUE", "TPL_CDW_REVENUE_CONCISE", draft_id=did)
    res_cdw_rev = validate_canonical_grounding(c_cdw_rev["rendered_text"], provenance_claims=[c_cdw_rev], draft_id=did)
    assert res_cdw_rev.is_grounded is True
    assert "FACT_CDW_REVENUE" in res_cdw_rev.verified_fact_ids

    # Promevo $2M+
    c_prom_pipe = generate_canonical_claim("FACT_PROMEVO_PIPELINE", "TPL_PROMEVO_PIPELINE_CONCISE", draft_id=did)
    res_prom_pipe = validate_canonical_grounding(c_prom_pipe["rendered_text"], provenance_claims=[c_prom_pipe], draft_id=did)
    assert res_prom_pipe.is_grounded is True
    assert "FACT_PROMEVO_PIPELINE" in res_prom_pipe.verified_fact_ids

    # DXC $22M
    c_dxc = generate_canonical_claim("FACT_DXC_PORTFOLIO", "TPL_DXC_PORTFOLIO_CONCISE", draft_id=did)
    res_dxc = validate_canonical_grounding(c_dxc["rendered_text"], provenance_claims=[c_dxc], draft_id=did)
    assert res_dxc.is_grounded is True
    assert "FACT_DXC_PORTFOLIO" in res_dxc.verified_fact_ids


# ===========================================================================
# 14.4 Percentage Mutation Tests
# ===========================================================================

@pytest.mark.parametrize("valid_pct_claim,expected_fact_id,template_id", [
    ("At Promevo, I achieved a 23% POC-to-production conversion rate.", "FACT_PROMEVO_POC_CONVERSION", "TPL_PROMEVO_POC_CONVERSION_CONCISE"),
    ("At Promevo, I reduced scoping turnaround by 40%.", "FACT_PROMEVO_SCOPING_TURNAROUND", "TPL_PROMEVO_SCOPING_TURNAROUND_CONCISE"),
    ("At Promevo, we saw 20% shorter sales cycles.", "FACT_PROMEVO_SALES_CYCLES", "TPL_PROMEVO_SALES_CYCLES_CONCISE"),
    ("At Promevo, we achieved a 25% reduction in legacy architecture complexity.", "FACT_PROMEVO_LEGACY_COMPLEXITY", "TPL_PROMEVO_LEGACY_COMPLEXITY_CONCISE"),
    ("At Promevo, we enabled 33% faster time-to-value.", "FACT_PROMEVO_TIME_TO_VALUE", "TPL_PROMEVO_TIME_TO_VALUE_CONCISE"),
    ("At Promevo, our presales efficiency roadmap targeted a 30% improvement.", "FACT_PROMEVO_EFFICIENCY_ROADMAP", "TPL_PROMEVO_EFFICIENCY_ROADMAP_CONCISE"),
])
def test_approved_percentage_facts_pass(valid_pct_claim, expected_fact_id, template_id):
    """Verified Promevo percentage metrics pass with provenance, and return advisory UNVERIFIED without."""
    did = "draft_pct_1"
    # Provenance-backed validation
    c_pct = generate_canonical_claim(expected_fact_id, template_id, draft_id=did)
    res_prov = validate_canonical_grounding(c_pct["rendered_text"], provenance_claims=[c_pct], draft_id=did)
    assert res_prov.is_grounded is True
    assert res_prov.status == GroundingStatus.GROUNDED
    assert expected_fact_id in res_prov.verified_fact_ids

    # Unprovenanced raw validation
    res_raw = validate_canonical_grounding(valid_pct_claim)
    assert res_raw.is_grounded is False
    assert res_raw.status == GroundingStatus.UNVERIFIED


@pytest.mark.parametrize("attack_pct_claim", [
    "I grew pilot conversion by 23% at Acme.",
    "I reduced scoping turnaround by 40% at Acme.",
    "At Google, I achieved 23% POC conversion.",
    "I improved customer satisfaction by 23% at Promevo.",
    "I reduced scoping turnaround by 40% at Acme.",
    "I increased revenue by 20% at Promevo.",
    "I reduced headcount by 40% at Promevo.",
    "I improved POC-to-production conversion to 23%.",  # Missing Promevo
    "I reduced scoping turnaround by 40%."             # Missing Promevo
])
def test_percentage_attacks_fail(attack_pct_claim):
    """Percentage claims with wrong employer, wrong metric, or omitted required employer fail."""
    res = validate_canonical_grounding(attack_pct_claim)
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
    assert res.requires_human_review is True
    assert any(u.category == ClaimCategory.PERCENTAGE for u in res.unsupported_claims)


# ===========================================================================
# 14.5 Employment Mutation Tests
# ===========================================================================

@pytest.mark.parametrize("emp_attack_claim", [
    "I spent five years working for Netflix.",
    "I am employed by Amazon.",
    "I led engineering while employed by Meta.",
    "Google hired me in 2018.",
    "My employer was Oracle.",
    "I formerly worked for Stripe.",
    "Before joining CDW, I worked for Acme.",
    "I left Microsoft after three years."
])
def test_employment_mutations_detected_and_rejected(emp_attack_claim):
    """All first-person career assertions are extracted and false employers rejected (never NO_CAREER_CLAIMS)."""
    res = validate_canonical_grounding(emp_attack_claim)
    assert res.is_grounded is False
    assert res.status not in [GroundingStatus.NO_CAREER_CLAIMS, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]
    assert res.requires_human_review is True
    assert len(res.unsupported_claims) >= 1


# ===========================================================================
# 14.6 Authentic Employment & Positive/Negative Tenures
# ===========================================================================

def test_authentic_employment_claims_pass():
    """Authentic first-person statements pass with provenance, and return advisory UNVERIFIED without."""
    claims = [
        ("FACT_EMPLOYMENT_GOOGLE", "TPL_EMP_GOOGLE"),
        ("FACT_EMPLOYMENT_CDW", "TPL_EMP_CDW"),
        ("FACT_EMPLOYMENT_PYTHIAN", "TPL_EMP_PYTHIAN"),
        ("FACT_EMPLOYMENT_DXC", "TPL_EMP_DXC"),
        ("FACT_EMPLOYMENT_IBM", "TPL_EMP_IBM"),
        ("FACT_EMPLOYMENT_PROMEVO", "TPL_EMP_PROMEVO"),
        ("FACT_EMPLOYMENT_MAVENCODE_ADVISORY", "TPL_EMP_MAVENCODE_ADVISORY_CONCISE")
    ]
    for fact_id, tpl_id in claims:
        did = f"draft_auth_{fact_id}"
        rec = generate_canonical_claim(fact_id, tpl_id, draft_id=did)
        res = validate_canonical_grounding(rec["rendered_text"], provenance_claims=[rec], draft_id=did)
        assert res.is_grounded is True, f"Failed to validate authentic claim with provenance: {rec['rendered_text']}"
        assert fact_id in res.verified_fact_ids

    # Unprovenanced raw prose returns UNVERIFIED
    raw_res = validate_canonical_grounding("I worked at Google from October 2019 to November 2021.")
    assert raw_res.is_grounded is False
    assert raw_res.status == GroundingStatus.UNVERIFIED


def test_false_google_claims_fail():
    """Negative claims contradicting Google canonical employment fail closed."""
    negative_claims = [
        "I joined Google in 2018.",
        "I worked at Google through 2024.",
        "I was Chief Technology Officer at Google.",
        "I currently work at Google."
    ]
    for draft in negative_claims:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Failed to reject false Google claim: {draft}"
        assert res.requires_human_review is True


# ===========================================================================
# 14.7 Title Category Tests (Held vs Target Titles)
# ===========================================================================

def test_target_titles_asserted_as_held_fail():
    """Asserting target/positioning titles as held titles must fail."""
    test_cases = [
        "I served as Field CTO.",
        "I was a Practice Director.",
        "My title was Interim Head of AI.",
        "I held the title of Technical Program Manager.",
        "I was Chief Executive Officer."
    ]
    for draft in test_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Failed to reject target title asserted as held: {draft}"
        assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED, GroundingStatus.UNVERIFIED]
        assert res.requires_human_review is True


def test_opportunity_wording_permitted_as_safe_prose():
    """Target-role terminology in opportunity references remains safe correspondence (NO_CAREER_CLAIMS_DETECTED)."""
    opp_texts = [
        "I am interested in the Field CTO role.",
        "The Practice Director opportunity aligns with my background.",
        "Thank you for reaching out regarding the Technical Program Manager position.",
        "I look forward to discussing the Chief Technology Officer opening."
    ]
    for text in opp_texts:
        res = validate_canonical_grounding(text)
        assert res.is_grounded is False, f"Non-career opportunity prose must not be affirmatively grounded: {text}"
        assert res.status in [GroundingStatus.NO_CAREER_CLAIMS, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]
        assert res.requires_human_review is False


# ===========================================================================
# 14.8 Unparsed / Indeterminate Career Assertion Tests
# ===========================================================================

def test_unparsed_career_assertions_return_indeterminate():
    """First-person career assertions with strong signals that cannot be safely resolved return INDETERMINATE/UNGROUNDED (never NO_CAREER_CLAIMS)."""
    unparsed_texts = [
        "During my years leading high-growth cloud ventures, I spearheaded major platform shifts.",
        "When I was working across confidential fintech startups, I transformed delivery operations.",
        "I spent several years building autonomous systems before moving to advisory."
    ]
    for text in unparsed_texts:
        res = validate_canonical_grounding(text)
        assert res.is_grounded is False, f"Expected unparsed assertion to fail: {text}"
        assert res.status in [GroundingStatus.INDETERMINATE, GroundingStatus.UNGROUNDED, GroundingStatus.VALIDATION_FAILED, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
        assert res.requires_human_review is True
        assert res.status not in [GroundingStatus.NO_CAREER_CLAIMS, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]


# ===========================================================================
# 14.9 Mixed-Claim Isolation & Cross-Clause Boundaries
# ===========================================================================

def test_mixed_claims_in_same_sentence():
    """A sentence with valid ($100M+ career) and invalid (85% cost cut) claims fails overall."""
    draft = "Across my career, I delivered $100M+ in enterprise revenue while driving an 85% reduction in cloud infrastructure costs."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED, GroundingStatus.UNVERIFIED, GroundingStatus.MIXED_REVIEW_REQUIRED]
    assert res.requires_human_review is True
    assert any("85%" in u.extracted_text for u in res.unsupported_claims)


def test_mixed_claims_across_clauses_no_context_leak():
    """At CDW I influenced $4M in annual revenue, and at Stripe I closed $2.1M in services (CDW context must not leak to Stripe)."""
    draft = "At CDW, I influenced $4M in annual revenue, and at Stripe I closed $2.1M in services."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED, GroundingStatus.UNVERIFIED, GroundingStatus.MIXED_REVIEW_REQUIRED]
    assert any("stripe" in u.reason.lower() or "2.1m" in u.extracted_text.lower() for u in res.unsupported_claims)


def test_mixed_claims_across_sentences_no_context_leak():
    """I worked at Google. At Amazon, I influenced $8M in revenue (Google context must not authorize Amazon)."""
    draft = "I worked at Google. At Amazon, I influenced $8M in revenue."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert any("amazon" in u.reason.lower() or "$8m" in u.extracted_text.lower() for u in res.unsupported_claims)


def test_bulleted_and_newline_separated_claims():
    """Bulleted lists containing one valid and one invalid fact fail overall."""
    draft = (
        "Key career accomplishments:\n"
        "• At Google, influenced $8M in new Google Cloud revenue\n"
        "• At Netflix, led a $50M infrastructure overhaul"
    )
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert any("netflix" in u.reason.lower() or "$50m" in u.reason.lower() or u.status in [ClaimStatus.UNSUPPORTED, ClaimStatus.POTENTIAL_CONFLICT] for u in res.unsupported_claims)


# ===========================================================================
# 14.10 Scribe Post-Generation & Fallback Revalidation
# ===========================================================================

def test_scribe_valid_grounded_draft_returned():
    """When Gemini returns an unprovenanced draft, Scribe safely falls back to deterministic grounded response."""
    raw_draft = (
        "Hi Sarah,\n\n"
        "Thank you for reaching out regarding the Principal Solutions Architect opportunity at Snowflake. "
        "Across my career, I have influenced and delivered $100M+ in enterprise revenue, including influencing $8M in new Google Cloud revenue at Google.\n\n"
        "I have attached my updated resume for your review.\n\n"
        "Best regards,\nBrian Kinlaw"
    )
    email = EmailMessage(
        id="msg_001",
        sender_name="Sarah Recruiter",
        sender_email="sarah@snowflake.com",
        subject="Opportunity at Snowflake",
        body_text="We have an opening for a Principal Solutions Architect."
    )
    profile = UserProfile(full_name="Brian Kinlaw", current_title="Strategic Advisor")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = raw_draft
    mock_client.models.generate_content.return_value = mock_response

    with patch("backend.radar.scribe_service.get_gemini_client", return_value=mock_client):
        result = generate_executive_reply(email, profile)
        assert result is not None
        assert "Sarah" in result
        assert "Snowflake" in result


def test_scribe_invalid_model_draft_falls_back_and_revalidates():
    """When Gemini returns an ungrounded draft (e.g. Amazon $4M generated), Scribe uses revalidated fallback."""
    hallucinated_draft = "At Amazon, I generated $4M in annual revenue and built their AI platform."
    email = EmailMessage(
        id="msg_002",
        sender_name="Alex Recruiter",
        sender_email="alex@amazon.com",
        subject="Opportunity at Amazon",
        body_text="Interested in your background."
    )
    profile = UserProfile(full_name="Brian Kinlaw", current_title="Strategic Advisor")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = hallucinated_draft
    mock_client.models.generate_content.return_value = mock_response

    with patch("backend.radar.scribe_service.get_gemini_client", return_value=mock_client):
        result = generate_executive_reply(email, profile)
        assert result != hallucinated_draft
        assert "At Amazon, I generated $4M" not in result
        assert "Alex" in result


def test_scribe_empty_none_malformed_model_responses_fallback():
    """Empty, None, or malformed LLM responses trigger fallback that is canonically grounded."""
    email = EmailMessage(
        id="msg_003",
        sender_name="Pat Recruiter",
        sender_email="pat@tech.com",
        subject="Role opening",
        body_text="Role details here."
    )
    profile = UserProfile(full_name="Brian Kinlaw", current_title="Strategic Advisor")

    for bad_response_text in [None, "", "   ", "{'invalid': 'json'}"]:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = bad_response_text
        mock_client.models.generate_content.return_value = mock_response

        with patch("backend.radar.scribe_service.get_gemini_client", return_value=mock_client):
            result = generate_executive_reply(email, profile)
            assert result is not None
            assert len(result.strip()) > 0
            assert "Pat" in result


# ===========================================================================
# 14.11 Risk Sentinel Integration Tests
# ===========================================================================

def test_unsupported_claim_produces_non_downgradable_risk_finding():
    """Any unverified career claim must produce UNVERIFIED_CAREER_CLAIM and cannot be downgraded by Gemini."""
    bad_draft = "At Amazon, I generated $4M in annual revenue."
    heuristic_res = analyze_risk_heuristics(
        email_text="Looking for an enterprise architect.",
        draft_text=bad_draft,
        action="DRAFT"
    )
    assert heuristic_res.severity in [RiskSeverity.CAUTION, RiskSeverity.HIGH_RISK]
    assert heuristic_res.recommended_action in ["REVIEW_CAUTION", "BLOCKED"]
    assert RiskCategory.UNVERIFIED_CAREER_CLAIM in heuristic_res.detected_categories
    assert heuristic_res.recommended_action != "PROCEED"
    assert heuristic_res.severity != RiskSeverity.SAFE

    # Simulate Gemini returning a false 'SAFE' opinion
    mock_gemini_safe = RiskAssessmentResult(
        severity=RiskSeverity.SAFE,
        is_flagged=False,
        risk_score=0,
        detected_categories=[RiskCategory.CLEAN],
        second_opinion_summary="Everything looks fine to me.",
        recommended_action="PROCEED"
    )
    merged = merge_risk_assessments(heuristic_res, mock_gemini_safe)
    # Monotonic invariant: Merged result MUST retain the caution/unverified finding
    assert merged.severity in [RiskSeverity.CAUTION, RiskSeverity.HIGH_RISK]
    assert merged.recommended_action in ["REVIEW_CAUTION", "BLOCKED"]
    assert RiskCategory.UNVERIFIED_CAREER_CLAIM in merged.detected_categories
    assert merged.recommended_action != "PROCEED"


# ===========================================================================
# 14.12 Transmission Isolation Tests
# ===========================================================================

def test_grounding_success_does_not_create_or_invoke_transmission():
    """Grounded validation success does not grant send authority or invoke mail transmission."""
    did = "draft_trans_1"
    c_google = generate_canonical_claim("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    good_draft = c_google["rendered_text"]
    val = validate_canonical_grounding(good_draft, provenance_claims=[c_google], draft_id=did)
    assert val.is_grounded is True

    # Even with a perfectly grounded draft, proposing SEND action remains HIGH_RISK + BLOCKED
    risk_res = analyze_risk_heuristics(
        email_text="Inbound inquiry.",
        draft_text=good_draft,
        action="SEND"
    )
    assert risk_res.severity == RiskSeverity.HIGH_RISK
    assert risk_res.recommended_action == "BLOCKED"
    assert RiskCategory.AUTONOMOUS_SEND_POLICY in risk_res.detected_categories


# ===========================================================================
# Phase 5.3 Required Exact Adversarial Test Cases (Section 13)
# ===========================================================================

def test_section_13_1_employer_binding_adversarial():
    """Section 13.1: All employer-binding bypass attempts must be BLOCKED."""
    blocked_cases = [
        "Regarding the role at CDW, I influenced $4M in annual revenue at Globex.",
        "I achieved a 23% POC-to-production conversion rate on behalf of Globex at Promevo.",
        "At Google, I discussed strategy; at Globex, I influenced $8M in cloud revenue.",
        "At Promevo, I advised the team, while Contoso achieved a 40% reduction in scoping turnaround."
    ]
    for draft in blocked_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Employer binding leak allowed ungrounded claim: {draft}"
        assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
        assert res.requires_human_review is True

    # Compound sentence with one valid and one invalid claim
    compound_draft = "At CDW, I influenced $4M in annual revenue; at Globex, I closed $2.1M in services."
    comp_res = validate_canonical_grounding(compound_draft)
    assert comp_res.is_grounded is False
    assert comp_res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED, GroundingStatus.MIXED_REVIEW_REQUIRED, GroundingStatus.UNVERIFIED]
    assert len(comp_res.unsupported_claims) >= 1
    assert any("globex" in u.reason.lower() for u in comp_res.unsupported_claims)


def test_section_13_2_employment_detection_adversarial():
    """Section 13.2: Unrecognized and unauthorized employment/payroll assertions must fail closed (never NO_CAREER_CLAIMS)."""
    detection_cases = [
        "My paycheck came from Netflix for five years.",
        "Amazon has employed me since 2020.",
        "I used to be on Apple’s payroll.",
        "Globex was my employer.",
        "I spent several years on Contoso’s payroll.",
        "The company I worked for was Initech."
    ]
    for draft in detection_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Employment assertion bypassed detection: {draft}"
        assert res.status not in [GroundingStatus.NO_CAREER_CLAIMS, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]
        assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
        assert res.requires_human_review is True


def test_section_13_3_chronology_adversarial():
    """Section 13.3: Chronology violations across all employers must fail closed."""
    chrono_attack_cases = [
        "I worked at Pythian from 2010 to 2020.",
        "I worked at IBM from 2018 to 2026.",
        "I currently work at Pythian.",
        "I joined DXC in 2024.",
        "I left Google in 2020.",
        "I worked at Google from 2019 to 2024.",
        "I currently work at CDW.",
        "I joined Promevo in 2024."
    ]
    for draft in chrono_attack_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Chronology violation was not rejected: {draft}"
        assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
        assert res.requires_human_review is True


def test_section_13_3_authentic_chronology_passes():
    """Section 7.5: Authentic chronology statements pass with provenance, and return advisory UNVERIFIED without."""
    positive_chrono_cases = [
        ("FACT_EMPLOYMENT_GOOGLE", "TPL_EMP_GOOGLE"),
        ("FACT_EMPLOYMENT_PYTHIAN", "TPL_EMP_PYTHIAN"),
        ("FACT_EMPLOYMENT_PROMEVO", "TPL_EMP_PROMEVO"),
        ("FACT_EMPLOYMENT_MAVENCODE_ADVISORY", "TPL_EMP_MAVENCODE_ADVISORY_CONCISE")
    ]
    for fact_id, tpl_id in positive_chrono_cases:
        did = f"draft_chrono_{fact_id}"
        rec = generate_canonical_claim(fact_id, tpl_id, draft_id=did)
        res = validate_canonical_grounding(rec["rendered_text"], provenance_claims=[rec], draft_id=did)
        assert res.is_grounded is True, f"Failed to validate authentic chronology with provenance: {rec['rendered_text']}"
        assert fact_id in res.verified_fact_ids

    # Unprovenanced raw validation
    raw_res = validate_canonical_grounding("I worked at Google from 2019 to 2021.")
    assert raw_res.is_grounded is False
    assert raw_res.status == GroundingStatus.UNVERIFIED


def test_section_13_4_title_relationships_adversarial():
    """Section 13.4: Substring title attacks and wrong seniority modifiers must fail closed."""
    title_attack_cases = [
        "I served as Principal Solutions Architect at Promevo.",
        "I was Field CTO at MavenCode.",
        "I was Senior Solutions Architect at Google.",
        "I was Advisory Solutions Architect at CDW."
    ]
    for draft in title_attack_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Title violation was not rejected: {draft}"
        assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
        assert res.requires_human_review is True


def test_section_13_5_authentic_title_and_multi_tenure():
    """Section 13.5: Authentic held titles pass with provenance, and return advisory UNVERIFIED without."""
    authentic_title_cases = [
        ("FACT_EMPLOYMENT_PROMEVO", "TPL_EMP_PROMEVO"),
        ("FACT_EMPLOYMENT_GOOGLE", "TPL_EMP_GOOGLE"),
        ("FACT_EMPLOYMENT_MAVENCODE_DIRECTOR", "TPL_EMP_MAVENCODE_DIRECTOR"),
        ("FACT_EMPLOYMENT_CDW", "TPL_EMP_CDW"),
        ("FACT_EMPLOYMENT_PYTHIAN", "TPL_EMP_PYTHIAN"),
        ("FACT_EMPLOYMENT_DXC", "TPL_EMP_DXC")
    ]
    for fact_id, tpl_id in authentic_title_cases:
        did = f"draft_title_{fact_id}"
        rec = generate_canonical_claim(fact_id, tpl_id, draft_id=did)
        res = validate_canonical_grounding(rec["rendered_text"], provenance_claims=[rec], draft_id=did)
        assert res.is_grounded is True, f"Failed to validate authentic title with provenance: {rec['rendered_text']}"
        assert fact_id in res.verified_fact_ids

    # Unprovenanced raw validation
    raw_res = validate_canonical_grounding("I was Cloud Customer Engineer at Google.")
    assert raw_res.is_grounded is False
    assert raw_res.status == GroundingStatus.UNVERIFIED


def test_section_13_6_negation_and_disclaimer_adversarial():
    """Section 13.6: Negated, disclaimed, and false accomplishment claims must fail closed (never grounded)."""
    negated_cases = [
        "I did not influence $8M in new Google Cloud revenue at Google.",
        "I falsely claimed that I influenced $8M in new Google Cloud revenue at Google.",
        "I never closed $2.1M in services at CDW.",
        "It would be inaccurate to say that I led a $22M portfolio at DXC.",
        "My résumé mistakenly states that I led a $22M portfolio at DXC.",
        "I never achieved a 23% POC-to-production conversion rate at Promevo.",
        "I cannot claim that I led a $22M portfolio at DXC.",
        "I have not achieved a 23% POC conversion rate at Promevo."
    ]
    for draft in negated_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Negated/disclaimed claim was falsely grounded: {draft}"
        assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
        assert res.requires_human_review is True


def test_section_13_7_positive_authentic_accomplishments_pass():
    """Section 13.7: Positive affirmative canonical accomplishments pass with provenance, and return advisory UNVERIFIED without."""
    positive_cases = [
        ("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE"),
        ("FACT_CDW_SERVICES", "TPL_CDW_SERVICES_CONCISE"),
        ("FACT_DXC_PORTFOLIO", "TPL_DXC_PORTFOLIO_CONCISE"),
        ("FACT_PROMEVO_POC_CONVERSION", "TPL_PROMEVO_POC_CONVERSION_CONCISE"),
        ("FACT_CDW_REVENUE", "TPL_CDW_REVENUE_CONCISE")
    ]
    for fact_id, tpl_id in positive_cases:
        did = f"draft_pos_{fact_id}"
        rec = generate_canonical_claim(fact_id, tpl_id, draft_id=did)
        res = validate_canonical_grounding(rec["rendered_text"], provenance_claims=[rec], draft_id=did)
        assert res.is_grounded is True, f"Failed to validate positive authentic claim with provenance: {rec['rendered_text']}"
        assert fact_id in res.verified_fact_ids

    # Unprovenanced raw validation
    raw_res = validate_canonical_grounding("At Google, I influenced $8M in new Google Cloud revenue.")
    assert raw_res.is_grounded is False
    assert raw_res.status == GroundingStatus.UNVERIFIED


# ===========================================================================
# Phase 5.3 Parameterized Mutation Testing Families (Section 12)
# ===========================================================================

@pytest.mark.parametrize("fictional_company", [
    "Globex", "Contoso", "Initech", "Umbrella Corporation", "Wayne Enterprises", "Stark Industries", "Hooli", "Acme Corp"
])
@pytest.mark.parametrize("claim_template", [
    "At {company}, I influenced $8M in cloud revenue.",
    "I closed $2.1M in services at {company}.",
    "I influenced $4M in annual revenue while at {company}.",
    "I led a $22M analytics portfolio at {company}.",
    "I achieved a 23% POC-to-production conversion rate on behalf of {company} at Promevo.",
    "Regarding the role at CDW, I influenced $4M in annual revenue at {company}."
])
def test_mutation_family_employers(fictional_company, claim_template):
    """Section 12.1: Employer mutations across arbitrary fictional companies must fail without a production denylist."""
    text = claim_template.format(company=fictional_company)
    res = validate_canonical_grounding(text)
    assert res.is_grounded is False, f"Fictional company mutation was falsely grounded: {text}"
    assert res.requires_human_review is True


@pytest.mark.parametrize("negation_prefix", [
    "I did not", "I didn't", "I never", "I have not", "I haven't", "I cannot claim that I",
    "I falsely claimed that I", "It would be inaccurate to say that I", "My draft incorrectly states that I"
])
def test_mutation_family_attributions(negation_prefix):
    """Section 12.2: Attribution mutations with negation and disclaimer prefixes must fail closed."""
    text = f"{negation_prefix} influenced $8M in new Google Cloud revenue at Google."
    res = validate_canonical_grounding(text)
    assert res.is_grounded is False, f"Negated attribution mutation was falsely grounded: {text}"
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED, GroundingStatus.UNVERIFIED]


@pytest.mark.parametrize("invalid_title_at_company", [
    "I was Senior Cloud Customer Engineer at Google.",
    "I was Principal Solutions Architect at Promevo.",
    "I was Advisory Solutions Architect at CDW.",
    "I was Field CTO at Google.",
    "I was Chief Executive Officer at Pythian.",
    "I was Practice Director at DXC Technology.",
    "I was Director of AI at IBM."
])
def test_mutation_family_titles(invalid_title_at_company):
    """Section 12.3: Title mutations with added seniority, target roles, or adjacent cross-employer titles fail closed."""
    res = validate_canonical_grounding(invalid_title_at_company)
    assert res.is_grounded is False, f"Title mutation was falsely grounded: {invalid_title_at_company}"
    assert res.requires_human_review is True


@pytest.mark.parametrize("invalid_chrono_text", [
    "I worked at Google from 2015 to 2018.",
    "I worked at Google from 2019 to 2025.",
    "I joined Pythian in 2019.",
    "I left CDW in 2026.",
    "I spent ten years working at Google.",
    "I worked at IBM from 2016 to 2020.",
    "I currently work at DXC Technology."
])
def test_mutation_family_chronology(invalid_chrono_text):
    """Section 12.4: Chronology mutations with wrong dates, durations, and status fail closed."""
    res = validate_canonical_grounding(invalid_chrono_text)
    assert res.is_grounded is False, f"Chronology mutation was falsely grounded: {invalid_chrono_text}"
    assert res.requires_human_review is True


@pytest.mark.parametrize("grammar_template", [
    "I worked for {company}.",
    "{company} employed me.",
    "{company} hired me.",
    "{company} was my employer.",
    "My employer was {company}.",
    "My paycheck came from {company}.",
    "I was on {company}'s payroll.",
    "I used to work for {company}.",
    "I spent 5 years at {company}.",
    "During my tenure with {company}, I led architecture.",
    "While employed by {company}, I directed strategy.",
    "Before joining CDW, I worked at {company}."
])
def test_mutation_family_grammar(grammar_template):
    """Section 12.5: Grammatical mutations of employment assertions for unapproved companies fail closed."""
    text = grammar_template.format(company="Globex")
    res = validate_canonical_grounding(text)
    assert res.is_grounded is False, f"Grammar mutation bypassed career detection: {text}"
    assert res.status not in [GroundingStatus.NO_CAREER_CLAIMS, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]
    assert res.requires_human_review is True


# ===========================================================================
# Phase 5.4 Remediation Test Suite (CCS v2.1 — Phase 5.4)
# ===========================================================================

@pytest.mark.parametrize("noun_modifier_claim", [
    # Exact reproduced review cases
    "At Google, I influenced $8M in Globex revenue.",
    "At CDW, I influenced $4M in Globex annual revenue.",
    "At Promevo, I achieved a 23% Globex POC-to-production conversion rate.",
    # Grammatical variants
    "At Google, I influenced $8M in annual Globex revenue.",
    "While at CDW, I drove $4M of Globex pipeline.",
    "At Promevo, I achieved Globex's 23% POC-to-production conversion rate.",
    "During my time at Google, I influenced an $8M Globex revenue outcome.",
    "At Google, I influenced $8M in revenue for Globex.",
    "At Google, I influenced Globex revenue totaling $8M.",
    # Multiword org mutation
    "While at Promevo, I contributed to $2M+ in Stark Industries pipeline.",
    # Reordered metric with modifier
    "At Promevo, I saw 20% shorter Contoso sales cycles."
])
def test_phase54_organization_noun_modifiers_fail_closed(noun_modifier_claim):
    """Section 7.1: Organization noun modifiers bound to metrics must fail closed when conflicting."""
    res = validate_canonical_grounding(noun_modifier_claim)
    assert res.is_grounded is False, f"Organization noun modifier was improperly grounded: {noun_modifier_claim}"
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
    assert res.requires_human_review is True


@pytest.mark.parametrize("temporal_signal_claim", [
    # Exact reproduced review cases
    "I worked at Google beginning in 2018 and ending in 2024.",
    "I worked at Google starting in 2018.",
    "These days, I work at Pythian.",
    # Temporal & Status variants
    "I worked at Google since 2018.",
    "I worked at Google until 2024.",
    "I worked at Google through 2024.",
    "I worked at Google from 2018 onward.",
    "Currently, I am employed at Pythian.",
    "I work at Pythian now.",
    "I still work at Pythian.",
    "I continue to work at Pythian.",
    "I formerly advised MavenCode."
])
def test_phase54_temporal_and_status_consumption(temporal_signal_claim):
    """Section 7.2: Unparsed or contradictory temporal/status signals must fail closed."""
    res = validate_canonical_grounding(temporal_signal_claim)
    assert res.is_grounded is False, f"Temporal/status violation was improperly grounded: {temporal_signal_claim}"
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
    assert res.requires_human_review is True


@pytest.mark.parametrize("lookalike_employer_claim", [
    # Exact reproduced review case
    "I worked at Googleplex from 2019 to 2021.",
    # Substring / compound lookalikes
    "I worked at Google Cloudworks from 2019 to 2021.",
    "I worked at NewGoogle from 2019 to 2021.",
    "I worked at IBMish from 2010 to 2012.",
    "I worked at MavenCode Labs.",
    "I worked at CDW Global from 2023 to 2024.",
    "I worked at Promevo Technologies in 2026.",
    "I worked at Pythian Solutions from 2021 to 2023.",
    "I worked at DXC Labs from 2015 to 2019."
])
def test_phase54_exact_employer_aliases_reject_substring_lookalikes(lookalike_employer_claim):
    """Section 7.3: Substring employer lookalikes must fail closed (no substring containment)."""
    res = validate_canonical_grounding(lookalike_employer_claim)
    assert res.is_grounded is False, f"Substring lookalike employer was falsely grounded: {lookalike_employer_claim}"
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
    assert res.requires_human_review is True


def test_phase54_exact_employer_aliases_allow_registered_aliases():
    """Section 7.3: Explicitly registered normalized aliases pass with provenance, and return advisory UNVERIFIED without."""
    valid_alias_cases = [
        ("FACT_EMPLOYMENT_GOOGLE", "TPL_EMP_GOOGLE"),
        ("FACT_EMPLOYMENT_CDW", "TPL_EMP_CDW"),
        ("FACT_EMPLOYMENT_DXC", "TPL_EMP_DXC"),
        ("FACT_EMPLOYMENT_PYTHIAN", "TPL_EMP_PYTHIAN"),
        ("FACT_EMPLOYMENT_IBM", "TPL_EMP_IBM")
    ]
    for fact_id, tpl_id in valid_alias_cases:
        did = f"draft_alias_{fact_id}"
        rec = generate_canonical_claim(fact_id, tpl_id, draft_id=did)
        res = validate_canonical_grounding(rec["rendered_text"], provenance_claims=[rec], draft_id=did)
        assert res.is_grounded is True, f"Registered employer alias was improperly rejected with provenance: {rec['rendered_text']}"
        assert fact_id in res.verified_fact_ids

    # Unprovenanced raw validation
    raw_res = validate_canonical_grounding("I worked at Google from 2019 to 2021.")
    assert raw_res.is_grounded is False
    assert raw_res.status == GroundingStatus.UNVERIFIED


@pytest.mark.parametrize("state_attack_claim", [
    # Exact reproduced case
    "I remain employed at Pythian.",
    # Active, passive, employer-subject, payroll variations asserting current state for ended tenures
    "I continue to work at Pythian.",
    "I still work for Pythian.",
    "Pythian still employs me.",
    "I am currently on Pythian's payroll.",
    "I remain on the payroll at Pythian.",
    "My current employer is Pythian.",
    "I am currently employed by CDW.",
    "CDW still employs me.",
    "I am currently on CDW's payroll."
])
def test_phase54_employment_state_detection_fails_closed(state_attack_claim):
    """Section 7.4: Employment-state assertions for past employers must be extracted and rejected (never NO_CAREER_CLAIMS)."""
    res = validate_canonical_grounding(state_attack_claim)
    assert res.is_grounded is False, f"Employment state assertion was falsely grounded: {state_attack_claim}"
    assert res.status not in [GroundingStatus.NO_CAREER_CLAIMS, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
    assert res.requires_human_review is True


def test_phase54_positive_employment_state_passes():
    """Section 7.4: Positive affirmative employment assertions pass with provenance, and return advisory UNVERIFIED without."""
    positive_cases = [
        ("FACT_EMPLOYMENT_MAVENCODE_ADVISORY", "TPL_EMP_MAVENCODE_ADVISORY_CONCISE"),
        ("FACT_EMPLOYMENT_PYTHIAN", "TPL_EMP_PYTHIAN")
    ]
    for fact_id, tpl_id in positive_cases:
        did = f"draft_state_{fact_id}"
        rec = generate_canonical_claim(fact_id, tpl_id, draft_id=did)
        res = validate_canonical_grounding(rec["rendered_text"], provenance_claims=[rec], draft_id=did)
        assert res.is_grounded is True, f"Authentic employment state assertion failed with provenance: {rec['rendered_text']}"
        assert fact_id in res.verified_fact_ids

    # Unprovenanced raw validation
    raw_res = validate_canonical_grounding("I currently serve as Strategic Advisor at MavenCode.")
    assert raw_res.is_grounded is False
    assert raw_res.status == GroundingStatus.UNVERIFIED


@pytest.mark.parametrize("non_affirmative_claim", [
    # Exact reproduced cases
    "I cannot honestly say I influenced $8M in new Google Cloud revenue at Google.",
    "I don't believe I influenced $8M in new Google Cloud revenue at Google.",
    "I allegedly influenced $8M in new Google Cloud revenue at Google.",
    # Modal / Hearsay / Disclaimer variants
    "I cannot claim that I influenced $8M in new Google Cloud revenue at Google.",
    "I would not say I influenced $8M in new Google Cloud revenue at Google.",
    "I doubt that I influenced $8M in new Google Cloud revenue at Google.",
    "I may have influenced $8M in new Google Cloud revenue at Google.",
    "I supposedly influenced $8M in new Google Cloud revenue at Google.",
    "I reportedly influenced $8M in new Google Cloud revenue at Google.",
    "It was alleged that I influenced $8M in new Google Cloud revenue at Google.",
    "Someone claimed that I influenced $8M in new Google Cloud revenue at Google.",
    "I was said to have influenced $8M in new Google Cloud revenue at Google."
])
def test_phase54_attribution_polarity_non_affirmative_fails_closed(non_affirmative_claim):
    """Section 7.5: Non-affirmative, negated, disclaimed, uncertain, or hearsay claims fail closed."""
    res = validate_canonical_grounding(non_affirmative_claim)
    assert res.is_grounded is False, f"Non-affirmative attribution was falsely grounded: {non_affirmative_claim}"
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]
    assert res.requires_human_review is True


def test_phase54_polarity_non_interference_on_opportunity_prose():
    """Section 7.5: Polarity checking does not corrupt safe opportunity prose or unrelated belief statements."""
    # Standalone alignment statement
    res_align = validate_canonical_grounding("I believe my experience aligns with the role.")
    assert res_align.is_grounded is False
    assert res_align.status in [GroundingStatus.NO_CAREER_CLAIMS, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]

    # Grounded claim combined with alignment statement
    did = "draft_p54_polarity"
    c_google = generate_canonical_claim("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    combined = f"{c_google['rendered_text']} I believe my experience aligns with the role."
    res_comb = validate_canonical_grounding(combined, provenance_claims=[c_google], draft_id=did)
    assert res_comb.is_grounded is True
    assert "FACT_GOOGLE_REVENUE" in res_comb.verified_fact_ids


@pytest.mark.parametrize("underspecified_multi_tenure", [
    # Exact reproduced case
    "I worked at MavenCode.",
    # Underspecified variants
    "I was with MavenCode.",
    "MavenCode employed me.",
    "I held a role at MavenCode.",
    "I previously worked for MavenCode.",
    "I have worked with MavenCode."
])
def test_phase54_ambiguous_multiple_tenures_return_indeterminate(underspecified_multi_tenure):
    """Section 7.6: Underspecified multi-tenure claims return INDETERMINATE/UNVERIFIED without selecting by insertion order."""
    res = validate_canonical_grounding(underspecified_multi_tenure)
    assert res.is_grounded is False, f"Underspecified multi-tenure was falsely grounded: {underspecified_multi_tenure}"
    assert res.status in [GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNVERIFIED]
    assert res.requires_human_review is True


def test_phase54_disambiguated_multi_tenures_pass_or_fail_correctly():
    """Section 7.6: Multi-tenure claims pass with provenance, and fail-closed when contradictory."""
    did1 = "draft_p54_multi_dir"
    did2 = "draft_p54_multi_adv"
    # 1. Director claim with provenance -> FACT_EMPLOYMENT_MAVENCODE_DIRECTOR
    c_dir = generate_canonical_claim("FACT_EMPLOYMENT_MAVENCODE_DIRECTOR", "TPL_EMP_MAVENCODE_DIRECTOR", draft_id=did1)
    res_dir = validate_canonical_grounding(c_dir["rendered_text"], provenance_claims=[c_dir], draft_id=did1)
    assert res_dir.is_grounded is True
    assert "FACT_EMPLOYMENT_MAVENCODE_DIRECTOR" in res_dir.verified_fact_ids

    # 2. Strategic Advisor claim with provenance -> FACT_EMPLOYMENT_MAVENCODE_ADVISORY
    c_adv = generate_canonical_claim("FACT_EMPLOYMENT_MAVENCODE_ADVISORY", "TPL_EMP_MAVENCODE_ADVISORY_CONCISE", draft_id=did2)
    res_adv = validate_canonical_grounding(c_adv["rendered_text"], provenance_claims=[c_adv], draft_id=did2)
    assert res_adv.is_grounded is True
    assert "FACT_EMPLOYMENT_MAVENCODE_ADVISORY" in res_adv.verified_fact_ids

    # 3. Contradictory dates for MavenCode -> UNSUPPORTED
    res_bad_dates = validate_canonical_grounding("I worked at MavenCode from 2010 to 2012.")
    assert res_bad_dates.is_grounded is False
    assert res_bad_dates.status in [GroundingStatus.UNGROUNDED, GroundingStatus.POTENTIAL_CONFLICT, GroundingStatus.UNSUPPORTED]

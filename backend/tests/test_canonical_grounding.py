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
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE]
    assert res.requires_human_review is True
    assert len(res.unsupported_claims) >= 1
    assert any(expected_reason_substr.lower() in u.reason.lower() for u in res.unsupported_claims)


def test_approved_monetary_claims_pass():
    """Affirmatively complete canonical monetary claims pass validation."""
    # Google $8M
    res_google = validate_canonical_grounding("At Google, I influenced $8M in new Google Cloud revenue.")
    assert res_google.is_grounded is True
    assert "FACT_GOOGLE_REVENUE" in res_google.verified_fact_ids

    # Career-wide $100M+
    res_career = validate_canonical_grounding("Across my career, I influenced and delivered $100M+ in enterprise revenue.")
    assert res_career.is_grounded is True
    assert "FACT_CAREER_IMPACT" in res_career.verified_fact_ids

    # CDW $2.1M
    res_cdw_serv = validate_canonical_grounding("At CDW, I closed $2.1M in services.")
    assert res_cdw_serv.is_grounded is True
    assert "FACT_CDW_SERVICES" in res_cdw_serv.verified_fact_ids

    # CDW $4M
    res_cdw_rev = validate_canonical_grounding("At CDW, I influenced $4M in annual revenue.")
    assert res_cdw_rev.is_grounded is True
    assert "FACT_CDW_REVENUE" in res_cdw_rev.verified_fact_ids

    # Promevo $2M+
    res_prom_pipe = validate_canonical_grounding("At Promevo, I contributed to an estimated $2M+ pipeline.")
    assert res_prom_pipe.is_grounded is True
    assert "FACT_PROMEVO_PIPELINE" in res_prom_pipe.verified_fact_ids

    # DXC $22M
    res_dxc = validate_canonical_grounding("At DXC Technology, I led a $22M analytics and AI portfolio.")
    assert res_dxc.is_grounded is True
    assert "FACT_DXC_PORTFOLIO" in res_dxc.verified_fact_ids


# ===========================================================================
# 14.4 Percentage Mutation Tests
# ===========================================================================

@pytest.mark.parametrize("valid_pct_claim,expected_fact_id", [
    ("At Promevo, I achieved a 23% POC-to-production conversion rate.", "FACT_PROMEVO_POC_CONVERSION"),
    ("At Promevo, I reduced scoping turnaround by 40%.", "FACT_PROMEVO_SCOPING_TURNAROUND"),
    ("At Promevo, we saw 20% shorter sales cycles.", "FACT_PROMEVO_SALES_CYCLES"),
    ("At Promevo, we achieved a 25% reduction in legacy architecture complexity.", "FACT_PROMEVO_LEGACY_COMPLEXITY"),
    ("At Promevo, we enabled 33% faster time-to-value.", "FACT_PROMEVO_TIME_TO_VALUE"),
    ("At Promevo, our presales efficiency roadmap targeted a 30% improvement.", "FACT_PROMEVO_EFFICIENCY_ROADMAP"),
])
def test_approved_percentage_facts_pass(valid_pct_claim, expected_fact_id):
    """Verified Promevo percentage metrics with explicit employer pass."""
    res = validate_canonical_grounding(valid_pct_claim)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert expected_fact_id in res.verified_fact_ids


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
    assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE]
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
    assert res.status != GroundingStatus.NO_CAREER_CLAIMS
    assert res.requires_human_review is True
    assert len(res.unsupported_claims) >= 1


# ===========================================================================
# 14.6 Authentic Employment & Positive/Negative Tenures
# ===========================================================================

def test_authentic_employment_claims_pass():
    """Authentic first-person statements for all 7 canonical employers pass."""
    claims = [
        "I worked at Google from October 2019 to November 2021.",
        "I was a Cloud Customer Engineer at Google.",
        "I served as a Data Cloud Customer Engineer at Google.",
        "I served as Senior Solutions Architect at CDW.",
        "I was Principal Cloud Solutions Architect at Pythian.",
        "I served as Principal Solution Architect at DXC Technology.",
        "I worked at IBM as Watson Analytics Solution Architect.",
        "I am currently Strategic Advisor, Data & AI at MavenCode."
    ]
    for draft in claims:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is True, f"Failed to validate authentic claim: {draft} ({res.validation_summary})"


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
        assert res.status in [GroundingStatus.UNGROUNDED, GroundingStatus.INDETERMINATE]
        assert res.requires_human_review is True


def test_opportunity_wording_permitted_as_safe_prose():
    """Target-role terminology in opportunity references remains safe correspondence."""
    opp_texts = [
        "I am interested in the Field CTO role.",
        "The Practice Director opportunity aligns with my background.",
        "Thank you for reaching out regarding the Technical Program Manager position.",
        "I look forward to discussing the Chief Technology Officer opening."
    ]
    for text in opp_texts:
        res = validate_canonical_grounding(text)
        assert res.is_grounded is True, f"Falsely flagged opportunity reference: {text}"
        assert res.status == GroundingStatus.NO_CAREER_CLAIMS
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
        assert res.status in [GroundingStatus.INDETERMINATE, GroundingStatus.UNGROUNDED, GroundingStatus.VALIDATION_FAILED]
        assert res.requires_human_review is True
        assert res.status != GroundingStatus.NO_CAREER_CLAIMS


# ===========================================================================
# 14.9 Mixed-Claim Isolation & Cross-Clause Boundaries
# ===========================================================================

def test_mixed_claims_in_same_sentence():
    """A sentence with valid ($100M+ career) and invalid (85% cost cut) claims fails overall."""
    draft = "Across my career, I delivered $100M+ in enterprise revenue while driving an 85% reduction in cloud infrastructure costs."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert "FACT_CAREER_IMPACT" in res.verified_fact_ids
    assert any("85%" in u.extracted_text for u in res.unsupported_claims)


def test_mixed_claims_across_clauses_no_context_leak():
    """At CDW I influenced $4M in annual revenue, and at Stripe I closed $2.1M in services (CDW context must not leak to Stripe)."""
    draft = "At CDW, I influenced $4M in annual revenue, and at Stripe I closed $2.1M in services."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert "FACT_CDW_REVENUE" in res.verified_fact_ids
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
    assert "FACT_GOOGLE_REVENUE" in res.verified_fact_ids
    assert any("netflix" in u.reason.lower() or "$50m" in u.reason.lower() for u in res.unsupported_claims)


# ===========================================================================
# 14.10 Scribe Post-Generation & Fallback Revalidation
# ===========================================================================

def test_scribe_valid_grounded_draft_returned():
    """When Gemini returns a grounded draft, Scribe returns it unchanged."""
    valid_draft = (
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
    mock_response.text = valid_draft
    mock_client.models.generate_content.return_value = mock_response

    with patch("backend.radar.scribe_service.get_gemini_client", return_value=mock_client):
        result = generate_executive_reply(email, profile)
        assert result == valid_draft


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
        val = validate_canonical_grounding(result)
        assert val.is_grounded is True


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
            val = validate_canonical_grounding(result)
            assert val.is_grounded is True


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
    good_draft = "At Google, I influenced $8M in new Google Cloud revenue and delivered $100M+ across my career."
    val = validate_canonical_grounding(good_draft)
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

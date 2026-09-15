"""
Aura Mail AI - Phase 5.5 Provenance-Backed Grounding & Advisory Scanner Test Suite
Validates the hybrid grounding architecture:
- Authoritative server-side provenance and deterministic template regeneration.
- Advisory scanner demotion for manual and edited prose (never returns GROUNDED).
- Edit invalidation, provenance attack defense, mixed-content handling, and lifecycle persistence.
"""

import pytest
from backend.canonical_grounding import (
    validate_canonical_grounding,
    generate_canonical_claim,
    verify_provenance_claim,
    get_available_templates,
    GroundingStatus,
    ClaimStatus,
    ClaimCategory,
    CANONICAL_CLAIM_TEMPLATES,
    PROVENANCE_STORE,
    ProvenanceStore
)


# ===========================================================================
# 19.1 Valid Generation Tests
# ===========================================================================

def test_phase55_valid_generation_returns_opaque_id_and_deterministic_text():
    """Section 19.1: Valid fact + template generates deterministic text with server-side provenance."""
    claim = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id="draft_p55_1")
    assert claim["canonical_fact_id"] == "FACT_GOOGLE_REVENUE"
    assert claim["template_id"] == "TPL_GOOGLE_REVENUE_CONCISE"
    assert claim["rendered_text"] == "At Google, I influenced $8M in new Google Cloud revenue."
    assert claim["claim_instance_id"].startswith("claim_inst_")
    assert claim["status"] == GroundingStatus.GROUNDED.value

    # Verify server-side provenance record exists
    rec = PROVENANCE_STORE.get_claim_instance(claim["claim_instance_id"])
    assert rec is not None
    assert rec.canonical_fact_id == "FACT_GOOGLE_REVENUE"
    assert rec.template_id == "TPL_GOOGLE_REVENUE_CONCISE"
    assert rec.exact_rendered_text == claim["rendered_text"]
    assert rec.is_invalidated is False
    assert rec.draft_id == "draft_p55_1"


def test_phase55_repeated_generation_produces_separately_managed_instances():
    """Section 19.1: Repeated generation produces separate opaque claim instances."""
    c1 = generate_canonical_claim("FACT_CDW_SERVICES", draft_id="draft_p55_2")
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", draft_id="draft_p55_2")
    assert c1["claim_instance_id"] != c2["claim_instance_id"]
    assert c1["rendered_text"] == c2["rendered_text"]


def test_phase55_generation_rejects_incompatible_or_unknown_facts():
    """Section 19.1: Generation rejects unknown or mismatched fact/template requests."""
    with pytest.raises(ValueError):
        generate_canonical_claim("FACT_UNKNOWN_FICTIONAL", draft_id="draft_p55_3")

    with pytest.raises(ValueError):
        generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_CDW_SERVICES_CONCISE", draft_id="draft_p55_3")

    with pytest.raises(ValueError):
        generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id="")


# ===========================================================================
# 19.2 Valid Grounding Tests
# ===========================================================================

def test_phase55_untouched_claim_returns_grounded():
    """Section 19.2: Untouched provenance claim in draft returns GROUNDED."""
    did = "draft_p55_untouched"
    c = generate_canonical_claim("FACT_CAREER_IMPACT", template_id="TPL_CAREER_ENTERPRISE_REVENUE_CONCISE", draft_id=did)
    draft = f"Hi Sarah,\n\n{c['rendered_text']}\n\nBest,\nBrian"

    start_off = draft.index(c['rendered_text'])
    end_off = start_off + len(c['rendered_text'])
    binding = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "b0",
        "start_offset": start_off,
        "end_offset": end_off,
        "submitted_block_text": c["rendered_text"]
    }
    res = validate_canonical_grounding(draft, claim_bindings=[binding], draft_id=did)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert res.requires_human_review is False
    assert len(res.supported_claims) == 1
    assert res.supported_claims[0].fact_id == "FACT_CAREER_IMPACT"
    assert len(res.unsupported_claims) == 0


def test_phase55_multiple_untouched_claims_return_grounded():
    """Section 19.2: Multiple valid provenance claims in one draft return GROUNDED."""
    did = "draft_p55_multi"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", template_id="TPL_CDW_SERVICES_CONCISE", draft_id=did)
    draft = f"Hi,\n\n{c1['rendered_text']}\n{c2['rendered_text']}\n\nBest regards,\nBrian"

    s1 = draft.index(c1['rendered_text'])
    e1 = s1 + len(c1['rendered_text'])
    s2 = draft.index(c2['rendered_text'])
    e2 = s2 + len(c2['rendered_text'])

    b1 = {"claim_instance_id": c1["claim_instance_id"], "draft_id": did, "block_id": "b1", "start_offset": s1, "end_offset": e1, "submitted_block_text": c1["rendered_text"]}
    b2 = {"claim_instance_id": c2["claim_instance_id"], "draft_id": did, "block_id": "b2", "start_offset": s2, "end_offset": e2, "submitted_block_text": c2["rendered_text"]}

    res = validate_canonical_grounding(draft, claim_bindings=[b1, b2], draft_id=did)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert len(res.supported_claims) == 2
    assert "FACT_GOOGLE_REVENUE" in res.verified_fact_ids
    assert "FACT_CDW_SERVICES" in res.verified_fact_ids


# ===========================================================================
# 19.3 Text Mutation & Edit Invalidation Tests
# ===========================================================================

@pytest.mark.parametrize("edit_desc, mutated_text", [
    ("one-character edit", "At Google, I influenced $8M in new Google Cloud revenue!"),
    ("employer change", "At Microsoft, I influenced $8M in new Google Cloud revenue."),
    ("amount change", "At Google, I influenced $9M in new Google Cloud revenue."),
    ("percentage change", "At Promevo, I achieved a 24% POC-to-production conversion rate."),
    ("plus-sign change", "Across my career, I influenced and delivered $100M in enterprise revenue."),
    ("title change", "I served as Chief Architect at Google from 2019 to 2021."),
    ("date change", "I served as Cloud Customer Engineer at Google from 2018 to 2021."),
    ("status change", "I currently serve as Cloud Customer Engineer at Google."),
    ("attribution-verb change", "At Google, I generated $8M in new Google Cloud revenue."),
    ("inserted negation", "At Google, I did not influence $8M in new Google Cloud revenue."),
    ("inserted uncertainty", "At Google, I perhaps influenced $8M in new Google Cloud revenue."),
    ("appended clause", "At Google, I influenced $8M in new Google Cloud revenue, beating quota."),
    ("prepended clause", "While leading teams at Google, I influenced $8M in new Google Cloud revenue."),
    ("inserted parenthetical", "At Google (Cloud division), I influenced $8M in new Google Cloud revenue.")
])
def test_phase55_mutated_text_loses_grounding(edit_desc, mutated_text):
    """Section 19.3: Any text mutation immediately strips GROUNDED authority."""
    did = "draft_p55_mutate"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    mutated_claim = dict(c)
    mutated_claim["rendered_text"] = mutated_text

    res = validate_canonical_grounding(mutated_text, provenance_claims=[mutated_claim], draft_id=did)
    assert res.is_grounded is False, f"Mutated text ({edit_desc}) was falsely grounded: {mutated_text}"
    assert res.status in [
        GroundingStatus.UNVERIFIED,
        GroundingStatus.POTENTIAL_CONFLICT,
        GroundingStatus.UNSUPPORTED,
        GroundingStatus.INDETERMINATE,
        GroundingStatus.MIXED_REVIEW_REQUIRED
    ]
    assert res.requires_human_review is True


# ===========================================================================
# 19.4 Provenance Attack Tests
# ===========================================================================

def test_phase55_fabricated_claim_id_fails_closed():
    """Section 19.4: Fabricated or unknown claim ID fails closed."""
    bogus_claim = {
        "claim_instance_id": "claim_inst_fabricated_bogus_12345",
        "canonical_fact_id": "FACT_GOOGLE_REVENUE",
        "template_id": "TPL_GOOGLE_REVENUE_CONCISE",
        "rendered_text": "At Google, I influenced $8M in new Google Cloud revenue."
    }
    res = validate_canonical_grounding(bogus_claim["rendered_text"], provenance_claims=[bogus_claim], draft_id="draft_bogus")
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNVERIFIED, GroundingStatus.POTENTIAL_CONFLICT]


def test_phase55_draft_mismatch_fails_closed():
    """Section 19.4: Claim ID bound to another draft fails closed."""
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id="draft_abc_123")
    res = validate_canonical_grounding(
        c["rendered_text"],
        provenance_claims=[c],
        draft_id="draft_xyz_999"  # Mismatched draft ID
    )
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.VALIDATION_FAILED, GroundingStatus.UNVERIFIED, GroundingStatus.POTENTIAL_CONFLICT]


def test_phase55_invalidated_claim_cannot_be_replayed():
    """Section 19.4: Invalidated claim instance cannot be replayed."""
    did = "draft_p55_inval"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    PROVENANCE_STORE.invalidate_claim_instance(c["claim_instance_id"], reason="Manual draft edit")

    res = validate_canonical_grounding(c["rendered_text"], provenance_claims=[c], draft_id=did)
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNVERIFIED, GroundingStatus.POTENTIAL_CONFLICT]


def test_phase55_deleted_provenance_store_fails_closed(tmp_path):
    """Section 19.4: Missing provenance record in storage fails closed."""
    empty_store = ProvenanceStore(storage_path=tmp_path / "empty_prov.json")
    is_valid, status, reason, supp = verify_provenance_claim(
        "claim_inst_nonexistent", "Some claim", draft_id="draft_test",
        start_offset=0, end_offset=len("Some claim"), draft_text="Some claim"
    )
    assert is_valid is False
    assert status == ClaimStatus.UNVERIFIED


# ===========================================================================
# 19.5 Manual Prose Fail-Closed Tests (Section 19.5)
# ===========================================================================

@pytest.mark.parametrize("manual_prose", [
    # Accurate facts without provenance
    "At Google, I influenced $8M in new Google Cloud revenue.",
    "Across my career, I influenced and delivered $100M+ in enterprise revenue.",
    "At CDW, I closed $2.1M in professional services.",
    "I worked at Google from 2019 to 2021.",
    # Contradictions and attacks
    "At Google, I influenced $8M in globex revenue.",
    "I influenced $8M in new googleplex revenue.",
    "At Google, I influenced $8M in revenue belonging to Globex.",
    "I worked at Google as of 2018.",
    "I remain working at Pythian.",
    "Pythian continues to employ me.",
    "I had a job at MavenCode.",
    "I perhaps influenced $8M in new Google Cloud revenue at Google.",
    "I do not think I influenced $8M in new Google Cloud revenue at Google.",
    "I am not certain that I influenced $8M in new Google Cloud revenue at Google."
])
def test_phase55_manual_prose_never_becomes_grounded(manual_prose):
    """Section 19.5: Manual, typed, or unprovenanced prose CANNOT receive GROUNDED authority."""
    res = validate_canonical_grounding(manual_prose)
    assert res.is_grounded is False, f"Manual prose was improperly grounded: {manual_prose}"
    assert res.status != GroundingStatus.GROUNDED
    assert res.status in [
        GroundingStatus.UNVERIFIED,
        GroundingStatus.POTENTIAL_CONFLICT,
        GroundingStatus.UNSUPPORTED,
        GroundingStatus.INDETERMINATE
    ]


def test_phase55_non_career_prose_returns_no_career_claims_detected():
    """Section 19.5: Non-career conversational prose returns NO_CAREER_CLAIMS_DETECTED (not verified safe)."""
    general_email = "Hi Sarah,\n\nThank you for reaching out. When are you free for a call next week?\n\nBest,\nBrian"
    res = validate_canonical_grounding(general_email)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.NO_CAREER_CLAIMS_DETECTED
    assert "No authoritative career grounding was performed" in res.validation_summary


# ===========================================================================
# 19.6 Mixed Content Tests
# ===========================================================================

def test_phase55_grounded_claim_plus_manual_career_prose_returns_mixed_review():
    """Section 19.6: Grounded claim + manual career prose returns MIXED_REVIEW_REQUIRED."""
    did = "draft_p55_mixed"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    mixed_draft = f"Hi Sarah,\n\n{c['rendered_text']}\n\nAlso, at Amazon I generated $50M in cloud revenue.\n\nBest,\nBrian"

    start_off = mixed_draft.index(c['rendered_text'])
    end_off = start_off + len(c['rendered_text'])
    b = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "b0",
        "start_offset": start_off,
        "end_offset": end_off,
        "submitted_block_text": c["rendered_text"]
    }
    res = validate_canonical_grounding(mixed_draft, claim_bindings=[b], draft_id=did)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.MIXED_REVIEW_REQUIRED
    assert res.requires_human_review is True
    assert len(res.supported_claims) == 1
    assert len(res.unsupported_claims) >= 1


def test_phase55_grounded_claim_plus_greeting_is_grounded():
    """Section 19.6: Grounded claim + standard non-career greeting/closing is grounded."""
    did = "draft_p55_greet"
    c = generate_canonical_claim("FACT_CDW_SERVICES", template_id="TPL_CDW_SERVICES_CONCISE", draft_id=did)
    draft = f"Hi Sarah,\n\nThank you for reaching out.\n\n{c['rendered_text']}\n\nLooking forward to speaking.\n\nBest regards,\nBrian"

    start_off = draft.index(c['rendered_text'])
    end_off = start_off + len(c['rendered_text'])
    b = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "b0",
        "start_offset": start_off,
        "end_offset": end_off,
        "submitted_block_text": c["rendered_text"]
    }
    res = validate_canonical_grounding(draft, claim_bindings=[b], draft_id=did)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert len(res.supported_claims) == 1
    assert len(res.unsupported_claims) == 0


# ===========================================================================
# 19.7 Advisory Scanner Tests
# ===========================================================================

def test_phase55_advisory_scanner_identifies_potential_conflicts():
    """Section 19.7: Advisory scanner flags potential conflicts in manual prose."""
    conflict_draft = "At Google, I influenced $8M in Globex revenue."
    res = validate_canonical_grounding(conflict_draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.POTENTIAL_CONFLICT
    assert any(u.status in [ClaimStatus.POTENTIAL_CONFLICT, ClaimStatus.MISATTRIBUTED] for u in res.unsupported_claims)


def test_phase55_advisory_scanner_identifies_unresolved_assertions():
    """Section 19.7: Advisory scanner flags unresolved employment assertions as INDETERMINATE."""
    unparsed_draft = "During my years leading technical teams, I managed large cloud systems."
    res = validate_canonical_grounding(unparsed_draft)
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.INDETERMINATE, GroundingStatus.POTENTIAL_CONFLICT]


# ===========================================================================
# 19.8 Persistence & Lifecycle Tests
# ===========================================================================

def test_phase55_provenance_store_persists_across_instances(tmp_path):
    """Section 19.8: Provenance records persist across store reloads."""
    store_file = tmp_path / "test_provenance.json"
    s1 = ProvenanceStore(storage_path=store_file)
    rec1 = s1.create_claim_instance("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id="draft_persist_1")

    # Reload in a new store instance
    s2 = ProvenanceStore(storage_path=store_file)
    rec2 = s2.get_claim_instance(rec1.claim_instance_id)
    assert rec2 is not None
    assert rec2.canonical_fact_id == rec1.canonical_fact_id
    assert rec2.exact_rendered_text == rec1.exact_rendered_text
    assert rec2.draft_id == "draft_persist_1"


def test_phase55_draft_invalidation_lifecycle():
    """Section 19.8: Draft invalidation invalidates all claims bound to draft_id."""
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id="draft_test_1")
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", draft_id="draft_test_1")

    # Invalidate draft
    count = PROVENANCE_STORE.invalidate_draft_claims("draft_test_1", reason="User edited draft in Outlook")
    assert count == 2

    # Verify both fail validation
    is_valid1, _, _, _ = verify_provenance_claim(c1["claim_instance_id"], c1["rendered_text"], draft_id="draft_test_1")
    is_valid2, _, _, _ = verify_provenance_claim(c2["claim_instance_id"], c2["rendered_text"], draft_id="draft_test_1")
    assert is_valid1 is False
    assert is_valid2 is False

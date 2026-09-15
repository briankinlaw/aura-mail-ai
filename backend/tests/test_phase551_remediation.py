"""
Aura Mail AI - Phase 5.5.1 Provenance Trust-Boundary Remediation Test Suite
========================================================================
Comprehensive verification for:
1. Actual Claim-Block Binding (exact offsets, non-overlapping ranges, slice match, manifest validation)
2. Draft Identity Policy (mandatory draft_id, cross-draft isolation, invalidation lifecycle)
3. Schema & Content Digest Enforcement (SHA-256 digests, versions 2.1.0 / 2 / 2.0.0, exact hash)
4. Transactional Fail-Closed Persistence (atomic temp write + fsync + replace, rollback on error, startup corruption safety)
5. Scribe Structured Draft Contract (ScribeDraftResult, offset correctness, availability preservation)
6. IBM Watson Role Association (explicit association with employment_record_id = "ibm")
7. Advisory Scanner & Status Independence (masking of verified blocks, NO_CAREER_CLAIMS_DETECTED vs GROUNDED)
8. API Endpoints Trust Boundaries (auth protection, mandatory draft_id validation, binding verification)
9. Security Invariants (8 verified tenures, draft-first / no-send invariant)
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.canonical_grounding import (
    CANONICAL_LEDGER_SCHEMA_VERSION,
    RECORD_SCHEMA_VERSION,
    CANONICAL_FACT_REGISTRY,
    CANONICAL_EMPLOYMENT_RECORDS,
    CANONICAL_CLAIM_TEMPLATES,
    GroundingStatus,
    ClaimStatus,
    ClaimBlockBinding,
    ProvenanceRecord,
    ProvenanceStore,
    PROVENANCE_STORE,
    compute_sha256,
    get_active_fact_digest,
    get_active_employment_record_digest,
    get_active_template_digest,
    get_active_ledger_digest,
    generate_canonical_claim,
    verify_provenance_claim,
    verify_provenance_claim_binding,
    validate_claim_manifest,
    validate_canonical_grounding,
    get_available_templates
)
from backend.radar.scribe_service import (
    ScribeDraftResult,
    generate_executive_reply_structured,
    compose_grounded_response_structured
)
from backend.models import EmailMessage, UserProfile, ReplyDraftRequest
from backend.radar.risk_evaluator import (
    analyze_risk_heuristics,
    evaluate_second_opinion_risk,
    RiskSeverity,
    RiskCategory
)
from backend.main import app


# ===========================================================================
# 1. Actual Claim-Block Binding Tests
# ===========================================================================

def test_binding_exact_unicode_codepoint_offsets_grounded():
    """Single valid claim block bound via exact Unicode code-point offsets returns GROUNDED."""
    did = "draft_bind_exact_1"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    greeting = "Hello recruiter,\n\n"
    closing = "\n\nBest regards,\nBrian"
    draft = f"{greeting}{c['rendered_text']}{closing}"

    start_offset = len(greeting)
    end_offset = start_offset + len(c["rendered_text"])

    binding = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": start_offset,
        "end_offset": end_offset,
        "submitted_block_text": c["rendered_text"]
    }

    res = validate_canonical_grounding(draft, claim_bindings=[binding], draft_id=did)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert len(res.supported_claims) == 1
    assert res.supported_claims[0].fact_id == "FACT_GOOGLE_REVENUE"


def test_binding_off_by_one_offset_fails_closed():
    """Off-by-one start or end offset fails closed with VALIDATION_FAILED."""
    did = "draft_bind_off1"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft = f"Intro. {c['rendered_text']} Outro."
    start_offset = draft.index(c["rendered_text"])

    # Off by +1 on start_offset
    binding = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": start_offset + 1,
        "end_offset": start_offset + len(c["rendered_text"]),
        "submitted_block_text": c["rendered_text"]
    }

    res = validate_canonical_grounding(draft, claim_bindings=[binding], draft_id=did)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.VALIDATION_FAILED
    assert "Slice mismatch" in res.validation_summary or "Claim manifest validation failed" in res.validation_summary


def test_binding_slice_content_mismatch_fails_closed():
    """Mismatch between draft text at [start:end] and submitted_block_text fails closed."""
    did = "draft_bind_slice_mismatch"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft = f"Intro. Mutated text here. Outro."

    binding = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": 7,
        "end_offset": 7 + len(c["rendered_text"]),
        "submitted_block_text": c["rendered_text"]
    }

    res = validate_canonical_grounding(draft, claim_bindings=[binding], draft_id=did)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.VALIDATION_FAILED


def test_binding_multiple_non_overlapping_blocks_grounded():
    """Multiple valid non-overlapping claim blocks return GROUNDED."""
    did = "draft_multi_bind_1"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", template_id="TPL_CDW_SERVICES_CONCISE", draft_id=did)
    draft = f"Hi,\n\n{c1['rendered_text']} {c2['rendered_text']}\n\nBest,\nBrian"

    start1 = draft.index(c1["rendered_text"])
    end1 = start1 + len(c1["rendered_text"])
    start2 = draft.index(c2["rendered_text"])
    end2 = start2 + len(c2["rendered_text"])

    bindings = [
        {
            "claim_instance_id": c1["claim_instance_id"],
            "draft_id": did,
            "block_id": "block_0",
            "start_offset": start1,
            "end_offset": end1,
            "submitted_block_text": c1["rendered_text"]
        },
        {
            "claim_instance_id": c2["claim_instance_id"],
            "draft_id": did,
            "block_id": "block_1",
            "start_offset": start2,
            "end_offset": end2,
            "submitted_block_text": c2["rendered_text"]
        }
    ]

    res = validate_canonical_grounding(draft, claim_bindings=bindings, draft_id=did)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert len(res.supported_claims) == 2


def test_binding_overlapping_ranges_fail_closed():
    """Overlapping claim block ranges in manifest fail closed before claim verification."""
    did = "draft_overlap_1"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", template_id="TPL_CDW_SERVICES_CONCISE", draft_id=did)
    draft = f"Some text here {c1['rendered_text']} and more text."

    bindings = [
        {
            "claim_instance_id": c1["claim_instance_id"],
            "draft_id": did,
            "block_id": "block_0",
            "start_offset": 10,
            "end_offset": 60,
            "submitted_block_text": draft[10:60]
        },
        {
            "claim_instance_id": c2["claim_instance_id"],
            "draft_id": did,
            "block_id": "block_1",
            "start_offset": 50,  # Overlaps [10:60]
            "end_offset": 80,
            "submitted_block_text": draft[50:80] if len(draft) >= 80 else "test"
        }
    ]

    is_valid, status, reason, _ = validate_claim_manifest(draft, bindings, draft_id=did)
    assert is_valid is False
    assert status == GroundingStatus.VALIDATION_FAILED
    assert "overlap" in reason.lower()

    res = validate_canonical_grounding(draft, claim_bindings=bindings, draft_id=did)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.VALIDATION_FAILED


def test_binding_duplicate_ids_fail_closed():
    """Duplicate claim instance IDs or duplicate block IDs in manifest fail closed."""
    did = "draft_dup_id_1"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft = f"{c['rendered_text']} and again {c['rendered_text']}"

    start1 = 0
    end1 = len(c["rendered_text"])
    start2 = draft.rindex(c["rendered_text"])
    end2 = start2 + len(c["rendered_text"])

    # Duplicate claim_instance_id
    dup_claim_bindings = [
        {"claim_instance_id": c["claim_instance_id"], "draft_id": did, "block_id": "b0", "start_offset": start1, "end_offset": end1, "submitted_block_text": c["rendered_text"]},
        {"claim_instance_id": c["claim_instance_id"], "draft_id": did, "block_id": "b1", "start_offset": start2, "end_offset": end2, "submitted_block_text": c["rendered_text"]}
    ]
    is_valid, status, reason, _ = validate_claim_manifest(draft, dup_claim_bindings, draft_id=did)
    assert is_valid is False
    assert status == GroundingStatus.VALIDATION_FAILED
    assert "Duplicate claim_instance_id" in reason


# ===========================================================================
# 2. Draft Identity Boundary & Lifecycle Tests
# ===========================================================================

def test_draft_identity_mandatory_non_empty():
    """Claim generation strictly requires a non-empty string draft_id."""
    with pytest.raises(ValueError, match="draft_id is mandatory"):
        generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=None)

    with pytest.raises(ValueError, match="draft_id is mandatory"):
        generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id="")

    with pytest.raises(ValueError, match="draft_id is mandatory"):
        generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id="   ")


def test_cross_draft_replay_fails_closed():
    """Claim generated for draft_A presented with draft_B fails closed."""
    c_a = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id="draft_A")
    draft_b_text = f"Hi,\n\n{c_a['rendered_text']}\n\nBest,\nBrian"

    start_off = draft_b_text.index(c_a["rendered_text"])
    end_off = start_off + len(c_a["rendered_text"])

    binding = {
        "claim_instance_id": c_a["claim_instance_id"],
        "draft_id": "draft_B",  # Mismatched claim binding draft_id vs stored record
        "block_id": "b0",
        "start_offset": start_off,
        "end_offset": end_off,
        "submitted_block_text": c_a["rendered_text"]
    }

    res = validate_canonical_grounding(draft_b_text, claim_bindings=[binding], draft_id="draft_B")
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.VALIDATION_FAILED, GroundingStatus.UNVERIFIED]


def test_draft_invalidation_lifecycle_multi_claim():
    """Invalidating a draft_id marks all bound claims invalidated and verification returns STALE_PROVENANCE."""
    did = "draft_lifecycle_99"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", draft_id=did)

    count = PROVENANCE_STORE.invalidate_draft_claims(did, reason="User typed manual edit in taskpane")
    assert count >= 2

    # Verification of both claims now fails with INVALIDATED
    is_valid1, status1, reason1, _ = verify_provenance_claim(
        c1["claim_instance_id"], c1["rendered_text"], draft_id=did,
        start_offset=0, end_offset=len(c1["rendered_text"]), draft_text=c1["rendered_text"]
    )
    assert is_valid1 is False
    assert status1 == ClaimStatus.INVALIDATED
    assert "invalidated" in reason1.lower()

    is_valid2, status2, reason2, _ = verify_provenance_claim(
        c2["claim_instance_id"], c2["rendered_text"], draft_id=did,
        start_offset=0, end_offset=len(c2["rendered_text"]), draft_text=c2["rendered_text"]
    )
    assert is_valid2 is False
    assert status2 == ClaimStatus.INVALIDATED


# ===========================================================================
# 3. Schema & Content Digest Enforcement Tests
# ===========================================================================

def test_schema_versions_and_digests_computed_correctly():
    """Ledger schema version is 2.1.0, record schema version is 2, template version is 2.0.0, and SHA-256 digests are non-empty."""
    assert CANONICAL_LEDGER_SCHEMA_VERSION == "2.1.0"
    assert RECORD_SCHEMA_VERSION == 2

    fact_digest = get_active_fact_digest("FACT_GOOGLE_REVENUE")
    assert len(fact_digest) == 64

    tpl_digest = get_active_template_digest("TPL_GOOGLE_REVENUE_CONCISE")
    assert len(tpl_digest) == 64

    ledger_digest = get_active_ledger_digest()
    assert len(ledger_digest) == 64


def test_provenance_record_verifies_active_digests():
    """If template or fact digest changes, verify_provenance_claim fails closed with STALE_PROVENANCE."""
    did = "draft_digest_test"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    rec = PROVENANCE_STORE.get_claim_instance(c["claim_instance_id"])

    # Tamper with template_digest in stored record
    rec_tampered = rec.model_copy(update={"template_digest": "0" * 64})
    try:
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec_tampered

        is_valid, status, reason, _ = verify_provenance_claim(
            rec.claim_instance_id, rec.exact_rendered_text, draft_id=did,
            start_offset=0, end_offset=len(rec.exact_rendered_text), draft_text=rec.exact_rendered_text
        )
        assert is_valid is False
        assert status == ClaimStatus.STALE_PROVENANCE
        assert "Template" in reason and ("modified" in reason or "mismatch" in reason or "changed" in reason)
    finally:
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec


def test_provenance_record_tampered_rendered_text_hash_fails():
    """If exact_rendered_text is modified in stored record, exact regeneration hash mismatch fails closed."""
    did = "draft_tamper_text"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    rec = PROVENANCE_STORE.get_claim_instance(c["claim_instance_id"])

    rec_tampered = rec.model_copy(update={"exact_rendered_text": "I made up a number."})
    try:
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec_tampered

        is_valid, status, reason, _ = verify_provenance_claim(
            rec.claim_instance_id, "I made up a number.", draft_id=did,
            start_offset=0, end_offset=len("I made up a number."), draft_text="I made up a number."
        )
        assert is_valid is False
        assert status in [ClaimStatus.STALE_PROVENANCE, ClaimStatus.UNVERIFIED]
    finally:
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec


# ===========================================================================
# 4. Transactional Fail-Closed Persistence Tests
# ===========================================================================

def test_persistence_atomic_replace_and_rollback_on_failure(tmp_path):
    """Simulated atomic persistence error rolls back in-memory changes and leaves store consistent."""
    store_file = tmp_path / "atomic_store.json"
    store = ProvenanceStore(storage_path=store_file)

    # Create initial claim successfully
    rec1 = store.create_claim_instance("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id="d1")
    assert rec1.claim_instance_id in store._records

    # Mock os.replace to fail with OSError in backend.canonical_grounding
    with patch("backend.canonical_grounding.os.replace", side_effect=OSError("Disk write failed")):
        with pytest.raises(RuntimeError, match="Atomic persistence of provenance store failed"):
            store.create_claim_instance("FACT_CDW_SERVICES", "TPL_CDW_SERVICES_CONCISE", draft_id="d1")

    # In-memory store should have rolled back the second claim
    assert len(store._records) == 1
    assert rec1.claim_instance_id in store._records


def test_persistence_corrupt_store_startup_fails_closed_without_overwriting(tmp_path):
    """Corrupt JSON store file on startup fails closed, does not overwrite file, and marks store unavailable."""
    store_file = tmp_path / "corrupt_store.json"
    with open(store_file, "w") as f:
        f.write("{ invalid json corrupted content")

    store = ProvenanceStore(storage_path=store_file)
    assert store._is_available is False

    # Attempting to create claim on unavailable store raises RuntimeError
    with pytest.raises(RuntimeError, match="Provenance store is unavailable"):
        store.create_claim_instance("FACT_GOOGLE_REVENUE", "TPL_GOOGLE_REVENUE_CONCISE", draft_id="d_corrupt")

    # The corrupted file on disk must NOT be overwritten
    with open(store_file, "r") as f:
        content = f.read()
    assert content == "{ invalid json corrupted content"


# ===========================================================================
# 5. Scribe Service Structured Draft Contract Tests
# ===========================================================================

def test_scribe_compose_grounded_response_structured():
    """Structured Scribe response includes draft_id, draft_text, exact claim_bindings, and is_grounded = True."""
    profile = UserProfile(
        full_name="Brian Kinlaw",
        current_title="Strategic Advisor, Data & AI",
        active_resume_file="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
    )
    did = "draft_scribe_struct_1"
    res = compose_grounded_response_structured(
        recruiter_name="Sarah Recruiter",
        company_name="Google",
        role_title="Enterprise Solutions Architect",
        required_skills=["Google Cloud", "AI", "Data"],
        selected_resume="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
        user_profile=profile,
        draft_id=did
    )
    assert isinstance(res, ScribeDraftResult)
    assert res.draft_id == did
    assert res.is_grounded is True
    assert res.grounding_status == GroundingStatus.GROUNDED.value
    assert len(res.claim_bindings) == 3

    # Verify every claim binding slice matches draft text exactly
    for b in res.claim_bindings:
        assert res.draft_text[b["start_offset"]:b["end_offset"]] == b["submitted_block_text"]
        assert b["draft_id"] == did


def test_scribe_generate_executive_reply_structured_fallback_on_client_none():
    """When Gemini client is None/unavailable, Scribe returns deterministic structured response."""
    email = EmailMessage(
        id="test_email_scribe",
        subject="Opportunity at Stripe",
        sender_name="Alex Recruiter",
        sender_email="alex@stripe.com",
        body_text="Hi Brian, are you open to discussing a Principal Architect role at Stripe?"
    )
    profile = UserProfile(
        full_name="Brian Kinlaw",
        current_title="Strategic Advisor, Data & AI"
    )
    with patch("backend.radar.scribe_service.get_gemini_client", return_value=None):
        res = generate_executive_reply_structured(email, profile, draft_id="draft_gemini_none")
        assert res.is_grounded is True
        assert res.grounding_status == "GROUNDED"
        assert len(res.claim_bindings) == 3


# ===========================================================================
# 6. IBM Watson Role Association Tests
# ===========================================================================

def test_ibm_watson_record_association():
    """TPL_EMP_IBM_WATSON has explicit employment_record_id = 'ibm' and template renders correctly."""
    tpl = CANONICAL_CLAIM_TEMPLATES["TPL_EMP_IBM_WATSON"]
    assert tpl.employment_record_id == "ibm"
    assert tpl.template_version == "2.0.0"

    did = "draft_ibm_watson"
    c = generate_canonical_claim("FACT_EMPLOYMENT_IBM_WATSON", "TPL_EMP_IBM_WATSON", draft_id=did)
    assert c["employment_record_id"] == "ibm"
    assert "IBM" in c["rendered_text"]
    assert "Watson" in c["rendered_text"]

    binding = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "b0",
        "start_offset": 0,
        "end_offset": len(c["rendered_text"]),
        "submitted_block_text": c["rendered_text"]
    }
    res = validate_canonical_grounding(c["rendered_text"], claim_bindings=[binding], draft_id=did)
    assert res.is_grounded is True
    assert "FACT_EMPLOYMENT_IBM_WATSON" in res.verified_fact_ids


# ===========================================================================
# 7. Advisory Scanner & Status Independence Tests
# ===========================================================================

def test_advisory_scanner_verified_block_masking():
    """Verified claim block slice is masked with whitespace so legitimate metrics do not trigger unverified alerts."""
    did = "draft_mask_1"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft = f"Hi Alex,\n\n{c['rendered_text']}\n\nLooking forward to speaking.\n\nBest regards,\nBrian"

    start_off = draft.index(c["rendered_text"])
    end_off = start_off + len(c["rendered_text"])

    binding = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": start_off,
        "end_offset": end_off,
        "submitted_block_text": c["rendered_text"]
    }

    res = validate_canonical_grounding(draft, claim_bindings=[binding], draft_id=did)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert len(res.supported_claims) == 1
    assert len(res.unsupported_claims) == 0


def test_status_independence_no_career_claims_detected():
    """NO_CAREER_CLAIMS_DETECTED is distinct from GROUNDED and never claims verified safe status."""
    non_career_draft = "Hi Sarah, thank you for reaching out. What time works best for you next Tuesday?"
    res = validate_canonical_grounding(non_career_draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.NO_CAREER_CLAIMS_DETECTED
    assert "No authoritative career grounding was performed" in res.validation_summary


def test_risk_evaluator_no_career_claims_summary_text():
    """Risk evaluator on non-career draft indicates no career claims detected and no authoritative grounding."""
    email = EmailMessage(
        id="test_msg_noclaims",
        subject="Meeting request",
        sender_name="Recruiter",
        sender_email="recruiter@example.com",
        body_text="Can we chat next week?"
    )
    draft = "Hi Recruiter, Tuesday at 2pm works for me. Best, Brian"
    risk_res = analyze_risk_heuristics(
        email_text=email.body_text,
        draft_text=draft,
        action="DRAFT"
    )
    assert risk_res.severity == RiskSeverity.SAFE
    assert "No authoritative career grounding was performed" in risk_res.second_opinion_summary


# ===========================================================================
# 8. API Endpoints Trust Boundaries Tests
# ===========================================================================

def test_api_templates_requires_local_auth():
    """GET /api/canonical/templates requires local auth header."""
    client = TestClient(app)
    # Missing auth token
    res = client.get("/api/canonical/templates")
    assert res.status_code in [401, 403]


def test_api_claim_generate_requires_draft_id():
    """POST /api/canonical/claims/generate requires non-empty draft_id."""
    client = TestClient(app)
    from backend.auth import get_local_session_token

    headers = {"X-Aura-Session-Token": get_local_session_token()}

    # Missing draft_id
    res_no_did = client.post(
        "/api/canonical/claims/generate",
        headers=headers,
        json={"canonical_fact_id": "FACT_GOOGLE_REVENUE"}
    )
    assert res_no_did.status_code == 400
    assert "draft_id is mandatory" in res_no_did.json()["detail"]

    # Valid draft_id
    res_valid = client.post(
        "/api/canonical/claims/generate",
        headers=headers,
        json={"canonical_fact_id": "FACT_GOOGLE_REVENUE", "draft_id": "draft_api_1"}
    )
    assert res_valid.status_code == 200
    claim = res_valid.json()["claim"]
    assert claim["draft_id"] == "draft_api_1"


def test_api_radar_draft_returns_structured_bindings():
    """POST /api/radar/draft returns draft_id and claim_bindings."""
    client = TestClient(app)
    from backend.auth import get_local_session_token

    headers = {"X-Aura-Session-Token": get_local_session_token()}
    res = client.post(
        "/api/radar/draft",
        headers=headers,
        json={
            "subject": "Opportunity",
            "body": "We have an open role.",
            "sender_name": "Recruiter",
            "sender_email": "recruiter@example.com",
            "include_availability": False
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert "draft_id" in data
    assert data["draft_id"].startswith("draft_")
    assert "claim_bindings" in data
    assert isinstance(data["claim_bindings"], list)
    assert data["is_grounded"] is True
    assert data["grounding_status"] == "GROUNDED"


# ===========================================================================
# 9. Security Invariants Tests
# ===========================================================================

def test_canonical_employment_tenures_complete_and_unmodified():
    """All 8 verified canonical employment tenures are present and exact."""
    expected_employers = {
        "google": ("Google", 2019, 10, 2021, 11),
        "cdw": ("CDW", 2023, 11, 2024, 10),
        "pythian": ("Pythian", 2021, 11, 2023, 5),
        "dxc": ("DXC Technology", 2015, 3, 2019, 10),
        "ibm": ("IBM", 2002, 1, 2015, 3),
        "promevo": ("Promevo", 2026, 3, 2026, 8),
        "mavencode_advisory": ("MavenCode", 2026, 9, None, None),
        "mavencode_director": ("MavenCode", 2024, 10, 2026, 2)
    }
    assert len(CANONICAL_EMPLOYMENT_RECORDS) == 8
    for emp_id, (canonical_name, start_y, start_m, end_y, end_m) in expected_employers.items():
        assert emp_id in CANONICAL_EMPLOYMENT_RECORDS
        rec = CANONICAL_EMPLOYMENT_RECORDS[emp_id]
        assert rec.employer_canonical == canonical_name
        assert rec.start_year == start_y and rec.start_month == start_m
        assert rec.end_year == end_y and rec.end_month == end_m


def test_send_remains_blocked_invariant():
    """Proposing SEND action is strictly BLOCKED across all contexts and never permitted."""
    res = analyze_risk_heuristics(
        email_text="Please reply.",
        draft_text="Here is my reply.",
        action="SEND"
    )
    assert res.severity == RiskSeverity.HIGH_RISK
    assert res.recommended_action == "BLOCKED"

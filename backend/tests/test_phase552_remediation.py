"""
Aura Mail AI - Phase 5.5.2 Provenance Trust-Boundary Remediation Test Suite
========================================================================
Comprehensive verification covering:
1. Failure A: Standalone authoritative verification elimination (fails closed without complete binding context).
2. Failure B: Elimination of legacy text-search offset reconstruction (explicit bindings only).
3. Failure C: Mandatory fail-closed versions and digests enforcement (presence, format, equality).
4. Failure D: Complete web-cockpit provenance lifecycle (structured generation, cache preservation, edit invalidation, save-draft validation).
5. Strict manifest validation (bounds, duplicate IDs, overlapping ranges, slice matching).
6. Security invariants (zero-transmission invariant, 8 canonical employment tenures, IBM Watson role association).
"""

import os
import json
import time
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
    is_valid_sha256,
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
from backend.providers.base import ProviderOperationResult
from backend.radar.risk_evaluator import (
    analyze_risk_heuristics,
    evaluate_second_opinion_risk,
    RiskSeverity,
    RiskCategory
)
from backend.auth import get_local_session_token
from backend.main import app, CACHED_EMAILS


@pytest.fixture(autouse=True)
def clean_provenance_state():
    """Ensure clean in-memory provenance store state for each test."""
    PROVENANCE_STORE._is_available = True
    PROVENANCE_STORE._load_error = None
    yield
    # Cleanup any invalid records that might have been created during test
    invalid_ids = [
        cid for cid, r in PROVENANCE_STORE._records.items()
        if not r.template_version or r.record_schema_version != RECORD_SCHEMA_VERSION
    ]
    for cid in invalid_ids:
        PROVENANCE_STORE._records.pop(cid, None)


# ===========================================================================
# 1. Failure A Regression: Elimination of Standalone Verification
# ===========================================================================

def test_failure_a_standalone_verification_fails_closed():
    """Standalone claim verification without draft_text and offsets must fail closed (VALIDATION_FAILED)."""
    did = "draft_fail_a_1"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)

    # Calling verify_provenance_claim without draft_text and offsets must return False and VALIDATION_FAILED
    is_valid, status, reason, supp = verify_provenance_claim(
        claim_instance_id=c["claim_instance_id"],
        submitted_text=c["rendered_text"],
        draft_id=did
    )
    assert is_valid is False
    assert status == ClaimStatus.VALIDATION_FAILED
    assert "Missing required binding context" in reason or "standalone verification disabled" in reason
    assert supp is None


def test_failure_a_api_verify_missing_offsets_fails_closed():
    """POST /api/canonical/claims/verify without offsets returns VALIDATION_FAILED transport status."""
    client = TestClient(app)
    headers = {"X-Aura-Session-Token": get_local_session_token()}
    did = "draft_api_fail_a"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)

    res = client.post(
        "/api/canonical/claims/verify",
        headers=headers,
        json={
            "claim_instance_id": c["claim_instance_id"],
            "submitted_text": c["rendered_text"],
            "draft_id": did
            # Missing start_offset, end_offset, block_id, draft_text
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "VALIDATION_FAILED"
    assert data["is_valid"] is False
    assert data["claim_status"] == ClaimStatus.VALIDATION_FAILED.value
    assert data["claim"] is None


# ===========================================================================
# 2. Failure B Regression: Elimination of Legacy Text-Search Reconstruction
# ===========================================================================

def test_failure_b_legacy_text_search_cannot_reconstruct_offsets():
    """Detached provenance_claims without explicit claim_bindings fails closed and cannot produce GROUNDED."""
    did = "draft_fail_b_1"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft_text = f"Hello recruiter,\n\n{c['rendered_text']}\n\nBest,\nBrian"

    # Passing detached provenance_claims (without explicit claim_bindings)
    res = validate_canonical_grounding(
        draft_text=draft_text,
        provenance_claims=[
            {
                "claim_instance_id": c["claim_instance_id"],
                "draft_id": did,
                "text": c["rendered_text"]
            }
        ],
        draft_id=did
    )
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNVERIFIED, GroundingStatus.VALIDATION_FAILED, GroundingStatus.INDETERMINATE]
    assert len(res.supported_claims) == 0
    assert len(res.unsupported_claims) > 0


def test_failure_b_pasted_canonical_sentence_without_provenance_is_unverified():
    """A canonical sentence pasted into draft text without provenance manifest returns UNVERIFIED."""
    draft_text = "At Google, I influenced $8M in new Google Cloud revenue."
    res = validate_canonical_grounding(draft_text)
    assert res.is_grounded is False
    assert res.status in [GroundingStatus.UNVERIFIED, GroundingStatus.NO_CAREER_CLAIMS_DETECTED]
    assert len(res.supported_claims) == 0


def test_failure_b_multiple_occurrences_cannot_be_inferred():
    """Duplicate text occurrences cannot be inferred by text search; explicit bindings required."""
    did = "draft_fail_b_multi"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft_text = f"Intro: {c['rendered_text']} Repeat: {c['rendered_text']}"

    res = validate_canonical_grounding(
        draft_text=draft_text,
        provenance_claims=[{"claim_instance_id": c["claim_instance_id"], "draft_id": did, "text": c["rendered_text"]}],
        draft_id=did
    )
    assert res.is_grounded is False
    assert len(res.supported_claims) == 0


# ===========================================================================
# 3. Failure C Regression: Mandatory Fail-Closed Versions & Digests
# ===========================================================================

@pytest.mark.parametrize("mutated_field,mutated_value,expected_status", [
    ("record_schema_version", 1, ClaimStatus.STALE_PROVENANCE),
    ("record_schema_version", 99, ClaimStatus.STALE_PROVENANCE),
    ("template_version", "1.0.0", ClaimStatus.STALE_PROVENANCE),
    ("template_version", "", ClaimStatus.STALE_PROVENANCE),
    ("template_digest", "", ClaimStatus.STALE_PROVENANCE),
    ("template_digest", "0" * 63, ClaimStatus.STALE_PROVENANCE),
    ("template_digest", "0" * 65, ClaimStatus.STALE_PROVENANCE),
    ("template_digest", "f" * 64, ClaimStatus.STALE_PROVENANCE),
    ("ledger_version", "2.0.0", ClaimStatus.STALE_PROVENANCE),
    ("ledger_version", "", ClaimStatus.STALE_PROVENANCE),
    ("ledger_digest", "", ClaimStatus.STALE_PROVENANCE),
    ("ledger_digest", "0" * 64, ClaimStatus.STALE_PROVENANCE),
    ("fact_version", "2.0.0", ClaimStatus.STALE_PROVENANCE),
    ("fact_digest", "", ClaimStatus.STALE_PROVENANCE),
    ("fact_digest", "0" * 64, ClaimStatus.STALE_PROVENANCE),
    ("exact_rendered_hash", "", ClaimStatus.STALE_PROVENANCE),
    ("exact_rendered_hash", "0" * 64, ClaimStatus.STALE_PROVENANCE),
    ("exact_rendered_text", "Mutated claim text.", ClaimStatus.STALE_PROVENANCE),
])
def test_failure_c_integrity_fields_fail_closed(mutated_field, mutated_value, expected_status):
    """Mutating, blanking, or omitting any required version, digest, or text hash fails closed."""
    did = f"draft_fail_c_{mutated_field}"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    rec = PROVENANCE_STORE.get_claim_instance(c["claim_instance_id"])

    # Mutate stored record in-memory for verification testing
    rec_tampered = rec.model_copy(update={mutated_field: mutated_value})
    try:
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec_tampered

        draft_text = f"Intro. {c['rendered_text']} Outro."
        start = draft_text.index(c["rendered_text"])
        end = start + len(c["rendered_text"])

        binding = ClaimBlockBinding(
            claim_instance_id=c["claim_instance_id"],
            draft_id=did,
            block_id="block_0",
            start_offset=start,
            end_offset=end,
            submitted_block_text=c["rendered_text"]
        )

        is_valid, status, reason, supp = verify_provenance_claim_binding(binding, draft_text)
        assert is_valid is False
        assert status == expected_status
        assert supp is None
    finally:
        # Restore clean record in store so persistent store is not polluted
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec


def test_failure_c_employment_record_digest_mutated_fails_closed():
    """Mutating employment_record_digest on employment claim fails closed."""
    did = "draft_fail_c_emp_digest"
    c = generate_canonical_claim("FACT_EMPLOYMENT_IBM_WATSON", template_id="TPL_EMP_IBM_WATSON", draft_id=did)
    rec = PROVENANCE_STORE.get_claim_instance(c["claim_instance_id"])

    rec_tampered = rec.model_copy(update={"employment_record_digest": "0" * 64})
    try:
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec_tampered

        draft_text = f"Intro: {c['rendered_text']}"
        start = draft_text.index(c["rendered_text"])
        end = start + len(c["rendered_text"])

        binding = ClaimBlockBinding(
            claim_instance_id=c["claim_instance_id"],
            draft_id=did,
            block_id="block_0",
            start_offset=start,
            end_offset=end,
            submitted_block_text=c["rendered_text"]
        )

        is_valid, status, reason, supp = verify_provenance_claim_binding(binding, draft_text)
        assert is_valid is False
        assert status == ClaimStatus.STALE_PROVENANCE
    finally:
        PROVENANCE_STORE._records[rec.claim_instance_id] = rec


def test_failure_c_persisted_record_missing_security_fields_fails_load(tmp_path):
    """Corrupt or legacy persisted records missing mandatory fields fail closed without defaults."""
    store_file = tmp_path / "legacy_store.json"
    legacy_data = {
        "claim_legacy_1": {
            "claim_instance_id": "claim_legacy_1",
            "draft_id": "draft_legacy",
            "canonical_fact_id": "FACT_GOOGLE_REVENUE",
            "template_id": "TPL_GOOGLE_REVENUE_CONCISE",
            # Missing template_digest, ledger_digest, fact_digest, exact_rendered_hash, record_schema_version
            "exact_rendered_text": "At Google, I influenced $8M in new Google Cloud revenue."
        }
    }
    with open(store_file, "w") as f:
        json.dump(legacy_data, f)

    store = ProvenanceStore(storage_path=store_file)
    assert store._is_available is False
    assert "missing mandatory security field" in store._load_error.lower()


# ===========================================================================
# 4. Failure D Regression: Complete Web-Cockpit Lifecycle Tests
# ===========================================================================

def test_failure_d_web_cockpit_generate_reply_returns_structured_provenance():
    """POST /api/emails/{id}/generate-reply returns structured draft and stores metadata in cache."""
    client = TestClient(app)
    headers = {"X-Aura-Session-Token": get_local_session_token()}

    # Setup cached test email
    test_msg = EmailMessage(
        id="email_web_cockpit_1",
        subject="Executive Architecture Role",
        sender_name="Recruiter Jane",
        sender_email="jane@recruiting.com",
        body_text="Hi Brian, are you open to discussing an Enterprise Solutions Architect role?"
    )
    CACHED_EMAILS[test_msg.id] = test_msg

    res = client.post(
        f"/api/emails/{test_msg.id}/generate-reply",
        headers=headers,
        json={"tone": "Professional & Warm", "selected_resume": "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "draft_id" in data and data["draft_id"].startswith("draft_email_")
    assert "claim_bindings" in data
    assert isinstance(data["claim_bindings"], list)
    assert len(data["claim_bindings"]) > 0
    assert data["is_grounded"] is True
    assert data["grounding_status"] == "GROUNDED"

    # Verify server-side cache retention
    cached = CACHED_EMAILS[test_msg.id]
    assert cached.draft_id == data["draft_id"]
    assert len(cached.claim_bindings) == len(data["claim_bindings"])
    assert cached.is_grounded is True
    assert cached.grounding_status == "GROUNDED"


def test_failure_d_web_cockpit_save_draft_with_valid_bindings_retains_grounding():
    """POST /api/emails/{id}/save-draft with valid bindings validates and returns grounded status."""
    client = TestClient(app)
    headers = {"X-Aura-Session-Token": get_local_session_token()}

    test_msg = EmailMessage(
        id="email_web_cockpit_save_valid",
        subject="Role Discussion",
        sender_name="Recruiter",
        sender_email="recruiter@example.com",
        body_text="Reachout"
    )
    CACHED_EMAILS[test_msg.id] = test_msg

    # Generate draft
    gen_res = client.post(
        f"/api/emails/{test_msg.id}/generate-reply",
        headers=headers,
        json={"tone": "Executive & Assertive"}
    )
    gen_data = gen_res.json()

    # Save draft with exact generated text and bindings (mocking provider draft storage)
    with patch("backend.main.provider_manager.save_draft_reply") as mock_save:
        mock_save.return_value = ProviderOperationResult(
            success=True,
            provider="MICROSOFT_GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft staged successfully",
            remote_object_id="draft_cloud_123"
        )
        save_res = client.post(
            f"/api/emails/{test_msg.id}/save-draft",
            headers=headers,
            json={
                "reply_body": gen_data["draft_reply"],
                "draft_id": gen_data["draft_id"],
                "claim_bindings": gen_data["claim_bindings"]
            }
        )
    assert save_res.status_code == 200
    save_data = save_res.json()
    assert save_data["success"] is True
    assert save_data["is_grounded"] is True
    assert save_data["grounding_status"] == "GROUNDED"


def test_failure_d_web_cockpit_save_draft_with_edited_text_fails_closed():
    """POST /api/emails/{id}/save-draft with modified text invalidates grounding (is_grounded = False)."""
    client = TestClient(app)
    headers = {"X-Aura-Session-Token": get_local_session_token()}

    test_msg = EmailMessage(
        id="email_web_cockpit_save_edited",
        subject="Role Discussion",
        sender_name="Recruiter",
        sender_email="recruiter@example.com",
        body_text="Reachout"
    )
    CACHED_EMAILS[test_msg.id] = test_msg

    gen_res = client.post(
        f"/api/emails/{test_msg.id}/generate-reply",
        headers=headers,
        json={"tone": "Executive & Assertive"}
    )
    gen_data = gen_res.json()

    # Save draft with manually edited text
    edited_text = gen_data["draft_reply"] + "\n\nP.S. I also generated $50M at CompanyX."
    with patch("backend.main.provider_manager.save_draft_reply") as mock_save:
        mock_save.return_value = ProviderOperationResult(
            success=True,
            provider="MICROSOFT_GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft staged successfully",
            remote_object_id="draft_cloud_123"
        )
        save_res = client.post(
            f"/api/emails/{test_msg.id}/save-draft",
            headers=headers,
            json={
                "reply_body": edited_text,
                "draft_id": gen_data["draft_id"],
                "claim_bindings": gen_data["claim_bindings"]
            }
        )
    assert save_res.status_code == 200
    save_data = save_res.json()
    assert save_data["success"] is True
    assert save_data["is_grounded"] is False
    assert save_data["grounding_status"] in ["UNVERIFIED", "VALIDATION_FAILED", "MIXED_REVIEW_REQUIRED"]


def test_failure_d_web_cockpit_save_draft_missing_metadata_fails_closed():
    """POST /api/emails/{id}/save-draft without draft_id or claim_bindings fails closed on grounding."""
    client = TestClient(app)
    headers = {"X-Aura-Session-Token": get_local_session_token()}

    test_msg = EmailMessage(
        id="email_web_cockpit_save_nometa",
        subject="Role Discussion",
        sender_name="Recruiter",
        sender_email="recruiter@example.com",
        body_text="Reachout"
    )
    CACHED_EMAILS[test_msg.id] = test_msg

    with patch("backend.main.provider_manager.save_draft_reply") as mock_save:
        mock_save.return_value = ProviderOperationResult(
            success=True,
            provider="MICROSOFT_GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft staged successfully",
            remote_object_id="draft_cloud_123"
        )
        save_res = client.post(
            f"/api/emails/{test_msg.id}/save-draft",
            headers=headers,
            json={"reply_body": "Here is my reply without metadata."}
        )
    assert save_res.status_code == 200
    save_data = save_res.json()
    assert save_data["is_grounded"] is False
    assert save_data["grounding_status"] == "UNVERIFIED"


# ===========================================================================
# 5. Authoritative Manifest & Binding Edge Cases
# ===========================================================================

def test_manifest_missing_required_fields_fails_closed():
    """Manifest binding missing claim_id or offsets fails closed with VALIDATION_FAILED."""
    draft_text = "Some draft text."
    is_valid, status, reason, parsed = validate_claim_manifest(
        draft_text=draft_text,
        claim_bindings=[{"draft_id": "d1", "start_offset": 0, "end_offset": 4, "submitted_block_text": "Some"}]
    )
    assert is_valid is False
    assert status == GroundingStatus.VALIDATION_FAILED


def test_manifest_duplicate_claim_id_fails_closed():
    """Manifest with duplicate claim_instance_id fails closed."""
    did = "draft_dup_cid"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft_text = f"{c['rendered_text']} and {c['rendered_text']}"
    s1 = 0
    e1 = len(c['rendered_text'])
    s2 = draft_text.rfind(c['rendered_text'])
    e2 = s2 + len(c['rendered_text'])

    bindings = [
        {"claim_instance_id": c["claim_instance_id"], "draft_id": did, "block_id": "b1", "start_offset": s1, "end_offset": e1, "submitted_block_text": c["rendered_text"]},
        {"claim_instance_id": c["claim_instance_id"], "draft_id": did, "block_id": "b2", "start_offset": s2, "end_offset": e2, "submitted_block_text": c["rendered_text"]}
    ]
    is_valid, status, reason, _ = validate_claim_manifest(draft_text, bindings, draft_id=did)
    assert is_valid is False
    assert status == GroundingStatus.VALIDATION_FAILED
    assert "Duplicate claim_instance_id" in reason


def test_manifest_duplicate_block_id_fails_closed():
    """Manifest with duplicate block_id fails closed."""
    did = "draft_dup_bid"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", template_id="TPL_CDW_SERVICES_CONCISE", draft_id=did)
    draft_text = f"{c1['rendered_text']} {c2['rendered_text']}"
    s1 = 0
    e1 = len(c1['rendered_text'])
    s2 = draft_text.index(c2['rendered_text'])
    e2 = s2 + len(c2['rendered_text'])

    bindings = [
        {"claim_instance_id": c1["claim_instance_id"], "draft_id": did, "block_id": "block_SAME", "start_offset": s1, "end_offset": e1, "submitted_block_text": c1["rendered_text"]},
        {"claim_instance_id": c2["claim_instance_id"], "draft_id": did, "block_id": "block_SAME", "start_offset": s2, "end_offset": e2, "submitted_block_text": c2["rendered_text"]}
    ]
    is_valid, status, reason, _ = validate_claim_manifest(draft_text, bindings, draft_id=did)
    assert is_valid is False
    assert status == GroundingStatus.VALIDATION_FAILED
    assert "Duplicate block_id" in reason


def test_manifest_overlapping_ranges_fail_closed():
    """Manifest with overlapping offset ranges fails closed."""
    did = "draft_overlap"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", template_id="TPL_CDW_SERVICES_CONCISE", draft_id=did)
    draft_text = f"{c1['rendered_text']} {c2['rendered_text']}"

    bindings = [
        {"claim_instance_id": c1["claim_instance_id"], "draft_id": did, "block_id": "b1", "start_offset": 0, "end_offset": 25, "submitted_block_text": draft_text[0:25]},
        {"claim_instance_id": c2["claim_instance_id"], "draft_id": did, "block_id": "b2", "start_offset": 20, "end_offset": 45, "submitted_block_text": draft_text[20:45]}
    ]
    is_valid, status, reason, _ = validate_claim_manifest(draft_text, bindings, draft_id=did)
    assert is_valid is False
    assert status == GroundingStatus.VALIDATION_FAILED
    assert "Overlapping or nested" in reason


def test_manifest_slice_mismatch_fails_closed():
    """Draft slice not matching submitted_block_text fails closed."""
    did = "draft_slice_mismatch"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    draft_text = "Some completely different text."

    bindings = [
        {"claim_instance_id": c["claim_instance_id"], "draft_id": did, "block_id": "b1", "start_offset": 0, "end_offset": len(c["rendered_text"]), "submitted_block_text": c["rendered_text"]}
    ]
    is_valid, status, reason, _ = validate_claim_manifest(draft_text, bindings, draft_id=did)
    assert is_valid is False
    assert status == GroundingStatus.VALIDATION_FAILED


def test_mixed_supported_and_unsupported_career_prose_fails_whole_draft_grounded():
    """A valid claim combined with unsupported unbound career prose produces MIXED_REVIEW_REQUIRED and is_grounded = False."""
    did = "draft_mixed_claims"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", template_id="TPL_GOOGLE_REVENUE_CONCISE", draft_id=did)
    unsupported_claim = "I also drove $999M in revenue at FakeCompany."
    draft_text = f"{c['rendered_text']} {unsupported_claim}"

    s1 = 0
    e1 = len(c["rendered_text"])
    bindings = [
        {"claim_instance_id": c["claim_instance_id"], "draft_id": did, "block_id": "b1", "start_offset": s1, "end_offset": e1, "submitted_block_text": c["rendered_text"]}
    ]

    res = validate_canonical_grounding(draft_text, claim_bindings=bindings, draft_id=did)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.MIXED_REVIEW_REQUIRED
    assert len(res.supported_claims) == 1
    assert len(res.unsupported_claims) > 0


def test_empty_manifest_returns_no_career_claims_detected_not_grounded():
    """Empty claim manifest on generic text returns NO_CAREER_CLAIMS_DETECTED with is_grounded = False."""
    draft_text = "Hi Alex, let's schedule time for next Tuesday at 2pm."
    res = validate_canonical_grounding(draft_text, claim_bindings=[])
    assert res.is_grounded is False
    assert res.status == GroundingStatus.NO_CAREER_CLAIMS_DETECTED


# ===========================================================================
# 6. Security Invariants
# ===========================================================================

def test_zero_transmission_invariant_send_strictly_blocked():
    """SEND action is strictly BLOCKED across all contexts and modes."""
    risk = analyze_risk_heuristics("Inbound reachout", "Outbound reply", action="SEND")
    assert risk.severity == RiskSeverity.HIGH_RISK
    assert risk.recommended_action == "BLOCKED"


def test_all_8_canonical_tenures_present_and_exact():
    """All 8 verified canonical employment tenures are present and exact."""
    expected = {
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
    for emp_id, (canon_name, sy, sm, ey, em) in expected.items():
        assert emp_id in CANONICAL_EMPLOYMENT_RECORDS
        rec = CANONICAL_EMPLOYMENT_RECORDS[emp_id]
        assert rec.employer_canonical == canon_name
        assert rec.start_year == sy and rec.start_month == sm
        assert rec.end_year == ey and rec.end_month == em


def test_ibm_watson_association_with_ibm():
    """IBM Watson template and fact are associated with employment_record_id = 'ibm'."""
    tpl = CANONICAL_CLAIM_TEMPLATES["TPL_EMP_IBM_WATSON"]
    assert tpl.employment_record_id == "ibm"
    assert tpl.template_version == "2.0.0"

    did = "draft_ibm_watson_check"
    c = generate_canonical_claim("FACT_EMPLOYMENT_IBM_WATSON", "TPL_EMP_IBM_WATSON", draft_id=did)
    assert c["employment_record_id"] == "ibm"

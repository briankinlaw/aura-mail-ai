"""
Phase 5.5.3 Closure Remediation Tests for Aura Mail AI.
Covers:
- Step 2 / 12: Failures A, B, C, D, E reproduction and fix verification
- Step 3 / 12: Strict 6-field canonical binding schema & mutation matrix
- Step 4 / 12: Fail-closed manifest validation (duplicates, overlaps, slices, draft mismatch)
- Step 5 / 12: Restricted verify_provenance_claim wrapper delegation
- Step 6 / 13: Cached draft identity & exact text hash enforcement
- Step 7 / 13: Cross-email provenance isolation & save/risk replay rejection
- Step 8 / 13: Persistent server-side invalidation after edits & divergence detection
- Step 9 / 13: Post-edit replay rejection
- Step 10 / 13: Web-cockpit bound risk check lifecycle
- Step 14 / 15: Preservation of Phase 5.5.2 fixes and all inherited security invariants
"""

import pytest
import time
import json
import uuid
from typing import Dict, Any, List
from fastapi.testclient import TestClient

from backend.canonical_grounding import (
    validate_claim_manifest,
    validate_canonical_grounding,
    verify_provenance_claim,
    verify_provenance_claim_binding,
    generate_canonical_claim,
    ClaimBlockBinding,
    ProvenanceStore,
    PROVENANCE_STORE,
    GroundingStatus,
    ClaimStatus,
    compute_sha256,
    get_active_ledger_digest,
    CANONICAL_EMPLOYMENT_RECORDS
)
from backend.models import EmailMessage, UserProfile, ClassificationResult, EmailCategory
from backend.main import app, CACHED_EMAILS
from backend.radar.risk_evaluator import (
    evaluate_second_opinion_risk,
    RiskSeverity,
    RiskCategory
)
from backend.auth import get_local_session_token

client = TestClient(app)
AUTH_HEADER = {"Authorization": f"Bearer {get_local_session_token()}"}


# ===========================================================================
# 1. Failure A & B Reproduction & Direct 6-Field Matrix (Step 2, 3, 4, 5, 12)
# ===========================================================================

def test_failure_a_missing_binding_identity_fails_manifest_validation():
    """
    Failure A: Incomplete binding missing draft_id and block_id must NOT become grounded.
    Must return VALIDATION_FAILED and is_grounded = False.
    """
    did = "draft_fail_a_001"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    claim_text = c["rendered_text"]
    claim_id = c["claim_instance_id"]

    # Incomplete manifest (missing draft_id and block_id)
    incomplete_binding = {
        "claim_instance_id": claim_id,
        "start_offset": 0,
        "end_offset": len(claim_text),
        "submitted_block_text": claim_text,
        # draft_id intentionally absent
        # block_id intentionally absent
    }

    result = validate_canonical_grounding(
        draft_text=claim_text,
        claim_bindings=[incomplete_binding],
        draft_id=did
    )
    assert result.is_grounded is False
    assert result.status == GroundingStatus.VALIDATION_FAILED
    assert "missing mandatory canonical field" in result.validation_summary.lower()


def test_failure_b_wrapper_without_block_id_fails_validation():
    """
    Failure B: Calling verify_provenance_claim without block_id must return
    is_valid = False and status = VALIDATION_FAILED (synthesis of block_0 disabled).
    """
    did = "draft_fail_b_001"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    claim_text = c["rendered_text"]
    claim_id = c["claim_instance_id"]

    is_valid, status, reason, supp = verify_provenance_claim(
        claim_instance_id=claim_id,
        submitted_text=claim_text,
        draft_id=did,
        draft_text=claim_text,
        start_offset=0,
        end_offset=len(claim_text),
        # block_id intentionally absent
    )
    assert is_valid is False
    assert status == ClaimStatus.VALIDATION_FAILED
    assert supp is None
    assert "block_id" in reason.lower()


def test_six_field_deletion_matrix():
    """
    Step 12: Beginning with one valid 6-field binding, delete each field individually.
    Each deletion must return VALIDATION_FAILED and is_grounded = False.
    """
    did = "draft_mutation_matrix_01"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    valid_binding = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": 0,
        "end_offset": len(c["rendered_text"]),
        "submitted_block_text": c["rendered_text"]
    }

    # 1. Missing claim_instance_id
    b1 = dict(valid_binding)
    del b1["claim_instance_id"]
    r1 = validate_canonical_grounding(c["rendered_text"], [b1], draft_id=did)
    assert r1.is_grounded is False
    assert r1.status == GroundingStatus.VALIDATION_FAILED

    # 2. Missing draft_id
    b2 = dict(valid_binding)
    del b2["draft_id"]
    r2 = validate_canonical_grounding(c["rendered_text"], [b2], draft_id=did)
    assert r2.is_grounded is False
    assert r2.status == GroundingStatus.VALIDATION_FAILED

    # 3. Missing block_id
    b3 = dict(valid_binding)
    del b3["block_id"]
    r3 = validate_canonical_grounding(c["rendered_text"], [b3], draft_id=did)
    assert r3.is_grounded is False
    assert r3.status == GroundingStatus.VALIDATION_FAILED

    # 4. Missing start_offset
    b4 = dict(valid_binding)
    del b4["start_offset"]
    r4 = validate_canonical_grounding(c["rendered_text"], [b4], draft_id=did)
    assert r4.is_grounded is False
    assert r4.status == GroundingStatus.VALIDATION_FAILED

    # 5. Missing end_offset
    b5 = dict(valid_binding)
    del b5["end_offset"]
    r5 = validate_canonical_grounding(c["rendered_text"], [b5], draft_id=did)
    assert r5.is_grounded is False
    assert r5.status == GroundingStatus.VALIDATION_FAILED

    # 6. Missing submitted_block_text
    b6 = dict(valid_binding)
    del b6["submitted_block_text"]
    r6 = validate_canonical_grounding(c["rendered_text"], [b6], draft_id=did)
    assert r6.is_grounded is False
    assert r6.status == GroundingStatus.VALIDATION_FAILED


@pytest.mark.parametrize("field_name,bad_val", [
    ("claim_instance_id", None),
    ("claim_instance_id", ""),
    ("claim_instance_id", "   "),
    ("claim_instance_id", 12345),
    ("draft_id", None),
    ("draft_id", ""),
    ("draft_id", "   "),
    ("draft_id", ["wrong_type"]),
    ("block_id", None),
    ("block_id", ""),
    ("block_id", "   "),
    ("block_id", 999),
    ("submitted_block_text", None),
    ("submitted_block_text", ""),
    ("submitted_block_text", "   "),
    ("submitted_block_text", {"obj": 1}),
    ("start_offset", None),
    ("start_offset", "0"),
    ("start_offset", True),   # boolean must be rejected
    ("start_offset", False),  # boolean must be rejected
    ("start_offset", -1),
    ("end_offset", None),
    ("end_offset", "10"),
    ("end_offset", True),     # boolean must be rejected
    ("end_offset", False),    # boolean must be rejected
])
def test_six_field_type_and_value_mutations(field_name, bad_val):
    """
    Test each field as None, empty, whitespace, wrong type, or boolean for offsets.
    All must fail closed with VALIDATION_FAILED.
    """
    did = "draft_mutations_02"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    b = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": 0,
        "end_offset": len(c["rendered_text"]),
        "submitted_block_text": c["rendered_text"]
    }
    b[field_name] = bad_val

    r = validate_canonical_grounding(c["rendered_text"], [b], draft_id=did)
    assert r.is_grounded is False
    assert r.status == GroundingStatus.VALIDATION_FAILED


@pytest.mark.parametrize("alias_key,alias_val,canonical_target", [
    ("claim_id", "claim_inst_xyz", "claim_instance_id"),
    ("start", 0, "start_offset"),
    ("end", 20, "end_offset"),
    ("text", "Some claim", "submitted_block_text"),
    ("rendered_text", "Some claim", "submitted_block_text"),
])
def test_legacy_aliases_replacing_canonical_fields_are_rejected(alias_key, alias_val, canonical_target):
    """
    Step 3: Reject claim_id, start, end, text, rendered_text when supplied instead
    of canonical fields. None may produce authoritative grounding.
    """
    did = "draft_alias_test"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    b = {
        "claim_instance_id": c["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": 0,
        "end_offset": len(c["rendered_text"]),
        "submitted_block_text": c["rendered_text"]
    }
    # Remove canonical field and supply legacy alias instead
    del b[canonical_target]
    b[alias_key] = alias_val

    r = validate_canonical_grounding(c["rendered_text"], [b], draft_id=did)
    assert r.is_grounded is False
    assert r.status == GroundingStatus.VALIDATION_FAILED


def test_wrapper_fails_closed_on_any_missing_argument():
    """
    Step 5: verify_provenance_claim must require all 7 arguments and fail closed if any is missing.
    """
    did = "draft_wrapper_all_args"
    c = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    text = c["rendered_text"]
    cid = c["claim_instance_id"]

    # All 7 arguments present -> succeeds
    is_valid, status, reason, supp = verify_provenance_claim(
        claim_instance_id=cid,
        submitted_text=text,
        draft_id=did,
        draft_text=text,
        start_offset=0,
        end_offset=len(text),
        block_id="block_0"
    )
    assert is_valid is True
    assert status == ClaimStatus.SUPPORTED
    assert supp is not None

    # Missing claim_instance_id
    iv, st, _, _ = verify_provenance_claim(claim_instance_id=None, submitted_text=text, draft_id=did, draft_text=text, start_offset=0, end_offset=len(text), block_id="block_0")
    assert iv is False and st == ClaimStatus.VALIDATION_FAILED

    # Missing draft_id
    iv, st, _, _ = verify_provenance_claim(claim_instance_id=cid, submitted_text=text, draft_id=None, draft_text=text, start_offset=0, end_offset=len(text), block_id="block_0")
    assert iv is False and st == ClaimStatus.VALIDATION_FAILED

    # Missing block_id
    iv, st, _, _ = verify_provenance_claim(claim_instance_id=cid, submitted_text=text, draft_id=did, draft_text=text, start_offset=0, end_offset=len(text), block_id=None)
    assert iv is False and st == ClaimStatus.VALIDATION_FAILED

    # Missing draft_text
    iv, st, _, _ = verify_provenance_claim(claim_instance_id=cid, submitted_text=text, draft_id=did, draft_text=None, start_offset=0, end_offset=len(text), block_id="block_0")
    assert iv is False and st == ClaimStatus.VALIDATION_FAILED

    # Missing start_offset
    iv, st, _, _ = verify_provenance_claim(claim_instance_id=cid, submitted_text=text, draft_id=did, draft_text=text, start_offset=None, end_offset=len(text), block_id="block_0")
    assert iv is False and st == ClaimStatus.VALIDATION_FAILED

    # Missing end_offset
    iv, st, _, _ = verify_provenance_claim(claim_instance_id=cid, submitted_text=text, draft_id=did, draft_text=text, start_offset=0, end_offset=None, block_id="block_0")
    assert iv is False and st == ClaimStatus.VALIDATION_FAILED

    # Missing submitted_text
    iv, st, _, _ = verify_provenance_claim(claim_instance_id=cid, submitted_text=None, draft_id=did, draft_text=text, start_offset=0, end_offset=len(text), block_id="block_0")
    assert iv is False and st == ClaimStatus.VALIDATION_FAILED


def test_manifest_validation_rejects_duplicates_overlaps_and_mismatched_slices():
    """
    Step 4 / 12: Manifest validator rejects duplicate claim IDs, duplicate block IDs,
    overlapping/nested ranges, out of bounds, and slice mismatches.
    """
    did = "draft_manifest_rules"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", draft_id=did)
    t1 = c1["rendered_text"]
    t2 = c2["rendered_text"]
    full_text = f"{t1} Additionally, {t2}"

    b1 = {
        "claim_instance_id": c1["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_0",
        "start_offset": 0,
        "end_offset": len(t1),
        "submitted_block_text": t1
    }
    b2_start = len(t1) + len(" Additionally, ")
    b2 = {
        "claim_instance_id": c2["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_1",
        "start_offset": b2_start,
        "end_offset": b2_start + len(t2),
        "submitted_block_text": t2
    }

    # Valid manifest
    res = validate_canonical_grounding(full_text, [b1, b2], draft_id=did)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED

    # Duplicate claim_instance_id
    b_dup_cid = dict(b2, claim_instance_id=c1["claim_instance_id"])
    r_dup_cid = validate_canonical_grounding(full_text, [b1, b_dup_cid], draft_id=did)
    assert r_dup_cid.is_grounded is False
    assert r_dup_cid.status == GroundingStatus.VALIDATION_FAILED

    # Duplicate block_id
    b_dup_bid = dict(b2, block_id="block_0")
    r_dup_bid = validate_canonical_grounding(full_text, [b1, b_dup_bid], draft_id=did)
    assert r_dup_bid.is_grounded is False
    assert r_dup_bid.status == GroundingStatus.VALIDATION_FAILED

    # Overlapping ranges
    b_overlap = dict(b2, start_offset=len(t1) - 5)
    r_overlap = validate_canonical_grounding(full_text, [b1, b_overlap], draft_id=did)
    assert r_overlap.is_grounded is False
    assert r_overlap.status == GroundingStatus.VALIDATION_FAILED

    # Nested ranges
    b_nested = {
        "claim_instance_id": c2["claim_instance_id"],
        "draft_id": did,
        "block_id": "block_1",
        "start_offset": 2,
        "end_offset": len(t1) - 2,
        "submitted_block_text": full_text[2:len(t1)-2]
    }
    r_nested = validate_canonical_grounding(full_text, [b1, b_nested], draft_id=did)
    assert r_nested.is_grounded is False
    assert r_nested.status == GroundingStatus.VALIDATION_FAILED

    # Mismatched slice
    b_slice_mismatch = dict(b1, submitted_block_text="Wrong slice text")
    r_slice_mismatch = validate_canonical_grounding(full_text, [b_slice_mismatch, b2], draft_id=did)
    assert r_slice_mismatch.is_grounded is False
    assert r_slice_mismatch.status == GroundingStatus.VALIDATION_FAILED


# ===========================================================================
# 2. Cross-Email Isolation & Replay Rejection Tests (Step 6, 7, 9, 13)
# ===========================================================================

def setup_two_cached_emails():
    """Helper to populate CACHED_EMAILS with Email A and Email B."""
    msg_a = EmailMessage(
        id="email_a_123",
        subject="Google Cloud Lead Role",
        sender_name="Recruiter Alice",
        sender_email="alice@techrecruit.com",
        body_text="Hi Brian, are you open to a Google Cloud advisory opportunity?",
        classification=ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            is_resume_request=True,
            reasoning="Recruiter inquiry"
        )
    )
    msg_b = EmailMessage(
        id="email_b_456",
        subject="CDW Solutions Architect Position",
        sender_name="Recruiter Bob",
        sender_email="bob@consultinghire.com",
        body_text="Hi Brian, we have a CDW solutions architect opening.",
        classification=ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            is_resume_request=True,
            reasoning="Recruiter inquiry"
        )
    )
    CACHED_EMAILS["email_a_123"] = msg_a
    CACHED_EMAILS["email_b_456"] = msg_b
    return msg_a, msg_b


def test_failure_c_cross_email_provenance_save_replay_rejected():
    """
    Failure C: Generate grounded draft for Email A, then submit Email A's draft_id,
    bindings, and text to Email B's save-draft endpoint.
    Must reject with is_grounded = False and NOT install Email A's authority into Email B.
    """
    setup_two_cached_emails()

    # Step 1: Generate grounded draft for Email A
    res_a = client.post(
        "/api/emails/email_a_123/generate-reply",
        headers=AUTH_HEADER,
        json={"tone": "Professional & Warm"}
    )
    assert res_a.status_code == 200
    data_a = res_a.json()
    draft_id_a = data_a["draft_id"]
    draft_text_a = data_a["draft_reply"]
    bindings_a = data_a["claim_bindings"]
    assert data_a["is_grounded"] is True

    # Step 2: Submit Email A's provenance to Email B's save-draft endpoint
    res_b = client.post(
        "/api/emails/email_b_456/save-draft",
        headers=AUTH_HEADER,
        json={
            "draft_id": draft_id_a,
            "claim_bindings": bindings_a,
            "reply_body": draft_text_a
        }
    )
    assert res_b.status_code == 200
    data_b = res_b.json()

    # Required corrected result:
    assert data_b["is_grounded"] is False
    assert data_b["grounding_status"] in ["VALIDATION_FAILED", "UNVERIFIED"]

    # Confirm Email B did NOT acquire draft_A authority
    email_b = CACHED_EMAILS["email_b_456"]
    assert email_b.draft_id is None
    assert email_b.is_grounded is False
    assert email_b.claim_bindings == []


def test_failure_c_cross_email_risk_check_replay_rejected():
    """
    Submitting Email A's draft_id and bindings to Email B's risk-check endpoint
    must be detected as divergence and evaluated as ungrounded text.
    """
    setup_two_cached_emails()

    # Generate draft for Email A
    res_a = client.post(
        "/api/emails/email_a_123/generate-reply",
        headers=AUTH_HEADER,
        json={"tone": "Professional & Warm"}
    )
    data_a = res_a.json()

    # Submit to Email B risk check
    res_b_risk = client.post(
        "/api/emails/email_b_456/risk-check",
        headers=AUTH_HEADER,
        json={
            "draft_id": data_a["draft_id"],
            "draft_text": data_a["draft_reply"],
            "claim_bindings": data_a["claim_bindings"]
        }
    )
    assert res_b_risk.status_code == 200
    data_risk_b = res_b_risk.json()

    assert data_risk_b["status"] == "DIVERGENCE_DETECTED"
    assert data_risk_b["is_grounded"] is False
    assert data_risk_b["risk_is_current"] is False


def test_two_emails_with_identical_text_remain_isolated():
    """
    Two emails generated with identical text get distinct draft IDs.
    Swapping draft IDs fails validation.
    """
    setup_two_cached_emails()

    res_a = client.post("/api/emails/email_a_123/generate-reply", headers=AUTH_HEADER, json={"tone": "Professional & Warm"})
    res_b = client.post("/api/emails/email_b_456/generate-reply", headers=AUTH_HEADER, json={"tone": "Professional & Warm"})
    data_a = res_a.json()
    data_b = res_b.json()

    assert data_a["draft_id"] != data_b["draft_id"]

    # Submitting draft_id_b to email A fails validation
    res_save_mismatch = client.post(
        "/api/emails/email_a_123/save-draft",
        headers=AUTH_HEADER,
        json={
            "draft_id": data_b["draft_id"],
            "reply_body": data_a["draft_reply"],
            "claim_bindings": data_a["claim_bindings"]
        }
    )
    assert res_save_mismatch.json()["is_grounded"] is False


# ===========================================================================
# 3. Server-Side Invalidation & Post-Edit Replay Rejection (Step 8, 9, 13)
# ===========================================================================

def test_failure_d_post_edit_replay_rejected():
    """
    Failure D: Generate a valid grounded draft, edit/invalidate it,
    then resubmit original text, original draft_id, and original bindings.
    Must reject with INVALIDATED / STALE_PROVENANCE and is_grounded = False.
    """
    setup_two_cached_emails()

    # Step 1: Generate valid grounded draft
    res_gen = client.post(
        "/api/emails/email_a_123/generate-reply",
        headers=AUTH_HEADER,
        json={"tone": "Professional & Warm"}
    )
    data_gen = res_gen.json()
    orig_draft_id = data_gen["draft_id"]
    orig_text = data_gen["draft_reply"]
    orig_bindings = data_gen["claim_bindings"]
    orig_claim_id = orig_bindings[0]["claim_instance_id"]
    assert data_gen["is_grounded"] is True

    # Step 2: Invalidate the draft via edit endpoint
    res_inval = client.post(
        "/api/emails/email_a_123/invalidate-draft",
        headers=AUTH_HEADER,
        json={"draft_id": orig_draft_id}
    )
    assert res_inval.status_code == 200
    assert res_inval.json()["status"] == "INVALIDATED"

    # Step 3: Verify server-side provenance store record is marked is_invalidated=True
    rec = PROVENANCE_STORE.get_claim_instance(orig_claim_id)
    assert rec.is_invalidated is True

    # Step 4: Resubmit original text, original draft ID, and original bindings to save-draft
    res_resubmit = client.post(
        "/api/emails/email_a_123/save-draft",
        headers=AUTH_HEADER,
        json={
            "draft_id": orig_draft_id,
            "reply_body": orig_text,
            "claim_bindings": orig_bindings
        }
    )
    data_resubmit = res_resubmit.json()
    assert data_resubmit["is_grounded"] is False
    assert data_resubmit["grounding_status"] in ["VALIDATION_FAILED", "UNVERIFIED", "INVALIDATED"]

    # Step 5: Direct verification of the invalidated claim must return INVALIDATED
    is_valid, status, reason, _ = verify_provenance_claim(
        claim_instance_id=orig_claim_id,
        submitted_text=orig_bindings[0]["submitted_block_text"],
        draft_id=orig_draft_id,
        draft_text=orig_text,
        start_offset=orig_bindings[0]["start_offset"],
        end_offset=orig_bindings[0]["end_offset"],
        block_id=orig_bindings[0]["block_id"]
    )
    assert is_valid is False
    assert status == ClaimStatus.INVALIDATED


def test_backend_divergence_detection_invalidates_claims_on_text_tamper():
    """
    Step 8 / 13: If request text hash diverges from cached draft hash during save,
    claims are persistently invalidated and grounding is cleared.
    """
    setup_two_cached_emails()

    res_gen = client.post("/api/emails/email_a_123/generate-reply", headers=AUTH_HEADER, json={"tone": "Professional & Warm"})
    data_gen = res_gen.json()
    orig_draft_id = data_gen["draft_id"]
    orig_claim_id = data_gen["claim_bindings"][0]["claim_instance_id"]

    # Save with modified text
    tampered_text = data_gen["draft_reply"] + " [I added this unprovenanced sentence.]"
    res_save = client.post(
        "/api/emails/email_a_123/save-draft",
        headers=AUTH_HEADER,
        json={
            "draft_id": orig_draft_id,
            "reply_body": tampered_text,
            "claim_bindings": data_gen["claim_bindings"]
        }
    )
    assert res_save.json()["is_grounded"] is False

    # Stored claim record is now invalidated
    rec = PROVENANCE_STORE.get_claim_instance(orig_claim_id)
    assert rec.is_invalidated is True


def test_new_generation_creates_fresh_groundable_claims():
    """
    Step 9: After invalidation, only a newly generated draft with fresh claim instances
    can regain authoritative grounding.
    """
    setup_two_cached_emails()

    res1 = client.post("/api/emails/email_a_123/generate-reply", headers=AUTH_HEADER, json={"tone": "Professional & Warm"})
    d1 = res1.json()

    # Invalidate
    client.post("/api/emails/email_a_123/invalidate-draft", headers=AUTH_HEADER, json={"draft_id": d1["draft_id"]})

    # Regenerate fresh draft
    res2 = client.post("/api/emails/email_a_123/generate-reply", headers=AUTH_HEADER, json={"tone": "Executive & Assertive"})
    d2 = res2.json()

    assert d2["draft_id"] != d1["draft_id"]
    assert d2["is_grounded"] is True
    assert d2["grounding_status"] == "GROUNDED"

    # New claim verifies as SUPPORTED
    new_cid = d2["claim_bindings"][0]["claim_instance_id"]
    new_rec = PROVENANCE_STORE.get_claim_instance(new_cid)
    assert new_rec.is_invalidated is False


# ===========================================================================
# 4. Web Cockpit Risk Lifecycle Tests (Step 10, 11, 13)
# ===========================================================================

def test_failure_e_web_cockpit_bound_risk_lifecycle():
    """
    Failure E & Step 10: Prove web cockpit has risk check bound to email_id, draft_id,
    and text hash, and that subsequent edits invalidate risk authority.
    """
    setup_two_cached_emails()

    # 1. Generate draft
    res_gen = client.post("/api/emails/email_a_123/generate-reply", headers=AUTH_HEADER, json={"tone": "Professional & Warm"})
    d = res_gen.json()

    # 2. Risk check with exact current draft identity
    res_risk = client.post(
        "/api/emails/email_a_123/risk-check",
        headers=AUTH_HEADER,
        json={
            "draft_id": d["draft_id"],
            "draft_text": d["draft_reply"],
            "claim_bindings": d["claim_bindings"]
        }
    )
    assert res_risk.status_code == 200
    risk_data = res_risk.json()
    assert risk_data["status"] == "SUCCESS"
    assert risk_data["is_grounded"] is True
    assert risk_data["risk_is_current"] is True
    assert risk_data["risk"]["severity"] in ["SAFE", "CAUTION"]

    # 3. Simulate edit: invalidate draft
    client.post("/api/emails/email_a_123/invalidate-draft", headers=AUTH_HEADER, json={"draft_id": d["draft_id"]})

    # 4. Risk check on invalidated draft now returns DIVERGENCE_DETECTED and is_grounded = False
    res_risk_after = client.post(
        "/api/emails/email_a_123/risk-check",
        headers=AUTH_HEADER,
        json={
            "draft_id": d["draft_id"],
            "draft_text": d["draft_reply"],
            "claim_bindings": d["claim_bindings"]
        }
    )
    assert res_risk_after.status_code == 200
    risk_after_data = res_risk_after.json()
    assert risk_after_data["status"] == "DIVERGENCE_DETECTED"
    assert risk_after_data["is_grounded"] is False
    assert risk_after_data["risk_is_current"] is False


def test_claim_free_content_never_becomes_verified_safe_grounding():
    """
    Step 10: Claim-free content produces NO_CAREER_CLAIMS_DETECTED and is_grounded = False,
    never GROUNDED or VERIFIED.
    """
    res = validate_canonical_grounding(
        draft_text="Thank you for reaching out. I would be happy to discuss further next week.",
        claim_bindings=[],
        draft_id="draft_no_claims"
    )
    assert res.is_grounded is False
    assert res.status == GroundingStatus.NO_CAREER_CLAIMS_DETECTED


# ===========================================================================
# 5. Security Invariant & Regression Tests (Step 14, 15)
# ===========================================================================

def test_zero_transmission_invariant_send_reply_remains_blocked():
    """
    Step 15: /api/emails/{id}/send-reply remains strictly blocked with 403 SEND_FORBIDDEN.
    """
    setup_two_cached_emails()
    res = client.post("/api/emails/email_a_123/send-reply", headers=AUTH_HEADER, json={"reply_body": "test"})
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_canonical_employment_ledger_and_ibm_watson_intact():
    """
    Step 14: All 8 canonical tenures and IBM Watson mapping remain intact.
    """
    assert len(CANONICAL_EMPLOYMENT_RECORDS) == 8
    assert "ibm" in CANONICAL_EMPLOYMENT_RECORDS
    assert CANONICAL_EMPLOYMENT_RECORDS["ibm"].employer_canonical == "IBM"
    assert CANONICAL_EMPLOYMENT_RECORDS["google"].employer_canonical == "Google"
    assert CANONICAL_EMPLOYMENT_RECORDS["cdw"].employer_canonical == "CDW"


def test_auth_and_localhost_boundary_intact():
    """
    Step 15: Privileged endpoints reject unauthenticated requests.
    """
    res = client.post("/api/canonical/claims/verify", json={})
    assert res.status_code in [401, 403]

    res_save = client.post("/api/emails/email_a_123/save-draft", json={})
    assert res_save.status_code in [401, 403]

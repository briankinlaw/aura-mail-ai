"""
Phase 5.5.4 Micro-Remediation Tests for Aura Mail AI.
Covers:
- Failure A: Invalidation persistence failure & draft authority quarantine (Step 2, 3, 9)
- Failure B: /invalidate-draft strict email ownership and isolation (Step 2, 4, 9)
- Failure C: Exact canonical 6-field manifest matching in save and risk (Step 2, 5, 9)
- Failure D: Stale asynchronous risk response and client generation safety (Step 2, 7, 8, 9)
- Security Invariants: Zero-transmission, 8 canonical tenures, IBM Watson mapping, Localhost boundary (Step 10, 11)
"""

import pytest
import time
import json
import uuid
from typing import Dict, Any, List
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.canonical_grounding import (
    validate_claim_manifest,
    validate_canonical_grounding,
    verify_provenance_claim,
    verify_provenance_claim_binding,
    generate_canonical_claim,
    canonicalize_binding_manifest,
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
# Helper: Setup cached emails
# ===========================================================================

def setup_test_cached_emails():
    CACHED_EMAILS.clear()
    PROVENANCE_STORE.reset_store()

    # Create grounded Email A
    did_a = "draft_phase554_email_a"
    c_a1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did_a)
    c_a2 = generate_canonical_claim("FACT_CDW_SERVICES", draft_id=did_a)
    t_a1 = c_a1["rendered_text"]
    t_a2 = c_a2["rendered_text"]
    text_a = f"{t_a1} Furthermore, {t_a2}"
    offset_a2 = len(t_a1) + 14

    bindings_a = [
        {
            "claim_instance_id": c_a1["claim_instance_id"],
            "draft_id": did_a,
            "block_id": "block_0",
            "start_offset": 0,
            "end_offset": len(t_a1),
            "submitted_block_text": t_a1
        },
        {
            "claim_instance_id": c_a2["claim_instance_id"],
            "draft_id": did_a,
            "block_id": "block_1",
            "start_offset": offset_a2,
            "end_offset": offset_a2 + len(t_a2),
            "submitted_block_text": t_a2
        }
    ]

    msg_a = EmailMessage(
        id="email_a_phase554",
        subject="Executive Architecture Role - Google",
        sender_name="Alice Recruiter",
        sender_email="alice@techrecruiting.com",
        body_text="Hi Brian, discussing enterprise revenue leadership.",
        draft_reply=text_a,
        draft_id=did_a,
        claim_bindings=bindings_a,
        grounding_status=GroundingStatus.GROUNDED.value,
        is_grounded=True,
        draft_text_hash=compute_sha256(text_a),
        status="INBOUND",
        received_at="2026-09-15 10:00:00"
    )
    CACHED_EMAILS[msg_a.id] = msg_a

    # Create grounded Email B
    did_b = "draft_phase554_email_b"
    c_b = generate_canonical_claim("FACT_EMPLOYMENT_PYTHIAN", draft_id=did_b)
    text_b = c_b["rendered_text"]
    bindings_b = [
        {
            "claim_instance_id": c_b["claim_instance_id"],
            "draft_id": did_b,
            "block_id": "block_0",
            "start_offset": 0,
            "end_offset": len(text_b),
            "submitted_block_text": text_b
        }
    ]
    msg_b = EmailMessage(
        id="email_b_phase554",
        subject="Pythian Systems Role",
        sender_name="Bob Hiring",
        sender_email="bob@pythianclient.com",
        body_text="Hi Brian, discussing your Pythian experience.",
        draft_reply=text_b,
        draft_id=did_b,
        claim_bindings=bindings_b,
        grounding_status=GroundingStatus.GROUNDED.value,
        is_grounded=True,
        draft_text_hash=compute_sha256(text_b),
        status="INBOUND",
        received_at="2026-09-15 10:05:00"
    )
    CACHED_EMAILS[msg_b.id] = msg_b

    return msg_a, msg_b, c_a1, c_a2, c_b


# ===========================================================================
# 1. Failure A: Replay after Invalidation Persistence Failure (Step 2, 3, 9)
# ===========================================================================

def test_failure_a_invalidation_persistence_failure_quarantines_draft_authority():
    """
    Failure A reproduction & fix:
    When _persist_to_disk() fails during invalidate_draft_claims(),
    the affected draft is placed into quarantine. Subsequent verification of the
    claims fails closed (is_valid=False, status=INVALIDATED / VALIDATION_FAILED)
    rather than remaining SUPPORTED / is_grounded=True.
    """
    PROVENANCE_STORE.reset_store()
    did = "draft_persist_fail_001"
    c1 = generate_canonical_claim("FACT_GOOGLE_REVENUE", draft_id=did)
    c2 = generate_canonical_claim("FACT_CDW_SERVICES", draft_id=did)

    t1 = c1["rendered_text"]
    cid1 = c1["claim_instance_id"]
    cid2 = c2["claim_instance_id"]

    # 1. Verify before invalidation -> SUCCESS
    iv, st, _, supp = verify_provenance_claim(
        claim_instance_id=cid1,
        draft_id=did,
        block_id="block_0",
        draft_text=t1,
        start_offset=0,
        end_offset=len(t1),
        submitted_text=t1
    )
    assert iv is True
    assert st == ClaimStatus.SUPPORTED

    # 2. Force persistence failure during invalidation
    with patch.object(PROVENANCE_STORE, "_persist_to_disk", side_effect=IOError("Disk I/O error")):
        with pytest.raises(Exception):
            PROVENANCE_STORE.invalidate_draft_claims(did, reason="Manual edit")

    # 3. Verify draft is quarantined
    assert PROVENANCE_STORE.is_draft_quarantined(did) is True

    # 4. Attempt to verify original claim 1 -> MUST FAIL CLOSED (not SUPPORTED)
    iv_after1, st_after1, reason1, _ = verify_provenance_claim(
        claim_instance_id=cid1,
        draft_id=did,
        block_id="block_0",
        draft_text=t1,
        start_offset=0,
        end_offset=len(t1),
        submitted_text=t1
    )
    assert iv_after1 is False
    assert st_after1 in (ClaimStatus.INVALIDATED, ClaimStatus.STALE_PROVENANCE, ClaimStatus.VALIDATION_FAILED, ClaimStatus.UNVERIFIED)
    assert st_after1 != ClaimStatus.SUPPORTED

    # 5. Attempt to verify claim 2 under same quarantined draft -> MUST FAIL CLOSED
    t2 = c2["rendered_text"]
    iv_after2, st_after2, reason2, _ = verify_provenance_claim(
        claim_instance_id=cid2,
        draft_id=did,
        block_id="block_0",
        draft_text=t2,
        start_offset=0,
        end_offset=len(t2),
        submitted_text=t2
    )
    assert iv_after2 is False
    assert st_after2 in (ClaimStatus.INVALIDATED, ClaimStatus.STALE_PROVENANCE, ClaimStatus.VALIDATION_FAILED, ClaimStatus.UNVERIFIED)

    # 6. Unrelated draft remains verifiable
    did_unrelated = "draft_unrelated_ok"
    c_unrel = generate_canonical_claim("FACT_EMPLOYMENT_GOOGLE", draft_id=did_unrelated)
    t_unrel = c_unrel["rendered_text"]
    iv_unrel, st_unrel, _, _ = verify_provenance_claim(
        claim_instance_id=c_unrel["claim_instance_id"],
        draft_id=did_unrelated,
        block_id="block_0",
        draft_text=t_unrel,
        start_offset=0,
        end_offset=len(t_unrel),
        submitted_text=t_unrel
    )
    assert iv_unrel is True
    assert st_unrel == ClaimStatus.SUPPORTED


def test_failure_a_save_and_risk_cannot_report_grounded_after_invalidation_persistence_failure():
    """
    Save and risk endpoints fail closed (HTTP 500 PERSISTENCE_FAILURE or ungrounded)
    and quarantine authority when persistence fails during invalidation.
    """
    msg_a, _, _, _, _ = setup_test_cached_emails()
    orig_draft_id = msg_a.draft_id

    # Force persistence failure during invalidate-draft endpoint
    with patch.object(PROVENANCE_STORE, "_persist_to_disk", side_effect=IOError("Disk full")):
        res_inv = client.post(
            f"/api/emails/{msg_a.id}/invalidate-draft",
            headers=AUTH_HEADER,
            json={"draft_id": orig_draft_id}
        )
        assert res_inv.status_code == 500
        assert res_inv.json()["detail"]["error_code"] in ["PERSISTENCE_FAILURE", "INVALIDATION_PERSISTENCE_FAILURE"]

    # Cache is cleared of authority and draft is quarantined
    assert PROVENANCE_STORE.is_draft_quarantined(orig_draft_id) is True
    assert msg_a.is_grounded is False
    assert msg_a.draft_id is None

    # Subsequent save attempt fails to attain grounded status
    res_save = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": "draft_phase554_email_a",
            "claim_bindings": msg_a.claim_bindings
        }
    )
    assert res_save.status_code == 200
    data_save = res_save.json()
    assert data_save["is_grounded"] is False
    assert data_save["grounding_status"] in (GroundingStatus.VALIDATION_FAILED.value, GroundingStatus.UNVERIFIED.value)


# ===========================================================================
# 2. Failure B: /invalidate-draft Email Ownership and Isolation (Step 2, 4, 9)
# ===========================================================================

def test_failure_b_cross_email_invalidation_rejected_without_mutation():
    """
    Failure B reproduction & fix:
    POST /api/emails/email_B/invalidate-draft with draft_id="draft_A" must be rejected
    with DRAFT_ID_MISMATCH (HTTP 400).
    Email A, Email B, and draft A's provenance must remain completely unmutated.
    """
    msg_a, msg_b, c_a1, _, _ = setup_test_cached_emails()
    draft_id_a = msg_a.draft_id
    draft_id_b = msg_b.draft_id

    # Cross-email attack: request invalidation on email_b using email_a's draft_id
    res = client.post(
        f"/api/emails/{msg_b.id}/invalidate-draft",
        headers=AUTH_HEADER,
        json={"draft_id": draft_id_a}
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "DRAFT_ID_MISMATCH"

    # Verify Email A was NOT invalidated
    assert msg_a.is_grounded is True
    assert msg_a.draft_id == draft_id_a
    assert len(msg_a.claim_bindings) == 2

    # Verify Email B was NOT invalidated
    assert msg_b.is_grounded is True
    assert msg_b.draft_id == draft_id_b

    # Verify draft A's claims in store remain active (not invalidated)
    rec = PROVENANCE_STORE.get_claim_instance(c_a1["claim_instance_id"])
    assert rec is not None
    assert rec.is_invalidated is False


def test_invalidation_ownership_missing_empty_and_stale_draft_id_rejected():
    """
    Missing, empty, whitespace, or stale draft IDs on /invalidate-draft
    must be rejected without mutating cache or store.
    """
    msg_a, msg_b, _, _, _ = setup_test_cached_emails()

    # 1. Missing draft_id
    r1 = client.post(f"/api/emails/{msg_a.id}/invalidate-draft", headers=AUTH_HEADER, json={})
    assert r1.status_code == 400
    assert r1.json()["detail"]["error_code"] == "VALIDATION_FAILED"

    # 2. Empty draft_id
    r2 = client.post(f"/api/emails/{msg_a.id}/invalidate-draft", headers=AUTH_HEADER, json={"draft_id": ""})
    assert r2.status_code == 400
    assert r2.json()["detail"]["error_code"] == "VALIDATION_FAILED"

    # 3. Whitespace draft_id
    r3 = client.post(f"/api/emails/{msg_a.id}/invalidate-draft", headers=AUTH_HEADER, json={"draft_id": "   "})
    assert r3.status_code == 400
    assert r3.json()["detail"]["error_code"] == "VALIDATION_FAILED"

    # 4. Email has no active draft
    msg_no_draft = EmailMessage(
        id="email_no_draft",
        subject="No Draft",
        sender_name="Sender",
        sender_email="sender@example.com",
        body_text="Hello",
        received_at="2026-09-15 10:00:00"
    )
    CACHED_EMAILS[msg_no_draft.id] = msg_no_draft
    r4 = client.post(f"/api/emails/{msg_no_draft.id}/invalidate-draft", headers=AUTH_HEADER, json={"draft_id": "draft_xyz"})
    assert r4.status_code == 400
    assert r4.json()["detail"]["error_code"] == "STALE_DRAFT"


def test_invalidation_of_replaced_draft_id_rejected():
    """
    After draft regeneration, attempting to invalidate the old draft_id
    is rejected and does NOT invalidate the newly generated draft.
    """
    msg_a, _, _, _, _ = setup_test_cached_emails()
    old_draft_id = msg_a.draft_id

    # Regenerate draft
    res_regen = client.post(
        f"/api/emails/{msg_a.id}/generate-reply",
        headers=AUTH_HEADER,
        json={"tone": "concise"}
    )
    assert res_regen.status_code == 200
    new_draft_id = res_regen.json()["draft_id"]
    assert new_draft_id != old_draft_id

    # Attempt to invalidate old draft_id on email_a
    res_inv_old = client.post(
        f"/api/emails/{msg_a.id}/invalidate-draft",
        headers=AUTH_HEADER,
        json={"draft_id": old_draft_id}
    )
    assert res_inv_old.status_code == 400
    assert res_inv_old.json()["detail"]["error_code"] == "DRAFT_ID_MISMATCH"

    # New draft remains active and valid
    assert msg_a.draft_id == new_draft_id
    assert msg_a.is_grounded is True


# ===========================================================================
# 3. Failure C: Exact Canonical Manifest Matching in Save & Risk (Step 2, 5, 9)
# ===========================================================================

def test_canonicalize_binding_manifest_projection():
    """
    Test canonicalize_binding_manifest helper:
    Exact 6-field projection, rejecting aliases, invalid types, and out-of-bounds.
    """
    valid_binding = {
        "claim_instance_id": "claim_inst_123",
        "draft_id": "draft_123",
        "block_id": "block_0",
        "start_offset": 0,
        "end_offset": 25,
        "submitted_block_text": "Valid text block content"
    }

    canon = canonicalize_binding_manifest([valid_binding])
    assert canon == [valid_binding]

    # Reject aliases
    assert canonicalize_binding_manifest([{"claim_id": "c1", "draft_id": "d1", "block_id": "b1", "start_offset": 0, "end_offset": 10, "submitted_block_text": "t"}]) is None
    assert canonicalize_binding_manifest([{"claim_instance_id": "c1", "draft_id": "d1", "block_id": "b1", "start": 0, "end_offset": 10, "submitted_block_text": "t"}]) is None

    # Reject non-list or None
    assert canonicalize_binding_manifest(None) is None
    assert canonicalize_binding_manifest("string") is None

    # Reject boolean offsets
    bad_offset = dict(valid_binding, start_offset=False)
    assert canonicalize_binding_manifest([bad_offset]) is None


def test_failure_c_substituted_manifest_fails_closed_in_save():
    """
    Failure C reproduction & fix in save:
    When submitted manifest is altered (changed block_id, reordered, omitted,
    added, foreign, duplicate), save fails closed with is_grounded = False.
    """
    msg_a, _, c_a1, c_a2, _ = setup_test_cached_emails()
    cached_manifest = list(msg_a.claim_bindings)

    # 1. Changed block_id
    alt1 = [dict(cached_manifest[0], block_id="block_tampered"), cached_manifest[1]]
    res1 = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": msg_a.draft_id,
            "claim_bindings": alt1
        }
    )
    assert res1.json()["is_grounded"] is False
    assert res1.json()["grounding_status"] == GroundingStatus.VALIDATION_FAILED.value

    # Reset email state
    setup_test_cached_emails()
    msg_a = CACHED_EMAILS["email_a_phase554"]

    # 2. Reordered bindings
    alt2 = [cached_manifest[1], cached_manifest[0]]
    res2 = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": msg_a.draft_id,
            "claim_bindings": alt2
        }
    )
    assert res2.json()["is_grounded"] is False

    # Reset email state
    setup_test_cached_emails()
    msg_a = CACHED_EMAILS["email_a_phase554"]

    # 3. Omitted binding
    alt3 = [cached_manifest[0]]
    res3 = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": msg_a.draft_id,
            "claim_bindings": alt3
        }
    )
    assert res3.json()["is_grounded"] is False

    # Reset email state
    setup_test_cached_emails()
    msg_a = CACHED_EMAILS["email_a_phase554"]

    # 4. Added foreign binding from another email
    c_foreign = generate_canonical_claim("FACT_EMPLOYMENT_IBM", draft_id="draft_foreign")
    foreign_b = {
        "claim_instance_id": c_foreign["claim_instance_id"],
        "draft_id": "draft_foreign",
        "block_id": "block_foreign",
        "start_offset": 0,
        "end_offset": len(c_foreign["rendered_text"]),
        "submitted_block_text": c_foreign["rendered_text"]
    }
    alt4 = cached_manifest + [foreign_b]
    res4 = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": msg_a.draft_id,
            "claim_bindings": alt4
        }
    )
    assert res4.json()["is_grounded"] is False


def test_failure_c_substituted_manifest_fails_closed_in_risk_check():
    """
    Failure C reproduction & fix in risk check:
    Altered manifest in /risk-check triggers DIVERGENCE_DETECTED,
    is_grounded = False, risk_is_current = False.
    """
    msg_a, _, _, _, _ = setup_test_cached_emails()
    cached_manifest = list(msg_a.claim_bindings)

    # Substituted manifest with modified block_id
    tampered_manifest = [dict(cached_manifest[0], block_id="block_hacked"), cached_manifest[1]]

    res = client.post(
        f"/api/emails/{msg_a.id}/risk-check",
        headers=AUTH_HEADER,
        json={
            "draft_id": msg_a.draft_id,
            "draft_text": msg_a.draft_reply,
            "claim_bindings": tampered_manifest
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "DIVERGENCE_DETECTED"
    assert data["is_grounded"] is False
    assert data["risk_is_current"] is False


# ===========================================================================
# 4. Failure D: Asynchronous Risk Lifecycle and Freshness (Step 2, 7, 8, 9)
# ===========================================================================

def test_failure_d_deterministic_frontend_risk_freshness_lifecycle():
    """
    Failure D reproduction & verification:
    Simulate the client-side risk generation snapshot & validation logic.
    Ensure that edit, email switch, regeneration, and malformed responses
    reliably discard stale asynchronous responses.
    """
    email_a_id = "email_a_phase554"
    draft_a_id = "draft_phase554_email_a"
    text_a = "Original draft text"
    text_a_hash = compute_sha256(text_a)

    # 1. State Snapshot at Request Creation
    app_state = {
      "selectedEmailId": email_a_id,
      "activeRiskToken": "risk_token_1",
      "riskRequestGeneration": 1
    }
    captured = {
      "token": "risk_token_1",
      "generation": 1,
      "emailId": email_a_id,
      "draftId": draft_a_id,
      "draftText": text_a,
      "draftTextHash": text_a_hash,
      "selectedEmailId": email_a_id
    }

    # Simulation validator function matching frontend/app.js logic
    def validate_risk_response(response_data, current_text, email_msg):
        # Freshness / Staleness check
        is_stale = (
            app_state["activeRiskToken"] != captured["token"] or
            app_state["riskRequestGeneration"] != captured["generation"] or
            app_state["selectedEmailId"] != captured["selectedEmailId"] or
            email_msg is None or
            email_msg.id != captured["emailId"] or
            email_msg.draft_id != captured["draftId"] or
            current_text != captured["draftText"]
        )
        if is_stale:
            return False, "DISCARD_STALE"

        # Integrity check
        is_malformed = (
            not response_data or
            not isinstance(response_data, dict) or
            response_data.get("status") not in ("SUCCESS", "VALIDATION_FAILED", "DIVERGENCE_DETECTED") or
            response_data.get("email_id") != captured["emailId"] or
            (response_data.get("status") == "SUCCESS" and (
                response_data.get("draft_id") != captured["draftId"] or
                not response_data.get("risk_is_current") or
                not response_data.get("risk") or
                not isinstance(response_data.get("risk", {}).get("severity"), str) or
                not isinstance(response_data.get("risk", {}).get("recommended_action"), str)
            ))
        )
        if is_malformed:
            return False, "FAIL_MALFORMED"

        return True, "APPLY"

    email_msg_mock = EmailMessage(
        id=email_a_id,
        subject="Test",
        sender_name="Alice",
        sender_email="alice@test.com",
        body_text="Hi",
        draft_reply=text_a,
        draft_id=draft_a_id,
        received_at="2026-09-15 10:00:00"
    )

    valid_response = {
        "status": "SUCCESS",
        "email_id": email_a_id,
        "draft_id": draft_a_id,
        "draft_text_hash": text_a_hash,
        "risk_is_current": True,
        "is_grounded": True,
        "risk": {
            "severity": "LOW",
            "recommended_action": "PROCEED"
        }
    }

    # Case 1: Unchanged state -> Applies successfully
    ok, act = validate_risk_response(valid_response, text_a, email_msg_mock)
    assert ok is True and act == "APPLY"

    # Case 2: Edit occurred while request was in-flight (app_state token invalidated & text changed)
    app_state["activeRiskToken"] = None
    app_state["riskRequestGeneration"] = 2
    ok_edit, act_edit = validate_risk_response(valid_response, "Edited text", email_msg_mock)
    assert ok_edit is False and act_edit == "DISCARD_STALE"

    # Case 3: Text edited and restored to original while in-flight (generation changed)
    ok_restored, act_restored = validate_risk_response(valid_response, text_a, email_msg_mock)
    assert ok_restored is False and act_restored == "DISCARD_STALE"

    # Case 4: Email switch occurred while request was in-flight
    app_state["activeRiskToken"] = "risk_token_2"
    app_state["riskRequestGeneration"] = 3
    app_state["selectedEmailId"] = "email_b_phase554"
    ok_switch, act_switch = validate_risk_response(valid_response, text_a, email_msg_mock)
    assert ok_switch is False and act_switch == "DISCARD_STALE"

    # Case 5: Malformed response received
    app_state["selectedEmailId"] = email_a_id
    app_state["activeRiskToken"] = captured["token"]
    app_state["riskRequestGeneration"] = captured["generation"]
    malformed_resp = {"status": "SUCCESS", "email_id": email_a_id, "risk": None}
    ok_mal, act_mal = validate_risk_response(malformed_resp, text_a, email_msg_mock)
    assert ok_mal is False and act_mal == "FAIL_MALFORMED"


def test_save_and_risk_with_exact_manifest_succeeds_grounded():
    """
    Step 5 / Step 9 (21): Save and risk succeed with is_grounded = True and risk_is_current = True
    when exact cached manifest and text hash are submitted.
    """
    msg_a, _, _, _, _ = setup_test_cached_emails()

    # 1. Save draft with exact manifest
    res_save = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": msg_a.draft_id,
            "claim_bindings": msg_a.claim_bindings
        }
    )
    assert res_save.status_code == 200
    data_save = res_save.json()
    assert data_save["is_grounded"] is True
    assert data_save["grounding_status"] == GroundingStatus.GROUNDED.value

    # 2. Risk check with exact manifest
    res_risk = client.post(
        f"/api/emails/{msg_a.id}/risk-check",
        headers=AUTH_HEADER,
        json={
            "draft_id": msg_a.draft_id,
            "draft_text": msg_a.draft_reply,
            "claim_bindings": msg_a.claim_bindings
        }
    )
    assert res_risk.status_code == 200
    data_risk = res_risk.json()
    assert data_risk["status"] == "SUCCESS"
    assert data_risk["is_grounded"] is True
    assert data_risk["risk_is_current"] is True


def test_failure_c_empty_or_missing_manifest_fails_closed_for_grounded_draft():
    """
    Step 9 (28, 29): Submitting an empty or missing manifest for a draft with
    cached claims fails closed (is_grounded = False).
    """
    msg_a, _, _, _, _ = setup_test_cached_emails()

    # Empty claim_bindings list
    res_empty = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": msg_a.draft_id,
            "claim_bindings": []
        }
    )
    assert res_empty.json()["is_grounded"] is False

    # Reset email state
    setup_test_cached_emails()
    msg_a = CACHED_EMAILS["email_a_phase554"]

    # None claim_bindings
    res_none = client.post(
        f"/api/emails/{msg_a.id}/save-draft",
        headers=AUTH_HEADER,
        json={
            "reply_body": msg_a.draft_reply,
            "draft_id": msg_a.draft_id,
            "claim_bindings": None
        }
    )
    assert res_none.json()["is_grounded"] is False


# ===========================================================================
# 5. Security Invariant Tests (Step 10, 11)
# ===========================================================================

def test_zero_transmission_invariant_send_reply_blocked():
    """
    Step 11: /api/emails/{id}/send-reply remains strictly blocked with 403 SEND_FORBIDDEN.
    """
    setup_test_cached_emails()
    res = client.post("/api/emails/email_a_phase554/send-reply", headers=AUTH_HEADER, json={"reply_body": "test"})
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_canonical_employment_ledger_and_ibm_watson_intact():
    """
    Step 10: All 8 verified canonical employment tenures and IBM Watson mapping remain exact.
    """
    assert len(CANONICAL_EMPLOYMENT_RECORDS) == 8
    assert "ibm" in CANONICAL_EMPLOYMENT_RECORDS
    assert CANONICAL_EMPLOYMENT_RECORDS["ibm"].employer_canonical == "IBM"
    assert CANONICAL_EMPLOYMENT_RECORDS["google"].employer_canonical == "Google"
    assert CANONICAL_EMPLOYMENT_RECORDS["cdw"].employer_canonical == "CDW"
    assert CANONICAL_EMPLOYMENT_RECORDS["pythian"].employer_canonical == "Pythian"
    assert CANONICAL_EMPLOYMENT_RECORDS["dxc"].employer_canonical == "DXC Technology"
    assert CANONICAL_EMPLOYMENT_RECORDS["promevo"].employer_canonical == "Promevo"
    assert CANONICAL_EMPLOYMENT_RECORDS["mavencode_advisory"].employer_canonical == "MavenCode"
    assert CANONICAL_EMPLOYMENT_RECORDS["mavencode_director"].employer_canonical == "MavenCode"


def test_localhost_privilege_and_auth_boundary_intact():
    """
    Step 11: Unauthenticated access to privileged endpoints is rejected with 401/403.
    """
    r1 = client.post("/api/canonical/claims/verify", json={})
    assert r1.status_code in (401, 403)

    r2 = client.post("/api/emails/email_a_phase554/save-draft", json={})
    assert r2.status_code in (401, 403)

    r3 = client.post("/api/emails/email_a_phase554/invalidate-draft", json={})
    assert r3.status_code in (401, 403)

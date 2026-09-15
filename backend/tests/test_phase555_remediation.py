"""
Aura Mail AI - Phase 5.5.5 Micro-Remediation Comprehensive Regression Suite
Tests that:
1. Invalidation-persistence failures are never swallowed and return explicit fail-closed states (INVALIDATION_PERSISTENCE_FAILURE).
2. Server-side risk evaluation captures an immutable snapshot and performs atomic compare-and-set to discard stale/invalidated results.
3. Completed risk evaluations cannot commit against modified, replaced, invalidated, or quarantined drafts.
4. Exact draft-text-hash matching is enforced in frontend response validation.
5. All inherited transmission, capability, and canonical ledger invariants remain intact.
"""

import pytest
import threading
import time
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app, CACHED_EMAILS, _EMAIL_STATE_LOCK, safely_invalidate_draft_authority
from backend.models import EmailMessage, ClassificationResult, EmailCategory
from backend.canonical_grounding import (
    PROVENANCE_STORE,
    GroundingStatus,
    ClaimStatus,
    compute_sha256,
    generate_canonical_claim,
    validate_canonical_grounding,
    canonicalize_binding_manifest,
    compute_manifest_digest,
    capture_risk_evaluation_snapshot,
    verify_risk_evaluation_snapshot,
    RiskEvaluationSnapshot,
    InvalidationPersistenceError,
    CANONICAL_EMPLOYMENT_RECORDS,
    CANONICAL_LEDGER_SCHEMA_VERSION,
    get_active_ledger_digest
)
from backend.auth import get_local_session_token


@pytest.fixture(autouse=True)
def reset_provenance_and_cache():
    """Reset in-memory provenance store, quarantine set, and email cache between tests."""
    with _EMAIL_STATE_LOCK:
        PROVENANCE_STORE.reset_store()
        CACHED_EMAILS.clear()
    yield
    with _EMAIL_STATE_LOCK:
        PROVENANCE_STORE.reset_store()
        CACHED_EMAILS.clear()


@pytest.fixture
def auth_client():
    token = get_local_session_token()
    client = TestClient(app)
    client.headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "https://localhost:8000"
    }
    return client


def _setup_grounded_email(email_id="email_p555_1", fact_id="FACT_GOOGLE_REVENUE", draft_id="draft_p555_1"):
    """Helper to setup a valid grounded draft for an email."""
    claim_rec = PROVENANCE_STORE.create_claim_instance(
        fact_id=fact_id,
        template_id="TPL_GOOGLE_REVENUE_CONCISE",
        draft_id=draft_id
    )
    exact_text = f"At Google, {claim_rec.exact_rendered_text}."
    start_off = exact_text.index(claim_rec.exact_rendered_text)
    end_off = start_off + len(claim_rec.exact_rendered_text)

    binding = {
        "claim_instance_id": claim_rec.claim_instance_id,
        "draft_id": draft_id,
        "block_id": "block_1",
        "start_offset": start_off,
        "end_offset": end_off,
        "submitted_block_text": claim_rec.exact_rendered_text
    }

    text_hash = compute_sha256(exact_text)

    msg = EmailMessage(
        id=email_id,
        subject="Executive Role",
        sender_name="Alice Recruiter",
        sender_email="alice@techrecruit.com",
        body_text="We have an executive opportunity.",
        draft_reply=exact_text,
        draft_id=draft_id,
        claim_bindings=[binding],
        is_grounded=True,
        grounding_status=GroundingStatus.GROUNDED.value,
        draft_text_hash=text_hash
    )
    with _EMAIL_STATE_LOCK:
        CACHED_EMAILS[email_id] = msg
    return msg, binding, exact_text, text_hash


# ===========================================================================
# Section A: Invalidation-Persistence Behavior Tests
# ===========================================================================

def test_failure_a1_save_path_invalidation_persistence_failure_fails_closed(auth_client):
    """
    When claims validation fails during save and invalidation persistence fails:
    - Authority is quarantined.
    - Response explicitly returns INVALIDATION_PERSISTENCE_FAILURE.
    - is_grounded = False, risk_is_current = False, requires_human_review = True.
    - Prior authority cannot be replayed.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()

    # Corrupt binding text to trigger validation failure
    corrupt_bindings = [{
        **binding,
        "submitted_block_text": "I generated $8M in revenue at Google."
    }]

    with patch.object(PROVENANCE_STORE, "_persist_to_disk", side_effect=RuntimeError("Disk write simulated failure")):
        payload = {
            "draft_id": msg.draft_id,
            "draft_reply": exact_text,
            "claim_bindings": corrupt_bindings
        }
        res = auth_client.post(f"/api/emails/{msg.id}/save-draft", json=payload)
        data = res.json()

        assert data["status"] == "INVALIDATION_PERSISTENCE_FAILURE"
        assert data["is_grounded"] is False
        assert data["risk_is_current"] is False
        assert data["requires_human_review"] is True
        assert "quarantined" in data["validation_summary"].lower()

        # Verify draft identity is quarantined in PROVENANCE_STORE
        assert PROVENANCE_STORE.is_draft_quarantined("draft_p555_1") is True


def test_failure_a2_risk_path_invalidation_persistence_failure_fails_closed(auth_client):
    """
    When draft divergence occurs during risk check and invalidation persistence fails:
    - Authority is quarantined.
    - Response explicitly returns status = INVALIDATION_PERSISTENCE_FAILURE.
    - is_grounded = False, risk_is_current = False, requires_human_review = True.
    - Replay verification after failure is rejected.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    orig_draft_id = msg.draft_id

    with patch.object(PROVENANCE_STORE, "_persist_to_disk", side_effect=RuntimeError("I/O error during risk invalidation")):
        payload = {
            "draft_id": orig_draft_id,
            "draft_text": "Modified unauthorized draft text.",
            "claim_bindings": [binding]
        }
        res = auth_client.post(f"/api/emails/{msg.id}/risk-check", json=payload)
        data = res.json()

        assert data["status"] == "INVALIDATION_PERSISTENCE_FAILURE"
        assert data["is_grounded"] is False
        assert data["risk_is_current"] is False
        assert data["requires_human_review"] is True
        assert PROVENANCE_STORE.is_draft_quarantined(orig_draft_id) is True


def test_failure_a3_invalidate_draft_endpoint_persistence_failure_raises_500(auth_client):
    """
    POST /api/emails/{id}/invalidate-draft returns 500 INVALIDATION_PERSISTENCE_FAILURE
    when disk persistence raises, placing authority into quarantine.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    orig_draft_id = msg.draft_id

    with patch.object(PROVENANCE_STORE, "_persist_to_disk", side_effect=IOError("Simulated disk full")):
        res = auth_client.post(f"/api/emails/{msg.id}/invalidate-draft", json={"draft_id": orig_draft_id})
        assert res.status_code == 500
        detail = res.json()["detail"]
        assert detail["error_code"] == "INVALIDATION_PERSISTENCE_FAILURE"
        assert detail["requires_human_review"] is True
        assert PROVENANCE_STORE.is_draft_quarantined(orig_draft_id) is True


def test_failure_a4_quarantined_draft_replay_rejected_after_persistence_failure():
    """
    Proves that a claim belonging to a quarantined draft cannot be verified
    or validated as grounded under any circumstance.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    claim_id = binding["claim_instance_id"]

    # Force persistence failure during invalidation
    with patch.object(PROVENANCE_STORE, "_persist_to_disk", side_effect=RuntimeError("Persistence failure")):
        with pytest.raises(InvalidationPersistenceError):
            PROVENANCE_STORE.invalidate_draft_claims(msg.draft_id, reason="Manual edit")

    assert PROVENANCE_STORE.is_draft_quarantined(msg.draft_id) is True

    # Attempt to retrieve claim
    rec = PROVENANCE_STORE.get_claim_instance(claim_id)
    assert rec is not None
    assert rec.is_invalidated is True

    # Attempt to validate grounding on original text
    val_res = validate_canonical_grounding(
        draft_text=exact_text,
        claim_bindings=[binding],
        draft_id=msg.draft_id
    )
    assert val_res.is_grounded is False
    assert val_res.status in [GroundingStatus.INVALIDATED, GroundingStatus.VALIDATION_FAILED]


# ===========================================================================
# Section B: Server-Side Risk Concurrency & Atomic Compare-and-Set Tests
# ===========================================================================

def test_failure_b1_in_flight_risk_evaluation_discarded_after_invalidation(auth_client):
    """
    Deterministic concurrency test:
    1. Risk check starts for draft A.
    2. During slow model evaluation, draft A is invalidated.
    3. Model evaluation finishes.
    4. Atomic compare-and-set detects invalidation and discards result.
    5. risk_is_current remains False.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()

    eval_started = threading.Event()
    eval_continue = threading.Event()

    original_eval = None
    import backend.main

    def controlled_evaluate(*args, **kwargs):
        eval_started.set()
        eval_continue.wait(timeout=5.0)
        from backend.radar.risk_evaluator import RiskAssessmentResult, RiskSeverity
        return RiskAssessmentResult(
            severity=RiskSeverity.SAFE,
            is_flagged=False,
            risk_score=10,
            second_opinion_summary="Model evaluation completed",
            recommended_action="PROCEED"
        )

    response_container = {}

    def run_risk_request():
        payload = {
            "draft_id": msg.draft_id,
            "draft_text": exact_text,
            "claim_bindings": [binding]
        }
        res = auth_client.post(f"/api/emails/{msg.id}/risk-check", json=payload)
        response_container["data"] = res.json()

    with patch("backend.main.evaluate_second_opinion_risk", side_effect=controlled_evaluate):
        req_thread = threading.Thread(target=run_risk_request)
        req_thread.start()

        # Wait until evaluation begins
        assert eval_started.wait(timeout=3.0) is True

        # While evaluation is running, invalidate draft on server
        with _EMAIL_STATE_LOCK:
            safely_invalidate_draft_authority(msg.draft_id, email_msg=msg, reason="User edited draft concurrently")

        # Resume evaluation
        eval_continue.set()
        req_thread.join(timeout=3.0)

        data = response_container["data"]
        assert data["status"] == "STALE_EVALUATION"
        assert data["risk_is_current"] is False
        assert data["is_grounded"] is False
        assert data["requires_human_review"] is True

        # Verify cached email state is not mutated by stale evaluation
        assert msg.risk_is_current is False


def test_failure_b2_in_flight_risk_evaluation_discarded_after_draft_replacement(auth_client):
    """
    When a draft is regenerated during in-flight risk evaluation:
    - The old evaluation completes.
    - Snapshot re-validation fails due to draft_id & draft_version change.
    - Old evaluation is discarded; cannot bind to the replacement draft.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()

    eval_started = threading.Event()
    eval_continue = threading.Event()

    def controlled_evaluate(*args, **kwargs):
        eval_started.set()
        eval_continue.wait(timeout=5.0)
        from backend.radar.risk_evaluator import RiskAssessmentResult, RiskSeverity
        return RiskAssessmentResult(
            severity=RiskSeverity.SAFE,
            recommended_action="PROCEED"
        )

    response_container = {}

    def run_risk_request():
        payload = {
            "draft_id": msg.draft_id,
            "draft_text": exact_text,
            "claim_bindings": [binding]
        }
        res = auth_client.post(f"/api/emails/{msg.id}/risk-check", json=payload)
        response_container["data"] = res.json()

    with patch("backend.main.evaluate_second_opinion_risk", side_effect=controlled_evaluate):
        req_thread = threading.Thread(target=run_risk_request)
        req_thread.start()

        assert eval_started.wait(timeout=3.0) is True

        # Replace draft concurrently
        with _EMAIL_STATE_LOCK:
            msg.draft_id = "draft_new_regenerated_999"
            msg.draft_text_hash = "hash_new_regenerated_999"
            msg.draft_version += 1
            msg.risk_is_current = False

        eval_continue.set()
        req_thread.join(timeout=3.0)

        data = response_container["data"]
        assert data["status"] == "STALE_EVALUATION"
        assert data["risk_is_current"] is False
        assert msg.risk_is_current is False


def test_failure_b3_unchanged_draft_risk_evaluation_succeeds(auth_client):
    """
    When draft remains unchanged during evaluation:
    - Snapshot verifies atomically.
    - Result is bound to active draft.
    - status = SUCCESS, risk_is_current = True, is_grounded = True.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()

    payload = {
        "draft_id": msg.draft_id,
        "draft_text": exact_text,
        "claim_bindings": [binding]
    }
    res = auth_client.post(f"/api/emails/{msg.id}/risk-check", json=payload)
    data = res.json()

    assert data["status"] == "SUCCESS"
    assert data["risk_is_current"] is True
    assert data["is_grounded"] is True
    assert data["draft_text_hash"] == text_hash
    assert msg.risk_is_current is True
    assert msg.risk_draft_id == msg.draft_id


# ===========================================================================
# Section C: Exact-Content Snapshot Binding Rejection Tests
# ===========================================================================

def test_snapshot_revalidation_rejects_single_field_discrepancies():
    """
    Tests that verify_risk_evaluation_snapshot rejects if any single field is altered.
    """
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    snapshot = capture_risk_evaluation_snapshot(msg.id, msg)
    assert snapshot is not None

    # 1. Quarantined draft
    PROVENANCE_STORE.quarantine_draft(msg.draft_id)
    is_valid, reason = verify_risk_evaluation_snapshot(snapshot, msg)
    assert is_valid is False
    assert "quarantined" in reason.lower()
    PROVENANCE_STORE.reset_store()

    # 2. Altered draft_id
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    snapshot = capture_risk_evaluation_snapshot(msg.id, msg)
    msg.draft_id = "draft_replaced"
    is_valid, reason = verify_risk_evaluation_snapshot(snapshot, msg)
    assert is_valid is False
    assert "draft id changed" in reason.lower()

    # 3. Altered draft_version
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    snapshot = capture_risk_evaluation_snapshot(msg.id, msg)
    msg.draft_version = snapshot.draft_version + 1
    is_valid, reason = verify_risk_evaluation_snapshot(snapshot, msg)
    assert is_valid is False
    assert "draft version changed" in reason.lower()

    # 4. Altered draft_text_hash
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    snapshot = capture_risk_evaluation_snapshot(msg.id, msg)
    msg.draft_text_hash = "tampered_hash"
    is_valid, reason = verify_risk_evaluation_snapshot(snapshot, msg)
    assert is_valid is False
    assert "text hash" in reason.lower()

    # 5. Altered canonical manifest
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    snapshot = capture_risk_evaluation_snapshot(msg.id, msg)
    msg.claim_bindings = []
    is_valid, reason = verify_risk_evaluation_snapshot(snapshot, msg)
    assert is_valid is False
    assert "manifest bindings changed" in reason.lower()

    # 6. Altered invalidation state
    msg, binding, exact_text, text_hash = _setup_grounded_email()
    snapshot = capture_risk_evaluation_snapshot(msg.id, msg)
    msg.invalidation_issued = True
    is_valid, reason = verify_risk_evaluation_snapshot(snapshot, msg)
    assert is_valid is False
    assert "invalidation was issued" in reason.lower()


# ===========================================================================
# Section D: Direct JavaScript Test Execution
# ===========================================================================

def test_direct_javascript_test_suite_execution():
    """
    Executes the pure JavaScript test suite using JavaScriptCore (macOS jsc).
    Proves that the actual production JavaScript module (frontend/risk_validator.js)
    is executed and passes all 17 assertions.
    """
    jsc_path = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
    test_file = Path(__file__).parent / "test_frontend_risk_validator.js"
    assert test_file.exists(), f"JS test file {test_file} must exist"

    result = subprocess.run(
        [jsc_path, str(test_file)],
        capture_output=True,
        text=True,
        cwd=str(test_file.parent.parent.parent)
    )

    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)

    assert result.returncode == 0, f"JSC execution failed: {result.stderr}"
    assert "All 17/17 JavaScript Risk Validator tests passed successfully!" in result.stdout


# ===========================================================================
# Section E: Inherited Invariant Regressions
# ===========================================================================

def test_inherited_invariant_send_is_forbidden_403(auth_client):
    """
    Confirms zero-transmission invariant: /send-reply returns HTTP 403 SEND_FORBIDDEN.
    """
    res = auth_client.post("/api/emails/any_id/send-reply", json={"reply_body": "test"})
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_inherited_invariant_ibm_watson_record_mapping():
    """
    Confirms IBM Watson fact maps to canonical employment record 'ibm'.
    """
    claim = PROVENANCE_STORE.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_ibm_test"
    )
    assert claim.employment_record_id == "ibm"
    assert claim.canonical_fact_id == "FACT_EMPLOYMENT_IBM_WATSON"
    assert claim.template_id == "TPL_EMP_IBM_WATSON"


def test_inherited_invariant_canonical_employment_ledger_eight_tenures():
    """
    Confirms exact 8-tenure employment ledger.
    """
    assert len(CANONICAL_EMPLOYMENT_RECORDS) == 8
    expected_employers = {"mavencode_advisory", "mavencode_director", "promevo", "cdw", "pythian", "google", "dxc", "ibm"}
    assert set(CANONICAL_EMPLOYMENT_RECORDS.keys()) == expected_employers

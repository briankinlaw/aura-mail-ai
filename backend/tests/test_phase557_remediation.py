"""
Phase 5.5.7 Durable Fail-Closed Micro-Remediation Tests (Aura Mail AI Revision 2.1).

Covers:
1. Section A: Direct same-process fresh-instance restart test.
2. Section B: Subprocess application restart test.
3. Section C: Malformed/corrupted/unreadable/unknown state marker tests.
4. Section D: Explicit administrative recovery (RESET_ALL_PROVENANCE and VALIDATE_AND_REPAIR).
5. Section E: Anti-auto-recovery tests (requests/startup cannot re-enable).
6. Section F: Invalidation persistence failure with durable disablement & radar stopping.
7. Section G: Snapshot metadata clarification (created_at is non-authoritative observational metadata).
8. Section H: Inherited Security Invariants.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from backend.main import app, CACHED_EMAILS, safely_invalidate_draft_authority, _EMAIL_STATE_LOCK
from backend.models import EmailMessage, EmailCategory, ClassificationResult
from backend.canonical_grounding import (
    ProvenanceStore,
    ProvenanceRecord,
    PROVENANCE_STORE,
    GroundingStatus,
    ClaimStatus,
    InvalidationPersistenceError,
    RiskEvaluationSnapshot,
    capture_risk_evaluation_snapshot,
    verify_risk_evaluation_snapshot,
    compute_sha256,
    canonicalize_binding_manifest,
    compute_manifest_digest,
    validate_canonical_grounding,
    verify_provenance_claim_binding,
    get_available_templates,
    CANONICAL_EMPLOYMENT_RECORDS,
    CANONICAL_CLAIM_TEMPLATES,
    CANONICAL_LEDGER_SCHEMA_VERSION,
    get_active_ledger_digest,
    RecoveryStrategy,
    RecoveryExecutionContext,
    AdministrativeRecoveryContext,
)
from backend.auth import get_local_session_token, issue_administrative_recovery_token
from backend.tests.conftest import test_reset_provenance_store


@pytest.fixture(autouse=True)
def clean_store_environment():
    """Ensures clean provenance store and cached email state before and after every test."""
    with _EMAIL_STATE_LOCK:
        CACHED_EMAILS.clear()
        test_reset_provenance_store()
    yield
    with _EMAIL_STATE_LOCK:
        CACHED_EMAILS.clear()
        test_reset_provenance_store()


@pytest.fixture
def auth_client():
    token = get_local_session_token()
    client = TestClient(app)
    client.headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "https://localhost:8000"
    }
    return client


# ===========================================================================
# Section A: Direct Same-Process Fresh-Instance Restart Test
# ===========================================================================

def test_same_process_fresh_instance_preserves_durably_disabled_state(tmp_path):
    """
    Proves that creating a new ProvenanceStore instance over a durably disabled
    storage location starts unavailable and cannot revive claims.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    # Step 1: Create Store A and create a valid claim
    store_a = ProvenanceStore(storage_path=storage_file)
    assert store_a.is_available() is True
    assert store_a.state_path == state_file

    rec = store_a.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_restart_test_1"
    )
    assert rec is not None
    assert rec.claim_instance_id in store_a._records

    # Step 2: Durably disable Store A
    store_a.disable_store(reason="Catastrophic invalidation failure", affected_draft_id="draft_restart_test_1")
    assert store_a.is_available() is False
    assert state_file.exists() is True

    with open(state_file, "r", encoding="utf-8") as f:
        st_data = json.load(f)
    assert st_data["state"] == "DISABLED"
    assert st_data["schema_version"] == 1
    assert st_data["recovery_required"] is True
    assert st_data["affected_draft_id"] == "draft_restart_test_1"

    # Step 3: Verify Store A denies claim retrieval and creation
    assert store_a.get_claim_instance(rec.claim_instance_id) is None
    with pytest.raises(RuntimeError, match="Provenance store is unavailable"):
        store_a.create_claim_instance(
            fact_id="FACT_EMPLOYMENT_IBM_WATSON",
            template_id="TPL_EMP_IBM_WATSON",
            draft_id="draft_restart_test_2"
        )

    # Step 4: Create fresh Store B over exact same files
    store_b = ProvenanceStore(storage_path=storage_file)

    # Prove Store B starts unavailable
    assert store_b.is_available() is False
    assert "DURABLY_DISABLED" in (store_b._unavailable_reason or "")

    # Prove claims are not exposed or revived
    assert store_b.get_claim_instance(rec.claim_instance_id) is None
    assert len(store_b._records) == 0

    # Prove new claims cannot be created in Store B
    with pytest.raises(RuntimeError, match="Provenance store is unavailable"):
        store_b.create_claim_instance(
            fact_id="FACT_EMPLOYMENT_IBM_WATSON",
            template_id="TPL_EMP_IBM_WATSON",
            draft_id="draft_restart_test_3"
        )


# ===========================================================================
# Section B: Subprocess Application Restart Test
# ===========================================================================

def test_subprocess_restart_preserves_durably_disabled_state(tmp_path):
    """
    Spawns a fresh Python interpreter in a subprocess to prove that process restarts
    do not clear the disabled condition or revive claims from the storage directory.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    # Setup disabled store with an existing claim
    store = ProvenanceStore(storage_path=storage_file)
    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_subproc_1"
    )
    claim_id = rec.claim_instance_id
    store.disable_store(reason="Subprocess test disable", affected_draft_id="draft_subproc_1")

    # Subprocess script to inspect fresh ProvenanceStore instance
    code = f"""
import sys
from pathlib import Path
from backend.canonical_grounding import ProvenanceStore

store = ProvenanceStore(storage_path=r"{storage_file}")
if store.is_available():
    print("FAIL: store is available")
    sys.exit(1)

claim = store.get_claim_instance("{claim_id}")
if claim is not None:
    print("FAIL: claim was retrieved")
    sys.exit(2)

try:
    store.create_claim_instance("FACT_EMPLOYMENT_IBM_WATSON", "TPL_EMP_IBM_WATSON", "draft_subproc_2")
    print("FAIL: claim creation succeeded")
    sys.exit(3)
except RuntimeError:
    pass

print("PASS: subprocess store is durably disabled")
sys.exit(0)
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent.parent)
    )
    assert proc.returncode == 0, f"Subprocess failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "PASS: subprocess store is durably disabled" in proc.stdout


# ===========================================================================
# Section C: Malformed/Corrupted/Unreadable State Marker Tests
# ===========================================================================

@pytest.mark.parametrize("corrupt_content,expected_err_snippet", [
    ("not-valid-json{{{", "STATE_FILE_INVALID"),
    (json.dumps(["not", "a", "dict"]), "STATE_FILE_INVALID"),
    (json.dumps({"state": "DISABLED"}), "STATE_FILE_INVALID"),  # Missing schema_version
    (json.dumps({"schema_version": 99, "state": "DISABLED"}), "STATE_FILE_INVALID"),  # Unsupported schema
    (json.dumps({"schema_version": 1}), "STATE_FILE_INVALID"),  # Missing state field
    (json.dumps({"schema_version": 1, "state": "UNKNOWN_STATE_XYZ"}), "STATE_FILE_INVALID"),
])
def test_malformed_state_file_starts_unavailable_fail_closed(tmp_path, corrupt_content, expected_err_snippet):
    """
    Proves that any malformed, corrupted, or unknown state marker forces the store
    to start unavailable fail-closed without deleting or ignoring the file.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    # Write corrupt state file
    with open(state_file, "w", encoding="utf-8") as f:
        f.write(corrupt_content)

    store = ProvenanceStore(storage_path=storage_file)
    assert store.is_available() is False
    assert expected_err_snippet in (store._unavailable_reason or "")
    # State file must remain intact
    assert state_file.exists() is True


def test_valid_claim_file_with_disabled_marker_remains_unavailable(tmp_path):
    """
    Proves that a syntactically valid provenance_records.json file cannot override
    or bypass a DISABLED state marker on startup.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    # First write valid claims
    store_init = ProvenanceStore(storage_path=storage_file)
    rec = store_init.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_valid_test"
    )
    cid = rec.claim_instance_id
    assert storage_file.exists() is True

    # Now write DISABLED state marker
    state_data = {
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Administrative lockdown",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)

    # Re-initialize store
    fresh_store = ProvenanceStore(storage_path=storage_file)
    assert fresh_store.is_available() is False
    assert fresh_store.get_claim_instance(cid) is None
    assert len(fresh_store._records) == 0


# ===========================================================================
# Section D: Explicit Administrative Recovery (recover_store)
# ===========================================================================

def test_recovery_requires_explicit_supported_strategy(tmp_path):
    """
    Proves that recover_store rejects unknown or inferred recovery strategies.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    admin_ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=get_local_session_token(),
    )

    with pytest.raises(ValueError, match="Unsupported recovery strategy"):
        store.recover_store(strategy="AUTO_GUESS", recovery_context=admin_ctx)


def test_recovery_strategy_reset_all_provenance(tmp_path):
    """
    Proves RESET_ALL_PROVENANCE safely clears claim records, removes disabled marker,
    and restores availability.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    store = ProvenanceStore(storage_path=storage_file)
    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_reset_1"
    )
    store.disable_store("Test disable", affected_draft_id="draft_reset_1")
    assert store.is_available() is False
    assert state_file.exists() is True

    admin_ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=issue_administrative_recovery_token(actor="local_admin"),
    )

    # Execute RESET_ALL_PROVENANCE
    res = store.recover_store(strategy=RecoveryStrategy.RESET_ALL_PROVENANCE, recovery_context=admin_ctx)
    assert res is True
    assert store.is_available() is True
    assert state_file.exists() is False
    assert len(store._records) == 0

    # Verify a fresh instance starts available with 0 records
    fresh = ProvenanceStore(storage_path=storage_file)
    assert fresh.is_available() is True
    assert len(fresh._records) == 0


def test_recovery_strategy_validate_and_repair_is_rejected(tmp_path):
    """
    Proves VALIDATE_AND_REPAIR is strictly rejected in Phase 5.5.8.
    Store remains unavailable fail-closed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    store = ProvenanceStore(storage_path=storage_file)
    store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_affected"
    )
    store.disable_store("Test disable", affected_draft_id="draft_affected")
    assert store.is_available() is False

    admin_ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=get_local_session_token(),
    )

    # Execute VALIDATE_AND_REPAIR - must be rejected
    with pytest.raises(ValueError, match="Unsupported recovery strategy"):
        store.recover_store(strategy="VALIDATE_AND_REPAIR", recovery_context=admin_ctx)

    # Store remains unavailable and marker remains
    assert store.is_available() is False
    assert state_file.exists() is True


# ===========================================================================
# Section E: Anti-Auto-Recovery Tests
# ===========================================================================

def test_api_requests_do_not_auto_recover_disabled_store(auth_client):
    """
    Proves that ordinary API endpoints (/api/status, /api/canonical/templates, /api/radar/risk-check)
    cannot clear the disabled marker or restore availability.
    """
    PROVENANCE_STORE.disable_store("Lockdown test")
    assert PROVENANCE_STORE.is_available() is False

    # 1. System status
    resp1 = auth_client.get("/api/status")
    assert resp1.status_code == 200
    assert PROVENANCE_STORE.is_available() is False

    # 2. Canonical templates
    resp2 = auth_client.get("/api/canonical/templates")
    assert resp2.status_code == 200
    assert PROVENANCE_STORE.is_available() is False

    # 3. Radar risk check
    resp3 = auth_client.post("/api/radar/risk-check", json={
        "draft_text": "Normal email body without claims",
        "proposed_action": "ANALYZE"
    })
    assert PROVENANCE_STORE.is_available() is False


# ===========================================================================
# Section F: Invalidation Persistence Failure with Durable Disablement & Radar
# ===========================================================================

def test_radar_stops_on_store_disable_persistence_failure(auth_client):
    """
    Proves that /api/radar/risk-check stops immediately and does not invoke
    evaluate_second_opinion_risk even when store disable persistence fails.
    """
    with _EMAIL_STATE_LOCK:
        CACHED_EMAILS["email_radar_dis_fail"] = EmailMessage(
            id="email_radar_dis_fail",
            sender_name="Recruiter",
            sender_email="recruiter@example.com",
            subject="Interview",
            body_text="Let's talk",
            draft_id="draft_dis_fail_1",
            draft_reply="I led the Watson initiative at IBM.",
            draft_text_hash=compute_sha256("I led the Watson initiative at IBM."),
            is_grounded=True,
            grounding_status=GroundingStatus.GROUNDED.value,
            claim_bindings=[{
                "claim_instance_id": "claim_dis_1",
                "draft_id": "draft_dis_fail_1",
                "block_id": "block_0",
                "start_offset": 0,
                "end_offset": 36,
                "submitted_block_text": "I led the Watson initiative at IBM."
            }]
        )

    # Mock invalidation to fail and disable_store to fail
    with patch.object(PROVENANCE_STORE, "invalidate_draft_claims", side_effect=Exception("Disk error")), \
         patch.object(PROVENANCE_STORE, "quarantine_draft", side_effect=Exception("Quarantine failed")), \
         patch.object(PROVENANCE_STORE, "disable_store", side_effect=RuntimeError("State marker write failed")), \
         patch("backend.main.evaluate_second_opinion_risk") as mock_eval:

        resp = auth_client.post("/api/radar/risk-check", json={
            "email_id": "email_radar_dis_fail",
            "draft_id": "draft_divergent",
            "draft_text": "Divergent draft",
            "proposed_action": "DRAFT"
        })

        assert resp.status_code == 500
        data = resp.json()
        assert data["status"] == "STORE_DISABLE_PERSISTENCE_FAILURE"
        assert data["is_grounded"] is False
        assert data["risk_is_current"] is False
        assert data["requires_human_review"] is True
        assert mock_eval.call_count == 0


# ===========================================================================
# Section G: Snapshot Metadata Clarification
# ===========================================================================

def test_snapshot_created_at_is_observational_metadata():
    """
    Proves that created_at is observational metadata: modifying created_at alone
    does not invalidate verify_risk_evaluation_snapshot if all 15 authoritative
    dimensions remain unchanged.
    """
    email_msg = EmailMessage(
        id="email_snap_obs",
        sender_name="Recruiter",
        sender_email="recruiter@example.com",
        subject="Discussion",
        body_text="Body",
        draft_id="draft_snap_obs_1",
        draft_reply="I led the Watson initiative at IBM.",
        draft_text_hash=compute_sha256("I led the Watson initiative at IBM."),
        is_grounded=True,
        grounding_status=GroundingStatus.GROUNDED.value,
        claim_bindings=[{
            "claim_instance_id": "claim_snap_obs_1",
            "draft_id": "draft_snap_obs_1",
            "block_id": "block_0",
            "start_offset": 0,
            "end_offset": 36,
            "submitted_block_text": "I led the Watson initiative at IBM."
        }]
    )

    snapshot = capture_risk_evaluation_snapshot("email_snap_obs", email_msg)
    assert snapshot is not None

    # Verify snapshot with different created_at timestamp
    import dataclasses
    modified_snapshot = dataclasses.replace(snapshot, created_at=snapshot.created_at + 1000.0)

    is_valid, reason = verify_risk_evaluation_snapshot(modified_snapshot, email_msg)
    assert is_valid is True
    assert reason == "Snapshot verified and unchanged."


# ===========================================================================
# Section H: Inherited Security Invariants
# ===========================================================================

def test_inherited_invariant_send_is_forbidden_403(auth_client):
    """
    Confirms zero-transmission invariant: /send-reply returns HTTP 403 SEND_FORBIDDEN.
    """
    resp = auth_client.post("/api/emails/email_inv_1/send-reply", json={"reply_body": "Hello"})
    assert resp.status_code == 403
    detail = resp.json().get("detail", {})
    err_code = detail.get("error_code") if isinstance(detail, dict) else resp.json().get("error_code")
    assert err_code == "SEND_FORBIDDEN"


def test_inherited_invariant_canonical_employment_ledger_and_ibm_watson():
    """
    Confirms canonical employment ledger integrity and IBM Watson record association.
    """
    assert "ibm" in CANONICAL_EMPLOYMENT_RECORDS
    ibm_rec = CANONICAL_EMPLOYMENT_RECORDS["ibm"]
    assert ibm_rec.employer_canonical == "IBM"
    assert "watson analytics solution architect — big data paas sme" in ibm_rec.held_titles

    tpl = CANONICAL_CLAIM_TEMPLATES["TPL_EMP_IBM_WATSON"]
    assert tpl.fact_id == "FACT_EMPLOYMENT_IBM_WATSON"
    assert tpl.employment_record_id == "ibm"
    assert CANONICAL_LEDGER_SCHEMA_VERSION == "2.1.0"
    assert len(get_active_ledger_digest()) == 64


def test_portable_frontend_risk_validator_javascript_execution():
    """
    Executes the pure JavaScript test suite using an available JavaScript engine (node or jsc).
    Proves that the actual production JavaScript module (frontend/risk_validator.js)
    is executed and passes all 17 assertions.
    """
    test_file = Path(__file__).parent / "test_frontend_risk_validator.js"
    assert test_file.exists(), f"JS test file {test_file} must exist"

    node_bin = shutil.which("node")
    jsc_bin = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"

    if node_bin and os.path.exists(node_bin):
        cmd = [node_bin, str(test_file)]
    elif os.path.exists(jsc_bin):
        cmd = [jsc_bin, str(test_file)]
    else:
        pytest.skip("No JavaScript engine (node or jsc) available in environment")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(test_file.parent.parent.parent)
    )

    assert result.returncode == 0, f"JS execution failed: {result.stderr}"
    assert "All 17/17 JavaScript Risk Validator tests passed successfully!" in result.stdout

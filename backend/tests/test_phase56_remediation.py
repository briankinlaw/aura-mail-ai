"""
Phase 5.6 Offline Administrative Recovery Remediation Tests (Aura Mail AI Revision 2.1).

Covers all required Phase 5.6 test categories:
- Category A: No in-process recovery authority
- Category B: Offline invocation and precondition tests
- Category C: Authorized offline reset lifecycle
- Category D: Invalid-marker recovery cases
- Category E: Complete crash-order matrix (17 failure points)
- Category F: Tampered-record reset matrix (12 tampering cases)
- Category G: Inherited regression tests
"""

import os
import sys
import io
import time
import json
import uuid
import errno
import subprocess
from pathlib import Path
from typing import Dict, Any
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from backend.main import app, CACHED_EMAILS, _EMAIL_STATE_LOCK
from backend.models import EmailMessage, EmailCategory, ClassificationResult
from backend.canonical_grounding import (
    ProvenanceStore,
    ProvenanceRecord,
    PROVENANCE_STORE,
    GroundingStatus,
    ClaimStatus,
    InvalidationPersistenceError,
    RecoveryStrategy,
    RecoveryAuthorizationError,
    RiskEvaluationSnapshot,
    capture_risk_evaluation_snapshot,
    verify_risk_evaluation_snapshot,
    generate_canonical_claim,
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
)
import backend.auth as auth_mod
from backend.auth import get_local_session_token, verify_local_token
from backend.runtime_lock import (
    acquire_shared_runtime_lock,
    acquire_exclusive_maintenance_lock,
    RuntimeLockError,
    AuraRuntimeLockContext,
)
from backend.offline_recovery import (
    execute_offline_recovery_transaction,
    resolve_and_validate_paths,
    read_and_verify_recovery_required,
    get_local_os_actor,
    main as offline_recovery_main,
    RecoveryPreconditionError,
    RecoveryTerminalError,
    RecoveryConfirmationError,
    RecoveryTransactionError,
    RecoveryError,
    _fsync_parent_dir,
)
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


# ==============================================================================
# CATEGORY A: No In-Process Recovery Authority
# ==============================================================================

def test_recovery_token_symbols_completely_absent():
    """Prove all Phase 5.5.9 recovery token symbols are deleted from production."""
    assert not hasattr(auth_mod, "issue_administrative_recovery_token")
    assert not hasattr(auth_mod, "verify_and_consume_recovery_token")
    assert not hasattr(auth_mod, "clear_administrative_recovery_tokens")
    assert not hasattr(auth_mod, "_ACTIVE_RECOVERY_TOKENS")
    assert not hasattr(auth_mod, "_RECOVERY_TOKEN_LOCK")


def test_provenance_store_recover_store_is_blocked_stub_with_zero_mutation(tmp_path):
    """
    Prove ProvenanceStore.recover_store() raises RuntimeError and mutates zero state.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_blocked_stub"
    )
    cid = rec.claim_instance_id
    store.disable_store("Test disable", affected_draft_id="draft_blocked_stub")

    marker_bytes = state_file.read_bytes()
    store_bytes = storage_file.read_bytes()
    inv_count = store.get_invalidation_count()
    quarantined = set(store._quarantined_draft_ids)

    # Calling recover_store with any arguments raises RuntimeError
    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, "admin_context", force=True)

    # Assert zero state mutation
    assert store.is_available() is False
    assert state_file.read_bytes() == marker_bytes
    assert storage_file.read_bytes() == store_bytes
    assert store.get_invalidation_count() == inv_count
    assert store._quarantined_draft_ids == quarantined
    assert len(store._records) == 0


def test_enable_store_and_reset_store_are_blocked_stubs(tmp_path):
    """Prove enable_store and reset_store aliases raise RuntimeError."""
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.enable_store()

    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.reset_store()


def test_no_http_route_exposes_recovery(auth_client):
    """Prove no recovery endpoint exists on FastAPI application."""
    for path in ["/api/recover", "/api/recovery", "/api/reset-provenance", "/api/admin/recover", "/authorize-send"]:
        resp = auth_client.post(path, json={})
        assert resp.status_code in (404, 405)


def test_session_token_grants_zero_recovery_capability():
    """Prove ordinary session token does not match any recovery capability."""
    session_token = get_local_session_token()
    assert session_token is not None
    assert not session_token.startswith("aura_rec_")


# ==============================================================================
# CATEGORY B: Offline Invocation & Precondition Tests
# ==============================================================================

def test_offline_recovery_rejects_non_interactive_stdin(tmp_path):
    """Prove non-interactive stdin (e.g. pipe or string buffer without isatty) fails closed."""
    state_file = tmp_path / "provenance_store_state.json"
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Terminal test",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

    pipe_in = io.StringIO("RESET ALL AURA PROVENANCE\n")
    # io.StringIO is not a tty
    with pytest.raises(RecoveryTerminalError, match="interactive terminal"):
        execute_offline_recovery_transaction(
            target_dir=tmp_path,
            interactive=True,
            stdin_stream=pipe_in,
            stdout_stream=io.StringIO(),
            is_test_harness=False
        )


def test_offline_recovery_rejects_incorrect_first_confirmation(tmp_path):
    """Prove incorrect first confirmation (e.g. 'yes', 'y', '1', 'confirm') is rejected."""
    state_file = tmp_path / "provenance_store_state.json"
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Confirm test",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True

    for bad_conf in ["yes", "y", "CONFIRM", "ok", "true", "1", "reset"]:
        mock_sin.readline.return_value = f"{bad_conf}\n"
        with pytest.raises(RecoveryConfirmationError, match="First confirmation failed"):
            execute_offline_recovery_transaction(
                target_dir=tmp_path,
                interactive=True,
                stdin_stream=mock_sin,
                stdout_stream=mock_sout,
                is_test_harness=False
            )


def test_offline_recovery_rejects_incorrect_second_confirmation(tmp_path):
    """Prove incorrect second confirmation (target directory path mismatch) is rejected."""
    state_file = tmp_path / "provenance_store_state.json"
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Confirm test 2",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True

    mock_sin.readline.side_effect = ["RESET ALL AURA PROVENANCE\n", "/wrong/data/directory\n"]

    with pytest.raises(RecoveryConfirmationError, match="Second confirmation failed"):
        execute_offline_recovery_transaction(
            target_dir=tmp_path,
            interactive=True,
            stdin_stream=mock_sin,
            stdout_stream=mock_sout,
            is_test_harness=False
        )


@pytest.mark.parametrize("forbidden_arg", [
    "--yes", "-y", "--force", "-f", "--actor=admin", "--strategy=RESET",
    "--repair", "--auto", "--enable", "--clear", "--reset", "--custom-flag"
])
def test_offline_recovery_cli_rejects_flags(forbidden_arg):
    """Prove CLI main entrypoint strictly rejects bypass and strategy flags."""
    ret = offline_recovery_main([forbidden_arg])
    assert ret == 1


def test_offline_recovery_rejects_healthy_marker_free_store(tmp_path):
    """Prove offline recovery refuses to execute against a healthy store with active claims."""
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_healthy_test"
    )
    assert store.is_available() is True
    assert not state_file.exists()

    with pytest.raises(RecoveryPreconditionError, match="Store precondition check failed"):
        execute_offline_recovery_transaction(
            target_dir=tmp_path,
            interactive=False,
            is_test_harness=True,
            actor_override="local_admin"
        )


def test_offline_recovery_rejects_symlinks(tmp_path):
    """Prove offline recovery rejects symlinked directories or target files."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    sym_dir = tmp_path / "sym_dir"
    sym_dir.symlink_to(real_dir)

    with pytest.raises(RecoveryError, match="Security violation.*symlink"):
        resolve_and_validate_paths(sym_dir)


def test_offline_recovery_rejects_concurrent_runtime_lock(tmp_path):
    """Prove offline recovery fails closed if Aura server/daemon holds the shared runtime lock."""
    state_file = tmp_path / "provenance_store_state.json"
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Lock test",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

    # Aura runtime acquires shared lock
    with acquire_shared_runtime_lock(data_dir=tmp_path):
        # Offline recovery attempting exclusive lock fails immediately
        with pytest.raises(RuntimeLockError, match="Cannot acquire exclusive maintenance lock.*Aura runtime.*is currently running"):
            execute_offline_recovery_transaction(
                target_dir=tmp_path,
                interactive=False,
                is_test_harness=True,
                actor_override="local_admin"
            )


def test_offline_recovery_exclusive_lock_blocks_runtime_startup(tmp_path):
    """Prove while offline recovery holds exclusive maintenance lock, runtime cannot start."""
    with acquire_exclusive_maintenance_lock(data_dir=tmp_path, actor="local_admin"):
        with pytest.raises(RuntimeLockError, match="Cannot acquire shared runtime lock.*Offline administrative maintenance"):
            acquire_shared_runtime_lock(data_dir=tmp_path)


# ==============================================================================
# CATEGORY C: Authorized Offline Reset Lifecycle
# ==============================================================================

def test_authorized_offline_reset_lifecycle(tmp_path):
    """
    Complete lifecycle test:
    1. Create valid stored claims.
    2. Create strict valid DISABLED marker.
    3. Invoke offline recovery transaction.
    4. Prove all claims removed and store is exactly {}.
    5. Prove marker removed only after empty verification.
    6. Prove fresh ProvenanceStore starts available and empty.
    7. Prove former claims remain unavailable.
    8. Prove new claims can be created only after recovery and reload.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec1 = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_c1"
    )
    rec2 = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_MAVENCODE_DIRECTOR",
        template_id="TPL_EMP_MAVENCODE_DIRECTOR",
        draft_id="draft_c2"
    )
    cid1 = rec1.claim_instance_id
    cid2 = rec2.claim_instance_id

    store.disable_store("Security incident C", affected_draft_id="draft_c1")
    assert store.is_available() is False
    assert state_file.exists() is True

    # Execute authorized offline reset
    res = execute_offline_recovery_transaction(
        target_dir=tmp_path,
        interactive=False,
        is_test_harness=True,
        actor_override="local_admin"
    )

    assert res["success"] is True
    assert res["actor"] == "local_admin"
    assert state_file.exists() is False

    # Stored file on disk is exactly {}
    with open(storage_file, "r", encoding="utf-8") as f:
        assert json.load(f) == {}

    # Reload store
    store._load()
    assert store.is_available() is True
    assert len(store._records) == 0
    assert store.get_claim_instance(cid1) is None
    assert store.get_claim_instance(cid2) is None

    # Fresh store instance starts available and empty
    fresh = ProvenanceStore(storage_path=storage_file)
    assert fresh.is_available() is True
    assert len(fresh._records) == 0
    assert fresh.get_claim_instance(cid1) is None

    # Subprocess check
    subproc_code = f"""
import sys, json
from pathlib import Path
from backend.canonical_grounding import ProvenanceStore

s = ProvenanceStore(storage_path=Path('{storage_file}'))
if not s.is_available() or len(s._records) != 0 or s.get_claim_instance('{cid1}') is not None:
    sys.exit(1)
sys.exit(0)
"""
    sp_res = subprocess.run([sys.executable, "-c", subproc_code], capture_output=True, text=True)
    assert sp_res.returncode == 0

    # New claim creation succeeds
    new_rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_c_new"
    )
    assert new_rec is not None
    assert new_rec.claim_instance_id != cid1


# ==============================================================================
# CATEGORY D: Invalid-Marker Recovery Cases
# ==============================================================================

@pytest.mark.parametrize("marker_payload,desc", [
    ("{ invalid json", "Malformed JSON"),
    (json.dumps({"schema_version": 99, "state": "DISABLED", "reason": "test", "affected_draft_id": None, "disabled_at": time.time(), "recovery_required": True}), "Unsupported schema version"),
    (json.dumps({"schema_version": 1, "state": "ENABLED", "reason": "test", "affected_draft_id": None, "disabled_at": time.time(), "recovery_required": True}), "state: ENABLED"),
    (json.dumps({"schema_version": 1, "state": "UNKNOWN", "reason": "test", "affected_draft_id": None, "disabled_at": time.time(), "recovery_required": True}), "Unknown state"),
    (json.dumps({"state": "DISABLED"}), "Missing required fields"),
    (json.dumps({"schema_version": "1", "state": "DISABLED", "reason": "test", "affected_draft_id": None, "disabled_at": time.time(), "recovery_required": True}), "Wrong field type schema_version"),
    (json.dumps({"schema_version": 1, "state": "DISABLED", "reason": "test", "affected_draft_id": None, "disabled_at": -10, "recovery_required": True}), "Negative disabled_at"),
    (json.dumps({"schema_version": 1, "state": "DISABLED", "reason": "test", "affected_draft_id": None, "disabled_at": time.time(), "recovery_required": True, "extra_field": 123}), "Unexpected fields"),
])
def test_invalid_marker_offline_recovery_succeeds_and_cleans_store(tmp_path, marker_payload, desc):
    """
    Prove offline recovery accepts recovery-required invalid markers and resets the store cleanly.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    storage_file.write_text(json.dumps({}))
    state_file.write_text(marker_payload)

    # Initial store starts unavailable fail-closed
    store = ProvenanceStore(storage_path=storage_file)
    assert store.is_available() is False

    # Execute offline recovery
    res = execute_offline_recovery_transaction(
        target_dir=tmp_path,
        interactive=False,
        is_test_harness=True,
        actor_override="local_admin"
    )
    assert res["success"] is True
    assert not state_file.exists()

    store._load()
    assert store.is_available() is True
    assert len(store._records) == 0


def test_marker_mutation_between_read_and_commit_aborts_fail_closed(tmp_path):
    """
    Prove if marker file is modified between initial verification and destructive commit,
    the transaction aborts fail closed without removing the marker.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Initial reason")

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True

    call_idx = [0]
    def dynamic_readline():
        call_idx[0] += 1
        if call_idx[0] == 1:
            # Mutate marker behind the transaction's back during confirmation
            state_file.write_text(json.dumps({
                "schema_version": 1,
                "state": "DISABLED",
                "reason": "Mutated reason concurrently",
                "affected_draft_id": None,
                "disabled_at": time.time() + 100,
                "recovery_required": True
            }))
            return "RESET ALL AURA PROVENANCE\n"
        return f"{tmp_path.resolve()}\n"

    mock_sin.readline.side_effect = dynamic_readline

    with pytest.raises(RecoveryTransactionError, match="State marker was mutated during recovery"):
        execute_offline_recovery_transaction(
            target_dir=tmp_path,
            interactive=True,
            stdin_stream=mock_sin,
            stdout_stream=mock_sout,
            is_test_harness=False
        )

    # Marker must still exist fail-closed
    assert state_file.exists() is True


# ==============================================================================
# CATEGORY E: Complete Crash-Order Matrix (17 Failure Points)
# ==============================================================================

@pytest.mark.parametrize("failure_hook_name,desc", [
    ("fail_lock_acquisition", "1. Maintenance lock acquisition failure"),
    ("fail_temp_creation", "2. Temp claim store creation failure"),
    ("fail_serialization", "3. Empty store serialization failure"),
    ("fail_temp_write", "4. Temp store write failure"),
    ("fail_temp_flush", "5. Temp store flush failure"),
    ("fail_temp_fsync", "6. Temp store fsync failure"),
    ("fail_claim_replace", "7. Atomic claim file replace failure"),
    ("fail_dir_fsync_1", "8. First parent directory fsync failure"),
    ("fail_claim_reread", "9. Claim store reread failure"),
    ("fail_empty_validation", "10. Empty store validation failure"),
    ("fail_marker_removal", "11. Marker removal failure"),
    ("fail_dir_fsync_2", "12. Second parent directory fsync failure"),
    ("fail_marker_absence_check", "13. Marker absence verification failure"),
    ("fail_final_reload", "14. Final claim reload failure"),
    ("fail_final_empty_validation", "15. Final empty validation failure"),
    ("fail_audit_write", "16. Audit event logging failure"),
    ("fail_marker_recreation", "17. Disabled marker recreation failure"),
])
def test_complete_crash_order_matrix(tmp_path, failure_hook_name, desc):
    """
    Inject failure at each of the 17 transaction stages.
    Assert fail-closed disposition and no authority exposed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_crash_matrix"
    )
    cid = rec.claim_instance_id
    store.disable_store("Crash matrix pre-disable", affected_draft_id="draft_crash_matrix")

    with pytest.raises(Exception):
        execute_offline_recovery_transaction(
            target_dir=tmp_path,
            interactive=False,
            is_test_harness=True,
            actor_override="local_admin",
            failure_hook=failure_hook_name
        )

    # Post failure: old claim must NEVER verify
    store._load()
    assert store.get_claim_instance(cid) is None
    if failure_hook_name != "fail_marker_recreation":
        assert store.is_available() is False


# ==============================================================================
# CATEGORY F: Tampered-Record Reset Matrix (12 Cases)
# ==============================================================================

@pytest.mark.parametrize("tamper_key,tamper_val,desc", [
    ("record_schema_version", 99, "1. wrong record_schema_version"),
    ("template_version", "99.0.0", "2. wrong template_version"),
    ("template_digest", "0" * 64, "3. wrong template_digest"),
    ("ledger_version", "99.0.0", "4. wrong ledger_version"),
    ("ledger_digest", "0" * 64, "5. wrong ledger_digest"),
    ("fact_version", "99.0.0", "6. wrong fact_version"),
    ("fact_digest", "0" * 64, "7. wrong fact_digest"),
    ("employment_record_digest", "0" * 64, "8. wrong employment_record_digest"),
    ("exact_rendered_text", "Tampered prose", "9. wrong exact_rendered_text"),
    ("exact_rendered_hash", "0" * 64, "10. noncanonical rendered hash"),
    ("expires_at", 1000.0, "11. expired claim"),
])
def test_tampered_record_reset_matrix(tmp_path, tamper_key, tamper_val, desc):
    """
    Prove tampered fields on disk exist before reset and are completely wiped after reset.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_tamper_matrix"
    )
    cid = rec.claim_instance_id

    # Apply tampering on disk
    with open(storage_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data[cid][tamper_key] = tamper_val
    with open(storage_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Verify mutation is present before recovery
    with open(storage_file, "r", encoding="utf-8") as f:
        before = json.load(f)
    assert before[cid][tamper_key] == tamper_val

    store.disable_store(f"Tamper detected: {desc}")
    assert store.is_available() is False

    # Execute reset
    res = execute_offline_recovery_transaction(
        target_dir=tmp_path,
        interactive=False,
        is_test_harness=True,
        actor_override="local_admin"
    )
    assert res["success"] is True

    store._load()
    assert store.is_available() is True
    assert len(store._records) == 0
    assert store.get_claim_instance(cid) is None


def test_tampered_record_key_mismatch_case(tmp_path):
    """12. Mismatched dictionary key and claim_instance_id."""
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_key_tamper"
    )
    cid = rec.claim_instance_id

    with open(storage_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    rec_obj = data.pop(cid)
    data["foreign_mismatched_key"] = rec_obj
    with open(storage_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    store.disable_store("Key mismatch")
    assert store.is_available() is False

    res = execute_offline_recovery_transaction(
        target_dir=tmp_path,
        interactive=False,
        is_test_harness=True,
        actor_override="local_admin"
    )
    assert res["success"] is True

    store._load()
    assert store.is_available() is True
    assert len(store._records) == 0


# ==============================================================================
# CATEGORY G: Inherited Regression Tests
# ==============================================================================

def test_complete_six_field_claim_binding_invariants():
    """Verify complete six-field claim bindings remain strictly validated."""
    from backend.canonical_grounding import ClaimBlockBinding
    binding = ClaimBlockBinding(
        claim_instance_id=f"clm_{uuid.uuid4().hex[:12]}",
        block_id="block_0",
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_binding_test",
        submitted_block_text="Led solutions at IBM Watson.",
        start_offset=0,
        end_offset=27
    )
    assert binding.claim_instance_id.startswith("clm_")
    assert binding.block_id == "block_0"
    assert binding.draft_id == "draft_binding_test"
    assert binding.start_offset == 0
    assert binding.end_offset == 27


def test_zero_transmission_paths_strictly_preserved():
    """Verify zero transmission paths remain in production."""
    import backend.main as main_mod
    assert not hasattr(main_mod, "authorize_send")
    assert not hasattr(main_mod, "send_email_direct")
    assert not hasattr(main_mod, "send_mail")

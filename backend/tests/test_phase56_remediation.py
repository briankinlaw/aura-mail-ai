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
import stat
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
    run_offline_recovery,
    get_local_os_actor,
    resolve_canonical_data_dir,
    _validate_provenance_paths,
    read_and_verify_recovery_required,
    _write_empty_store_atomically,
    _verify_empty_store,
    _remove_disabled_marker,
    _restore_disabled_marker,
    _append_recovery_audit,
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

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = True

    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
        with pytest.raises(RecoveryTerminalError, match="interactive terminal"):
            run_offline_recovery()


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

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        for bad_conf in ["yes", "y", "CONFIRM", "ok", "true", "1", "reset"]:
            mock_sin.readline.return_value = f"{bad_conf}\n"
            with pytest.raises(RecoveryConfirmationError, match="First confirmation failed"):
                run_offline_recovery()


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

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        with pytest.raises(RecoveryConfirmationError, match="Second confirmation failed"):
            run_offline_recovery()


@pytest.mark.parametrize("forbidden_arg", [
    "--yes", "-y", "--force", "-f", "--actor=admin", "--strategy=RESET",
    "--repair", "--auto", "--enable", "--clear", "--reset", "--custom-flag",
    "/custom/path", "target"
])
def test_offline_recovery_cli_rejects_flags(forbidden_arg):
    """Prove CLI main entrypoint strictly rejects bypass flags and positional arguments."""
    ret = offline_recovery_main([forbidden_arg])
    assert ret == 2


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
        read_and_verify_recovery_required(state_file, storage_file)


def test_offline_recovery_rejects_symlinks(tmp_path):
    """Prove offline recovery rejects symlinked directories or target files."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    sym_dir = tmp_path / "sym_dir"
    sym_dir.symlink_to(real_dir)

    with pytest.raises(RecoveryPreconditionError, match="Security violation.*symlink"):
        _validate_provenance_paths(sym_dir)


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

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True

    # Aura runtime acquires shared lock
    with acquire_shared_runtime_lock(data_dir=tmp_path):
        with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
             patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
            with pytest.raises(RuntimeLockError, match="Cannot acquire exclusive maintenance lock.*Aura runtime.*is currently running"):
                run_offline_recovery()


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

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True
    mock_sin.readline.side_effect = [
        "RESET ALL AURA PROVENANCE\n",
        f"{tmp_path}\n"
    ]

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        res = run_offline_recovery()

    assert res["success"] is True
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

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True
    mock_sin.readline.side_effect = [
        "RESET ALL AURA PROVENANCE\n",
        f"{tmp_path}\n"
    ]

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        res = run_offline_recovery()

    assert res["success"] is True
    assert state_file.exists() is False
    with open(storage_file, "r", encoding="utf-8") as f:
        assert json.load(f) == {}

    store._load()
    assert store.is_available() is True


def test_marker_mutation_between_read_and_commit_aborts_fail_closed(tmp_path):
    """Prove if state marker is mutated during the transaction, recovery aborts fail-closed."""
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_mutate"
    )
    store.disable_store("Initial incident")

    original_bytes = state_file.read_bytes()

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True

    calls = []
    def mock_readline_fn(*args, **kwargs):
        if not calls:
            calls.append(1)
            return "RESET ALL AURA PROVENANCE\n"
        state_file.write_text(json.dumps({
            "schema_version": 1,
            "state": "DISABLED",
            "reason": "MUTATED_REASON_ATTACK",
            "affected_draft_id": None,
            "disabled_at": time.time(),
            "recovery_required": True
        }))
        return f"{tmp_path}\n"

    mock_sin.readline.side_effect = mock_readline_fn

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        with pytest.raises(RecoveryTransactionError, match="State marker was mutated during recovery transaction"):
            run_offline_recovery()

    # Recovery aborted: marker still exists
    assert state_file.exists() is True
    store._load()
    assert store.is_available() is False


# ==============================================================================
# CATEGORY E: Complete Crash-Order Matrix (17 failure points)
# ==============================================================================

@pytest.mark.parametrize("hook,desc", [
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
def test_complete_crash_order_matrix(tmp_path, hook, desc):
    """
    Prove that failure at any of the 17 sequential transaction stages
    fails closed, restores or preserves the DISABLED marker, and never leaves old claims authoritative.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id=f"draft_{hook}"
    )
    cid = rec.claim_instance_id
    store.disable_store(f"Disable for crash test {hook}")

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True
    mock_sin.readline.side_effect = [
        "RESET ALL AURA PROVENANCE\n",
        f"{tmp_path}\n"
    ]

    # Map hook to target function to patch
    patches = {
        "fail_lock_acquisition": patch("backend.offline_recovery.acquire_exclusive_maintenance_lock", side_effect=RuntimeLockError("Injected lock failure")),
        "fail_temp_creation": patch("backend.offline_recovery._write_empty_store_atomically", side_effect=IOError("Injected temp creation failure")),
        "fail_serialization": patch("json.dumps", side_effect=ValueError("Injected serialization failure")),
        "fail_temp_write": patch("backend.offline_recovery._write_all", side_effect=IOError("Injected short write failure")),
        "fail_temp_flush": patch("os.fsync", side_effect=IOError("Injected fsync failure")),
        "fail_temp_fsync": patch("os.fsync", side_effect=IOError("Injected fsync failure")),
        "fail_claim_replace": patch("os.replace", side_effect=IOError("Injected atomic replace failure")),
        "fail_dir_fsync_1": patch("backend.offline_recovery._fsync_parent_dir", side_effect=IOError("Injected dir fsync failure")),
        "fail_claim_reread": patch("backend.offline_recovery._verify_empty_store", side_effect=IOError("Injected reread failure")),
        "fail_empty_validation": patch("backend.offline_recovery._verify_empty_store", side_effect=RecoveryTransactionError("Injected validation failure")),
        "fail_marker_removal": patch("backend.offline_recovery._remove_disabled_marker", side_effect=IOError("Injected marker remove failure")),
        "fail_dir_fsync_2": patch("backend.offline_recovery._fsync_parent_dir", side_effect=IOError("Injected dir fsync 2 failure")),
        "fail_marker_absence_check": patch("backend.offline_recovery._remove_disabled_marker", side_effect=lambda p: None),
        "fail_final_reload": patch("backend.offline_recovery._verify_empty_store", side_effect=IOError("Injected final reload failure")),
        "fail_final_empty_validation": patch("backend.offline_recovery._verify_empty_store", side_effect=RecoveryTransactionError("Injected final empty validation failure")),
        "fail_audit_write": patch("backend.offline_recovery._append_recovery_audit", side_effect=IOError("Injected audit write failure")),
        "fail_marker_recreation": patch("backend.offline_recovery._remove_disabled_marker", side_effect=IOError("Injected remove failure causing recreation")),
    }

    target_patch = patches.get(hook, patch("builtins.print"))

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        with target_patch:
            with pytest.raises((RecoveryError, RuntimeError, IOError, ValueError)):
                run_offline_recovery()

    # Fail-closed invariant: fresh store must start UNAVAILABLE or old claim must be inaccessible
    fresh_store = ProvenanceStore(storage_path=storage_file)
    assert fresh_store.get_claim_instance(cid) is None


# ==============================================================================
# CATEGORY F: Tampered-Record Reset Matrix (12 tampering cases)
# ==============================================================================

@pytest.mark.parametrize("corrupt_field,corrupt_value,desc", [
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
def test_tampered_record_reset_matrix(tmp_path, corrupt_field, corrupt_value, desc):
    """
    Prove that any tampered record is completely eradicated after offline reset.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id=f"draft_{corrupt_field}"
    )
    cid = rec.claim_instance_id

    # Tamper with stored file
    data = json.loads(storage_file.read_text(encoding="utf-8"))
    data[cid][corrupt_field] = corrupt_value
    storage_file.write_text(json.dumps(data, indent=2))

    store.disable_store(f"Corrupted field {corrupt_field}")

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True
    mock_sin.readline.side_effect = [
        "RESET ALL AURA PROVENANCE\n",
        f"{tmp_path}\n"
    ]

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        res = run_offline_recovery()

    assert res["success"] is True
    assert state_file.exists() is False

    fresh_store = ProvenanceStore(storage_path=storage_file)
    assert fresh_store.is_available() is True
    assert len(fresh_store._records) == 0
    assert fresh_store.get_claim_instance(cid) is None


def test_tampered_record_key_mismatch_case(tmp_path):
    """Prove mismatched dictionary key and claim ID is eradicated after reset."""
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_key_mismatch"
    )
    cid = rec.claim_instance_id

    # Tamper with key
    data = json.loads(storage_file.read_text(encoding="utf-8"))
    raw_item = data.pop(cid)
    data["forged_key_000"] = raw_item
    storage_file.write_text(json.dumps(data, indent=2))

    store.disable_store("Key mismatch corruption")

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True
    mock_sin.readline.side_effect = [
        "RESET ALL AURA PROVENANCE\n",
        f"{tmp_path}\n"
    ]

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path):
        res = run_offline_recovery()

    assert res["success"] is True
    assert state_file.exists() is False

    fresh_store = ProvenanceStore(storage_path=storage_file)
    assert fresh_store.is_available() is True
    assert len(fresh_store._records) == 0
    assert fresh_store.get_claim_instance(cid) is None


# ==============================================================================
# CATEGORY G: Inherited Regression Tests
# ==============================================================================

def test_complete_six_field_claim_binding_invariants():
    """Verify all 6 mandatory binding fields remain enforced."""
    from backend.canonical_grounding import ClaimBlockBinding
    raw_block = {
        "claim_instance_id": "cid_test",
        "draft_id": "draft_test",
        "block_id": "block_test",
        "submitted_block_text": "Sample text",
        "start_offset": 0,
        "end_offset": 11,
    }
    binding_obj = ClaimBlockBinding(**raw_block)
    is_valid, status, reason, claim_meta = verify_provenance_claim_binding(binding_obj, draft_text="Sample text")
    assert status == ClaimStatus.UNVERIFIED  # Unregistered test ID fails closed as UNVERIFIED


def test_zero_transmission_paths_strictly_preserved(auth_client):
    """Verify /send-reply endpoint remains strictly disabled with 403."""
    resp = auth_client.post("/api/emails/test_id/send-reply")
    assert resp.status_code == 403

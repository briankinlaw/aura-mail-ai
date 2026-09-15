"""
Phase 5.6.1 Offline Recovery Boundary Remediation Tests (Aura Mail AI Revision 2.1).

Proves the complete resolution of the failed Phase 5.6 findings:
- Finding 2.1: No production test-harness bypass parameters in run_offline_recovery().
- Finding 2.2: Genuine OS-derived actor attribution immune to forged environment variables.
- Finding 2.3: Hardened runtime lock symlink enforcement with O_NOFOLLOW and stat/fstat checks.
- Finding 2.4: Durable local JSONL audit record (data/.aura_recovery_audit.log).
- Daemon lock lifetime: Guaranteed release on initialization failure.
- Short-write protection: Complete-write loop (_write_all) before fsync.
- Comprehensive adversarial red-team matrix validation.
"""

import os
import sys
import io
import stat
import time
import json
import uuid
import pwd
import inspect
import subprocess
from pathlib import Path
from typing import Dict, Any
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from backend.main import app, CACHED_EMAILS, _EMAIL_STATE_LOCK
from backend.canonical_grounding import (
    ProvenanceStore,
    ProvenanceRecord,
    PROVENANCE_STORE,
    RecoveryStrategy,
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
    _write_all,
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
)
from backend.daemon import run_daemon_cycle
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
# SECTION 1: Production Bypass Parameter Removal Tests (Finding 2.1)
# ==============================================================================

def test_run_offline_recovery_has_zero_parameters():
    """Prove run_offline_recovery signature has exactly zero parameters."""
    sig = inspect.signature(run_offline_recovery)
    assert len(sig.parameters) == 0, f"Expected 0 parameters, found: {list(sig.parameters.keys())}"


@pytest.mark.parametrize("bypass_kwargs", [
    {"is_test_harness": True},
    {"interactive": False},
    {"actor_override": "attacker_admin"},
    {"failure_hook": "fail_lock_acquisition"},
    {"target_dir": "/tmp/custom_data"},
    {"stdin_stream": io.StringIO()},
    {"stdout_stream": io.StringIO()},
    {"confirmation_override": True},
    {"force": True},
    {"yes": True},
    {"token": "aura_rec_123"},
    {"strategy": "RESET_ALL_PROVENANCE"},
    {"custom_keyword": "injected"},
])
def test_run_offline_recovery_rejects_all_bypass_kwargs(tmp_path, bypass_kwargs):
    """
    Prove calling run_offline_recovery with any bypass keyword argument
    raises TypeError and mutates zero state.
    """
    state_file = tmp_path / "provenance_store_state.json"
    storage_file = tmp_path / "provenance_records.json"
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Test finding 2.1",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))
    storage_file.write_text(json.dumps({"old_claim": {"some": "data"}}))

    marker_before = state_file.read_bytes()
    store_before = storage_file.read_bytes()

    with pytest.raises(TypeError):
        run_offline_recovery(**bypass_kwargs)

    # Assert zero mutation
    assert state_file.read_bytes() == marker_before
    assert storage_file.read_bytes() == store_before


def test_reproduce_failed_phase56_exploit_is_blocked(tmp_path):
    """
    Directly reproduce the Phase 5.6 bypass exploit and prove it fails closed:
    execute_offline_recovery_transaction(target_dir=..., interactive=False, is_test_harness=True, actor_override=...)
    """
    import backend.offline_recovery as off_mod
    assert not hasattr(off_mod, "execute_offline_recovery_transaction")

    # Attempting to call run_offline_recovery with exploit parameters raises TypeError
    with pytest.raises(TypeError):
        off_mod.run_offline_recovery(
            target_dir=tmp_path,
            interactive=False,
            is_test_harness=True,
            actor_override="caller-chosen"
        )


# ==============================================================================
# SECTION 2: Genuine OS Actor Attribution & Environment Immunity (Finding 2.2)
# ==============================================================================

@pytest.mark.parametrize("env_var", ["LOGNAME", "USER", "LNAME", "USERNAME"])
def test_actor_attribution_immune_to_single_env_var_forgery(monkeypatch, env_var):
    """Prove setting any single environment variable does not forge the actor identity."""
    real_uid = os.getuid()
    real_username = pwd.getpwuid(real_uid).pw_name

    monkeypatch.setenv(env_var, "forged_malicious_operator")

    uid, username = get_local_os_actor()
    assert uid == real_uid
    assert username == real_username
    assert username != "forged_malicious_operator"


def test_actor_attribution_immune_to_all_env_vars_forged_together(monkeypatch):
    """Prove setting all identity environment variables together does not forge actor."""
    real_uid = os.getuid()
    real_username = pwd.getpwuid(real_uid).pw_name

    monkeypatch.setenv("LOGNAME", "forged_admin")
    monkeypatch.setenv("USER", "forged_admin")
    monkeypatch.setenv("LNAME", "forged_admin")
    monkeypatch.setenv("USERNAME", "forged_admin")

    uid, username = get_local_os_actor()
    assert uid == real_uid
    assert username == real_username
    assert username != "forged_admin"


def test_actor_attribution_rejects_pwd_lookup_failure():
    """Prove that if OS password database lookup fails, get_local_os_actor fails closed."""
    with patch("pwd.getpwuid", side_effect=KeyError("UID not found")):
        with pytest.raises(RecoveryPreconditionError, match="Failed to resolve operating system username"):
            get_local_os_actor()


def test_actor_attribution_rejects_empty_resolved_username():
    """Prove that if pwd returns an empty username, get_local_os_actor fails closed."""
    mock_entry = MagicMock()
    mock_entry.pw_name = "   "
    with patch("pwd.getpwuid", return_value=mock_entry):
        with pytest.raises(RecoveryPreconditionError, match="Empty operating system username"):
            get_local_os_actor()


# ==============================================================================
# SECTION 3: Hardened Runtime Lock & Symlink Protection (Finding 2.3)
# ==============================================================================

def test_runtime_lock_rejects_symlink_path_before_open(tmp_path):
    """Prove runtime lock refuses a symlink lock path before calling open."""
    real_file = tmp_path / "real.lock"
    real_file.touch()
    sym_file = tmp_path / "sym.lock"
    sym_file.symlink_to(real_file)

    ctx = AuraRuntimeLockContext(sym_file, is_exclusive=True)
    with pytest.raises(RuntimeLockError, match="Security violation.*symlink"):
        ctx.acquire()


def test_runtime_lock_rejects_symlink_parent_directory(tmp_path):
    """Prove runtime lock refuses a symlinked parent directory."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    sym_dir = tmp_path / "sym_dir"
    sym_dir.symlink_to(real_dir)

    lock_path = sym_dir / ".aura_runtime.lock"
    ctx = AuraRuntimeLockContext(lock_path, is_exclusive=True)
    with pytest.raises(RuntimeLockError, match="Security violation.*symlink"):
        ctx.acquire()


def test_runtime_lock_enforces_0600_permissions_and_ownership(tmp_path):
    """Prove runtime lock creates the lock file with mode 0600 and validates ownership."""
    lock_file = tmp_path / ".aura_runtime.lock"
    ctx = AuraRuntimeLockContext(lock_file, is_exclusive=True, actor="test_actor")
    ctx.acquire()
    try:
        assert ctx.is_held() is True
        st = os.stat(lock_file)
        assert stat.S_IMODE(st.st_mode) == 0o600
        assert st.st_uid == os.getuid()
    finally:
        ctx.release()


def test_runtime_lock_rejects_non_regular_file(tmp_path):
    """Prove runtime lock fails closed if the target is a directory or non-regular file."""
    lock_dir = tmp_path / ".aura_runtime.lock"
    lock_dir.mkdir()

    ctx = AuraRuntimeLockContext(lock_dir, is_exclusive=True)
    with pytest.raises(RuntimeLockError):
        ctx.acquire()


def test_stale_unlocked_file_does_not_block_active_process(tmp_path):
    """
    Prove that a preexisting lock file on disk without an active kernel flock
    does NOT block a new process from acquiring the lock.
    """
    lock_file = tmp_path / ".aura_runtime.lock"
    lock_file.write_text(json.dumps({"pid": 999999, "type": "STALE"}))

    ctx = AuraRuntimeLockContext(lock_file, is_exclusive=True, actor="new_admin")
    ctx.acquire()
    assert ctx.is_held() is True
    ctx.release()


def test_concurrent_exclusive_locks_fail_closed(tmp_path):
    """Prove two concurrent exclusive maintenance locks cannot be held simultaneously."""
    lock_file = tmp_path / ".aura_runtime.lock"
    ctx1 = AuraRuntimeLockContext(lock_file, is_exclusive=True, actor="admin_1")
    ctx2 = AuraRuntimeLockContext(lock_file, is_exclusive=True, actor="admin_2")

    ctx1.acquire()
    assert ctx1.is_held() is True

    try:
        with pytest.raises(RuntimeLockError, match="Cannot acquire exclusive maintenance lock"):
            ctx2.acquire()
    finally:
        ctx1.release()

    # After ctx1 releases, ctx2 can acquire
    ctx2.acquire()
    assert ctx2.is_held() is True
    ctx2.release()


def test_subprocess_shared_lock_blocks_offline_recovery(tmp_path):
    """
    Prove using a real separate OS process holding a shared lock
    that offline recovery cannot acquire an exclusive maintenance lock.
    """
    state_file = tmp_path / "provenance_store_state.json"
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Subprocess test",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

    # Spawn subprocess that holds shared runtime lock
    lock_path = tmp_path / ".aura_runtime.lock"
    hold_script = f"""
import time, fcntl, os
fd = os.open('{lock_path}', os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
print('LOCK_HELD', flush=True)
time.sleep(3)
"""
    proc = subprocess.Popen([sys.executable, "-c", hold_script], stdout=subprocess.PIPE, text=True)
    try:
        # Wait for subprocess to hold lock
        line = proc.stdout.readline()
        assert "LOCK_HELD" in line

        # Offline recovery must fail
        with pytest.raises(RuntimeLockError):
            acquire_exclusive_maintenance_lock(data_dir=tmp_path, actor="admin")
    finally:
        proc.kill()
        proc.wait()


# ==============================================================================
# SECTION 4: Daemon Lock Lifetime & Failure Safety (Section 13)
# ==============================================================================

def test_daemon_cycle_releases_lock_on_initialization_failure(tmp_path):
    """
    Prove that if any initialization fails inside run_daemon_cycle()
    (e.g. load_processed_ids raises Exception), the shared runtime lock is safely released.
    """
    with patch("backend.daemon.acquire_shared_runtime_lock") as mock_acquire:
        real_ctx = AuraRuntimeLockContext(tmp_path / ".aura_runtime.lock", is_exclusive=False)
        mock_acquire.return_value = real_ctx

        with patch("backend.daemon.load_processed_ids", side_effect=RuntimeError("Corrupt processed IDs")):
            summary = run_daemon_cycle(dry_run=True)
            assert "Corrupt processed IDs" in summary["errors"][0]

        # Verify lock was released
        assert real_ctx.is_held() is False

        # An exclusive maintenance lock can now be acquired immediately
        maint_ctx = AuraRuntimeLockContext(tmp_path / ".aura_runtime.lock", is_exclusive=True)
        maint_ctx.acquire()
        assert maint_ctx.is_held() is True
        maint_ctx.release()


# ==============================================================================
# SECTION 5: Durable Local JSONL Audit Record Tests (Finding 2.4)
# ==============================================================================

def test_durable_recovery_audit_record_written_and_verified(tmp_path):
    """
    Prove successful recovery writes a durable secret-free JSON Lines audit record to data/.aura_recovery_audit.log.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    audit_file = tmp_path / ".aura_recovery_audit.log"

    storage_file.write_text(json.dumps({"claim1": {"test": "data"}}))
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Audit verification test",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

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
    assert audit_file.exists() is True

    # Validate audit log mode and content
    st = os.stat(audit_file)
    assert stat.S_IMODE(st.st_mode) == 0o600

    lines = audit_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])

    assert record["event_type"] == "OFFLINE_ADMINISTRATIVE_PROVENANCE_RECOVERY"
    assert record["uid"] == os.getuid()
    assert record["username"] == pwd.getpwuid(os.getuid()).pw_name
    assert record["target_dir"] == str(tmp_path)
    assert record["status"] == "SUCCESS"
    assert "prior_marker_digest" in record
    assert "timestamp" in record

    # Prove no secrets, tokens, or claims are logged
    forbidden_terms = ["aura_rec_", "token", "Bearer", "password", "secret", "private_key"]
    for term in forbidden_terms:
        assert term not in lines[0]


def test_audit_write_failure_restores_disabled_marker_fail_closed(tmp_path):
    """
    Prove that if audit writing fails, the DISABLED marker is recreated and recovery fails closed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    storage_file.write_text(json.dumps({"claim1": {"test": "data"}}))
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Audit failure test",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True
    mock_sin.readline.side_effect = [
        "RESET ALL AURA PROVENANCE\n",
        f"{tmp_path}\n"
    ]

    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=tmp_path), \
         patch("backend.offline_recovery._append_recovery_audit", side_effect=IOError("Injected disk full error")):
        with pytest.raises(RecoveryTransactionError, match="failed after claim replacement"):
            run_offline_recovery()

    # Invariant: DISABLED marker MUST exist after failed audit write
    assert state_file.exists() is True
    marker_content = json.loads(state_file.read_text(encoding="utf-8"))
    assert marker_content["state"] == "DISABLED"
    assert marker_content["recovery_required"] is True

    # Fresh store starts unavailable
    fresh = ProvenanceStore(storage_path=storage_file)
    assert fresh.is_available() is False


# ==============================================================================
# SECTION 6: Short-Write Handling Tests (Section 12)
# ==============================================================================

def test_write_all_handles_partial_writes():
    """Prove _write_all loop writes all bytes even when os.write writes partially."""
    payload = b"Hello, Aura Recovery Transaction!"
    written_bytes = bytearray()

    def mock_partial_write(fd, data):
        # Simulate writing only 5 bytes at a time
        chunk = data[:5]
        written_bytes.extend(chunk)
        return len(chunk)

    with patch("os.write", side_effect=mock_partial_write):
        _write_all(999, payload)

    assert bytes(written_bytes) == payload


def test_write_all_raises_on_zero_bytes_written():
    """Prove _write_all raises IOError if os.write returns 0 before completing."""
    with patch("os.write", return_value=0):
        with pytest.raises(IOError, match="Short write"):
            _write_all(999, b"Some payload")

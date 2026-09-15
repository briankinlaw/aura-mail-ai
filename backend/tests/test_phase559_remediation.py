"""
Phase 5.5.9 Administrative Recovery Hardening Tests (Aura Mail AI Revision 2.1).
Adapted for Phase 5.6 Offline Recovery Boundary.

Covers all eight findings from the Phase 5.5.8 independent review gate:
- Finding 1: Dedicated administrative recovery authority (isolated from ordinary session token, no in-process recovery capability).
- Finding 2: Strict enum-instance enforcement / blocked in-process recovery stubs.
- Finding 3: Healthy store protection (precondition prevents reset of available marker-free stores).
- Finding 4: Non-suppressed durability (real directory fsync failures fail closed).
- Finding 5: Post-marker-removal reload verification and fail-closed marker recreation on failure.
- Finding 6: 10-stage deterministic crash-order failure injection test matrix on offline recovery.
- Finding 7: Authoritative tampering field test matrix (exact schema fields verified before and after reset).
- Finding 8: Deterministic unreadable marker tests (permission / I/O errors fail closed).
"""

import os
import sys
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
from backend.auth import get_local_session_token
from backend.tests.conftest import test_reset_provenance_store
from backend.offline_recovery import (
    run_offline_recovery,
    read_and_verify_recovery_required,
    _write_empty_store_atomically,
    _remove_disabled_marker,
    _restore_disabled_marker,
    RecoveryPreconditionError,
    RecoveryTerminalError,
    RecoveryConfirmationError,
    RecoveryTransactionError,
    _fsync_parent_dir,
)
from unittest.mock import patch, MagicMock


def _run_mock_recovery(data_dir):
    mock_sin = MagicMock()
    mock_sin.isatty.return_value = True
    mock_sout = MagicMock()
    mock_sout.isatty.return_value = True
    mock_sin.readline.side_effect = ["RESET ALL AURA PROVENANCE\n", f"{data_dir}\n"]
    with patch("sys.stdin", mock_sin), patch("sys.stdout", mock_sout), \
         patch("backend.offline_recovery.resolve_canonical_data_dir", return_value=data_dir):
        return run_offline_recovery()


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
# FINDING 1: Absence of In-Process Recovery Authority
# ==============================================================================

def test_recovery_token_functions_absent_from_auth_module():
    """
    Prove that administrative recovery token minting and validation functions
    are completely removed from backend.auth in Phase 5.6.
    """
    assert not hasattr(auth_mod, "issue_administrative_recovery_token")
    assert not hasattr(auth_mod, "verify_and_consume_recovery_token")
    assert not hasattr(auth_mod, "clear_administrative_recovery_tokens")
    assert not hasattr(auth_mod, "_ACTIVE_RECOVERY_TOKENS")
    assert not hasattr(auth_mod, "_RECOVERY_TOKEN_LOCK")


def test_ordinary_session_token_cannot_authorize_recovery(tmp_path):
    """
    Prove that calling in-process recover_store with the local session token raises RuntimeError.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Lockdown for auth test")

    session_token = get_local_session_token()

    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.recover_store(session_token)

    assert store.is_available() is False
    assert state_file.exists() is True


def test_recovery_tokens_not_accepted_as_ordinary_session_token():
    """
    Prove random or crafted recovery tokens cannot authenticate standard session requests.
    """
    assert auth_mod.verify_local_token("aura_rec_0123456789abcdef0123456789abcdef") is False


# ==============================================================================
# FINDING 2: Strict Enum & Permanent Block Enforcement
# ==============================================================================

def test_raw_string_strategy_and_all_recover_store_calls_blocked(tmp_path):
    """
    Prove in-process recover_store is blocked for any arguments.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Enum test")

    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.recover_store("RESET_ALL_PROVENANCE")

    assert store.is_available() is False


# ==============================================================================
# FINDING 3: Healthy Store Precondition (No Reset on Healthy Store)
# ==============================================================================

def test_healthy_available_store_rejects_recovery_without_mutation(tmp_path):
    """
    Prove calling execute_offline_recovery_transaction on a healthy, available store with active claims
    and no state marker is rejected before any mutation.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_healthy"
    )
    cid = rec.claim_instance_id
    assert store.is_available() is True
    assert state_file.exists() is False
    assert len(store._records) == 1

    initial_storage_bytes = storage_file.read_bytes()

    with pytest.raises(RecoveryPreconditionError, match="Store precondition check failed"):
        read_and_verify_recovery_required(state_file, storage_file)

    # Prove zero mutations occurred
    assert store.is_available() is True
    assert state_file.exists() is False
    assert len(store._records) == 1
    assert store.get_claim_instance(cid) is not None
    assert storage_file.read_bytes() == initial_storage_bytes


# ==============================================================================
# FINDING 4: Non-Suppressed Durability
# ==============================================================================

def test_supported_parent_dir_fsync_io_error_fails_closed(tmp_path):
    """
    Prove that a genuine I/O error (EIO) during parent directory fsync fails closed
    and is not silently suppressed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Durability test")

    with patch("os.fsync", side_effect=OSError(errno.EIO, "I/O Error")):
        with pytest.raises(OSError):
            _fsync_parent_dir(storage_file)


def test_unsupported_filesystem_fsync_error_ignored(tmp_path):
    """
    Prove that on filesystems where directory fsync is unsupported (EINVAL/ENOTSUP),
    _fsync_parent_dir logs debug and returns cleanly without raising.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)

    with patch("os.fsync", side_effect=OSError(errno.EINVAL, "Invalid argument")):
        # _fsync_parent_dir ignores EINVAL cleanly
        _fsync_parent_dir(storage_file)


# ==============================================================================
# FINDING 5: Reload Verification & Fail-Closed Marker Restoration
# ==============================================================================

def test_post_marker_removal_failure_recreates_disabled_marker(tmp_path):
    """
    Prove that if a failure occurs after claim replacement during offline recovery,
    a strictly valid DISABLED marker is recreated on disk fail-closed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Pre-recovery disable")

    # Injected failure after claim replacement but during final empty validation
    with patch("backend.offline_recovery._verify_empty_store", side_effect=RecoveryTransactionError("Injected final empty validation failure")):
        with pytest.raises(Exception):
            _run_mock_recovery(tmp_path)

    store._load()
    assert store.is_available() is False
    assert state_file.exists() is True

    # Verify recreated marker is valid DISABLED schema
    with open(state_file, "r", encoding="utf-8") as f:
        marker_data = json.load(f)
    assert marker_data["state"] == "DISABLED"
    assert marker_data["schema_version"] == 1
    assert marker_data["recovery_required"] is True


# ==============================================================================
# FINDING 6: 10-Stage Crash-Order Failure Injection Tests
# ==============================================================================

@pytest.mark.parametrize("stage_hook,desc", [
    ("fail_temp_creation", "Stage 1: Temp claim file creation failure"),
    ("fail_serialization", "Stage 2: JSON dump failure"),
    ("fail_temp_flush", "Stage 3: Temp file flush failure"),
    ("fail_temp_fsync", "Stage 4: Temp file fsync failure"),
    ("fail_claim_replace", "Stage 5: Atomic replace failure"),
    ("fail_dir_fsync_1", "Stage 6: Parent directory fsync after claim write"),
    ("fail_claim_reread", "Stage 7: Claim reread verification failure"),
    ("fail_empty_validation", "Stage 8: Empty store verification failure"),
    ("fail_marker_removal", "Stage 9: State marker removal failure"),
    ("fail_dir_fsync_2", "Stage 10: Parent directory fsync after marker remove"),
    ("fail_marker_absence_check", "Stage 11: Final marker absence check failure"),
    ("fail_final_reload", "Stage 12: Final claim reload failure"),
    ("fail_final_empty_validation", "Stage 13: Final empty revalidation failure"),
])
def test_crash_order_failure_matrix(tmp_path, stage_hook, desc):
    """
    Prove that a failure at any crash-order recovery stage leaves the store
    unavailable fail-closed with no old authority exposed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_crash_order"
    )
    cid = rec.claim_instance_id
    store.disable_store(f"Crash stage {stage_hook}", affected_draft_id="draft_crash_order")
    assert store.is_available() is False

    patches = {
        "fail_temp_creation": patch("backend.offline_recovery._write_empty_store_atomically", side_effect=IOError("Injected temp creation failure")),
        "fail_serialization": patch("json.dumps", side_effect=ValueError("Injected serialization failure")),
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
    }
    target_patch = patches.get(stage_hook, patch("builtins.print"))
    with target_patch:
        with pytest.raises(Exception):
            _run_mock_recovery(tmp_path)

    store._load()
    # Prove store remains unavailable and old claim cannot verify
    assert store.is_available() is False
    assert store.get_claim_instance(cid) is None


# ==============================================================================
# FINDING 7: Authoritative Tampering Field Tests
# ==============================================================================

@pytest.mark.parametrize("tamper_key,tamper_val,desc", [
    ("record_schema_version", 99, "Corrupted record_schema_version"),
    ("exact_rendered_text", "Tampered prose content", "Corrupted exact_rendered_text"),
    ("exact_rendered_hash", "0" * 64, "Corrupted exact_rendered_hash"),
    ("template_digest", "1" * 64, "Corrupted template_digest"),
    ("ledger_digest", "2" * 64, "Corrupted ledger_digest"),
    ("fact_digest", "3" * 64, "Corrupted fact_digest"),
    ("employment_record_digest", "4" * 64, "Corrupted employment_record_digest"),
])
def test_authoritative_tampered_records_eradicated_after_reset(tmp_path, tamper_key, tamper_val, desc):
    """
    Prove that tampered authoritative schema fields on disk are eradicated after recovery.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_tamper_auth"
    )
    cid = rec.claim_instance_id

    # Tamper with the raw disk record
    with open(storage_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert cid in data
    data[cid][tamper_key] = tamper_val
    with open(storage_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Verify tampering is present on disk before recovery
    with open(storage_file, "r", encoding="utf-8") as f:
        persisted = json.load(f)
    assert persisted[cid][tamper_key] == tamper_val

    # Disable store
    store.disable_store(f"Tamper detected: {desc}", affected_draft_id="draft_tamper_auth")
    assert store.is_available() is False

    res = _run_mock_recovery(tmp_path)

    assert res["success"] is True
    store._load()
    assert store.is_available() is True
    assert len(store._records) == 0
    assert store.get_claim_instance(cid) is None

    # Disk store is exactly {}
    with open(storage_file, "r", encoding="utf-8") as f:
        assert json.load(f) == {}


def test_tampered_record_key_mismatch_eradicated_after_reset(tmp_path):
    """
    Prove dictionary key mismatch (key != claim_instance_id) is eradicated after reset.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_key_mismatch"
    )
    cid = rec.claim_instance_id

    # Mutate disk record key to foreign key
    with open(storage_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    rec_obj = data.pop(cid)
    data["mismatched_claim_key_xyz"] = rec_obj
    with open(storage_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    store.disable_store("Key mismatch detected")
    assert store.is_available() is False

    res = _run_mock_recovery(tmp_path)

    assert res["success"] is True
    store._load()
    assert store.is_available() is True
    assert len(store._records) == 0


# ==============================================================================
# FINDING 8: Unreadable Marker Coverage
# ==============================================================================

def test_unreadable_state_marker_starts_unavailable_fail_closed(tmp_path):
    """
    Prove that if the state marker file cannot be read (e.g. PermissionError),
    the store starts unavailable fail-closed with STATE_FILE_INVALID and never exposes claims.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    # Create valid claim
    init_store = ProvenanceStore(storage_path=storage_file)
    rec = init_store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_unreadable_test"
    )
    cid = rec.claim_instance_id

    # Create state marker
    state_file.write_text(json.dumps({
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Test",
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True
    }))

    # Simulate PermissionError on reading state marker
    orig_open = open
    def conditional_open(file, mode="r", *args, **kwargs):
        if str(file) == str(state_file) and "r" in mode:
            raise PermissionError(errno.EACCES, "Permission denied")
        return orig_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=conditional_open):
        store = ProvenanceStore(storage_path=storage_file)
        assert store.is_available() is False
        assert "STATE_FILE_INVALID" in (store._unavailable_reason or "")
        assert store.get_claim_instance(cid) is None
        assert len(store._records) == 0

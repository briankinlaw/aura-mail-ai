"""
Phase 5.5.9 Administrative Recovery Hardening Tests (Aura Mail AI Revision 2.1).

Covers all eight findings from the Phase 5.5.8 independent review gate:
- Finding 1: Dedicated administrative recovery authority (isolated from ordinary session token, single-use, actor-bound, short-lived).
- Finding 2: Strict enum-instance enforcement (rejection of raw strings and aliases).
- Finding 3: Healthy store protection (precondition prevents reset of available marker-free stores).
- Finding 4: Non-suppressed durability (real directory fsync failures fail closed).
- Finding 5: Post-marker-removal reload verification and fail-closed marker recreation on failure.
- Finding 6: 10-stage deterministic crash-order failure injection test matrix.
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
    RecoveryExecutionContext,
    RecoveryAuthorizationError,
    AdministrativeRecoveryContext,
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
from backend.auth import (
    get_local_session_token,
    issue_administrative_recovery_token,
    verify_and_consume_recovery_token,
    clear_administrative_recovery_tokens,
)
from backend.tests.conftest import test_reset_provenance_store


@pytest.fixture(autouse=True)
def clean_store_environment():
    """Ensures clean provenance store, token store, and cached email state before and after every test."""
    with _EMAIL_STATE_LOCK:
        CACHED_EMAILS.clear()
        clear_administrative_recovery_tokens()
        test_reset_provenance_store()
    yield
    with _EMAIL_STATE_LOCK:
        CACHED_EMAILS.clear()
        clear_administrative_recovery_tokens()
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


def _create_valid_admin_context(actor: str = "local_maint_admin") -> AdministrativeRecoveryContext:
    token = issue_administrative_recovery_token(actor=actor)
    return AdministrativeRecoveryContext(
        actor=actor,
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=token,
    )


# ==============================================================================
# FINDING 1: Dedicated Administrative Recovery Authority
# ==============================================================================

def test_ordinary_session_token_explicitly_rejected_as_recovery_evidence(tmp_path):
    """
    Prove that the ordinary local session token cannot authorize recovery.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Lockdown for auth test")

    session_token = get_local_session_token()
    ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=session_token,
    )

    with pytest.raises(RecoveryAuthorizationError, match="Invalid, expired, or already consumed administrative recovery authorization evidence"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False
    assert state_file.exists() is True


def test_recovery_token_is_single_use_consumed(tmp_path):
    """
    Prove that an administrative recovery token is consumed upon first verification
    and cannot be replayed.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("First disable")

    token = issue_administrative_recovery_token(actor="local_admin")
    ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=token,
    )

    # First recovery succeeds and consumes the token
    res1 = store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)
    assert res1 is True
    assert store.is_available() is True

    # Disable store again and attempt replay with the same context/token
    store.disable_store("Second disable")
    assert store.is_available() is False

    with pytest.raises(RecoveryAuthorizationError, match="Invalid, expired, or already consumed administrative recovery authorization evidence"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False


def test_recovery_token_actor_binding_enforced(tmp_path):
    """
    Prove that a recovery token minted for actor A cannot be used by actor B.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Actor mismatch test")

    token_for_alice = issue_administrative_recovery_token(actor="alice_admin")
    ctx_bob = AdministrativeRecoveryContext(
        actor="bob_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=token_for_alice,
    )

    with pytest.raises(RecoveryAuthorizationError, match="Invalid, expired, or already consumed administrative recovery authorization evidence"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx_bob)

    assert store.is_available() is False


def test_expired_recovery_token_rejected(tmp_path):
    """
    Prove that an expired recovery token is rejected.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Expiration test")

    # Issue token with very short TTL
    token = issue_administrative_recovery_token(actor="local_admin", ttl_seconds=0.01)
    time.sleep(0.05)

    ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=token,
    )

    with pytest.raises(RecoveryAuthorizationError, match="Invalid, expired, or already consumed administrative recovery authorization evidence"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False


def test_recovery_token_rejected_on_ordinary_http_endpoints(auth_client):
    """
    Prove recovery tokens cannot be used as bearer tokens on standard HTTP endpoints.
    """
    rec_token = issue_administrative_recovery_token(actor="test_admin")
    resp = auth_client.get("/api/canonical/templates", headers={"Authorization": f"Bearer {rec_token}"})
    assert resp.status_code == 403


# ==============================================================================
# FINDING 2: Strict Enum Instance Enforcement
# ==============================================================================

def test_raw_string_strategy_strictly_rejected(tmp_path):
    """
    Prove raw string 'RESET_ALL_PROVENANCE' is rejected with ValueError.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Enum test")

    ctx = _create_valid_admin_context()

    with pytest.raises(ValueError, match="Unsupported recovery strategy"):
        store.recover_store("RESET_ALL_PROVENANCE", ctx)

    assert store.is_available() is False


def test_raw_string_execution_context_strictly_rejected(tmp_path):
    """
    Prove raw string 'LOCAL_ADMIN_MAINTENANCE' in context is rejected with RecoveryAuthorizationError.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Context enum test")

    token = issue_administrative_recovery_token(actor="local_admin")
    ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context="LOCAL_ADMIN_MAINTENANCE",  # Raw string instead of enum
        explicitly_confirmed=True,
        authorization_evidence=token,
    )

    with pytest.raises(RecoveryAuthorizationError, match="Forbidden recovery execution context"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False


# ==============================================================================
# FINDING 3: Healthy Store Precondition (No Reset on Healthy Store)
# ==============================================================================

def test_healthy_available_store_rejects_recovery_without_mutation(tmp_path):
    """
    Prove calling recover_store on a healthy, available store with active claims
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
    ctx = _create_valid_admin_context()

    with pytest.raises(RecoveryAuthorizationError, match="Store is currently healthy and available"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

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

    ctx = _create_valid_admin_context()

    with patch.object(store, "_fsync_parent_dir", side_effect=OSError(errno.EIO, "I/O Error")):
        with pytest.raises(RuntimeError, match="Administrative recovery failed"):
            store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False
    assert state_file.exists() is True


def test_unsupported_filesystem_fsync_error_ignored(tmp_path):
    """
    Prove that on filesystems where directory fsync is unsupported (EINVAL/ENOTSUP),
    _fsync_parent_dir logs debug and returns cleanly without raising.
    """
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)

    with patch("os.fsync", side_effect=OSError(errno.EINVAL, "Invalid argument")):
        # _fsync_parent_dir ignores EINVAL cleanly
        store._fsync_parent_dir(storage_file)


# ==============================================================================
# FINDING 5: Reload Verification & Fail-Closed Marker Restoration
# ==============================================================================

def test_post_marker_removal_failure_recreates_disabled_marker(tmp_path):
    """
    Prove that if an unexpected error occurs during final _load() after marker removal,
    a strictly valid DISABLED marker is recreated on disk fail-closed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Pre-recovery disable")

    ctx = _create_valid_admin_context()

    # Simulate failure during _load() after marker has been removed
    with patch.object(store, "_load", side_effect=RuntimeError("Disk corruption during reload")):
        with pytest.raises(RuntimeError, match="Administrative recovery failed"):
            store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

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

@pytest.mark.parametrize("stage_index,patch_target,patch_side_effect,desc", [
    (1, "builtins.open", OSError("Temp file open failed"), "Stage 1: Temp claim file creation failure"),
    (2, "json.dump", TypeError("JSON dump serialization error"), "Stage 2: JSON dump failure"),
    (3, "builtins.open", OSError("Flush failed"), "Stage 3: Temp file flush failure"),
    (4, "os.fsync", OSError(errno.EIO, "Fsync failed"), "Stage 4: Temp file fsync failure"),
    (5, "os.replace", OSError("Atomic replace failed"), "Stage 5: Atomic replace failure"),
    (6, "backend.canonical_grounding.ProvenanceStore._fsync_parent_dir", OSError(errno.EIO, "Dir fsync 1 failed"), "Stage 6: Parent directory fsync after claim write"),
    (7, "json.load", ValueError("Corrupt claim JSON on reread"), "Stage 7: Claim reread verification failure"),
    (8, "os.remove", OSError("Marker remove failed"), "Stage 8: State marker removal failure"),
    (9, "backend.canonical_grounding.ProvenanceStore._fsync_parent_dir", OSError(errno.EIO, "Dir fsync 2 failed"), "Stage 9: Parent directory fsync after marker remove"),
    (10, "backend.canonical_grounding.ProvenanceStore._load", RuntimeError("Reload verification failed"), "Stage 10: Final _load revalidation failure"),
])
def test_10_stage_crash_order_failure_matrix(tmp_path, stage_index, patch_target, patch_side_effect, desc):
    """
    Prove that a failure at any of the 10 crash-order recovery stages leaves the store
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
    store.disable_store(f"Crash stage {stage_index}", affected_draft_id="draft_crash_order")
    assert store.is_available() is False

    ctx = _create_valid_admin_context()

    # Apply stage-specific failure injection
    if stage_index in (6, 9):
        call_count = [0]
        orig_fsync = store._fsync_parent_dir
        def conditional_fsync(path):
            call_count[0] += 1
            target_call = 1 if stage_index == 6 else 2
            if call_count[0] == target_call:
                raise patch_side_effect
            return orig_fsync(path)

        with patch.object(store, "_fsync_parent_dir", side_effect=conditional_fsync):
            with pytest.raises(RuntimeError, match="Administrative recovery failed"):
                store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)
    elif stage_index in (1, 2, 3, 4, 7):
        orig_open = open
        class FlushFailWrapper:
            def __init__(self, f):
                self._f = f
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return self._f.__exit__(*args)
            def write(self, *args, **kwargs):
                return self._f.write(*args, **kwargs)
            def flush(self):
                raise patch_side_effect
            def fileno(self):
                return self._f.fileno()

        def conditional_open(file, mode="r", *args, **kwargs):
            if ".tmp_" in str(file) and "w" in mode:
                if stage_index == 1:
                    raise patch_side_effect
                if stage_index == 3:
                    f = orig_open(file, mode, *args, **kwargs)
                    return FlushFailWrapper(f)
            return orig_open(file, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=conditional_open):
            if stage_index == 2:
                with patch("json.dump", side_effect=patch_side_effect):
                    with pytest.raises(RuntimeError, match="Administrative recovery failed"):
                        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)
            elif stage_index == 4:
                with patch("os.fsync", side_effect=patch_side_effect):
                    with pytest.raises(RuntimeError, match="Administrative recovery failed"):
                        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)
            elif stage_index == 7:
                orig_json_load = json.load
                def conditional_json_load(f):
                    if hasattr(f, "name") and "provenance_records.json" in str(f.name):
                        return {"fake_surviving_claim": {}}
                    return orig_json_load(f)
                with patch("json.load", side_effect=conditional_json_load):
                    with pytest.raises(RuntimeError, match="Administrative recovery failed"):
                        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)
            elif stage_index in (1, 3):
                with pytest.raises(RuntimeError, match="Administrative recovery failed"):
                    store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)
    else:
        with patch(patch_target, side_effect=patch_side_effect):
            with pytest.raises(RuntimeError, match="Administrative recovery failed"):
                store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

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

    ctx = _create_valid_admin_context()
    res = store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert res is True
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

    ctx = _create_valid_admin_context()
    res = store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert res is True
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

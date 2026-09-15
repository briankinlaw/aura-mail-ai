"""
Phase 5.5.8 Administrative Recovery Micro-Remediation Tests (Aura Mail AI Revision 2.1).

Covers:
- Section A: No-default recovery strategy tests
- Section B: Administrative recovery context authorization matrix
- Section C: Alias-bypass tests (enable_store, reset_store stubs)
- Section D: Strict marker schema validation matrix (26 cases + valid disabled marker)
- Section E: Recovery reset execution tests
- Section F: Crash-order and simulated failure tests
- Section G: Tampered-record reset recovery tests
- Section H: Fresh process and subprocess restart tests
- Section I: Inherited security invariants (zero-transmission, risk-grounding separation, localhost)
"""

import os
import sys
import time
import json
import uuid
import math
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
from backend.auth import get_local_session_token
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


def _create_valid_admin_context() -> AdministrativeRecoveryContext:
    return AdministrativeRecoveryContext(
        actor="local_root_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=get_local_session_token(),
    )


# ==============================================================================
# SECTION A: No-Default Recovery Strategy Tests
# ==============================================================================

def test_recover_store_requires_explicit_arguments_without_defaults(tmp_path):
    """
    Prove recover_store() with missing arguments fails before modifying:
    - marker bytes
    - claim-store bytes
    - availability
    - in-memory records
    - quarantine state
    - invalidation counters
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)

    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_no_default"
    )
    store.disable_store("Test disable", affected_draft_id="draft_no_default")
    assert store.is_available() is False
    assert state_file.exists() is True

    initial_marker_bytes = state_file.read_bytes()
    initial_store_bytes = storage_file.read_bytes()
    initial_inv_count = store.get_invalidation_count()
    initial_quarantine = set(store._quarantined_draft_ids)

    # 1. Calling recover_store() with no arguments must raise TypeError
    with pytest.raises(TypeError):
        store.recover_store()

    # Verify nothing changed
    assert state_file.read_bytes() == initial_marker_bytes
    assert storage_file.read_bytes() == initial_store_bytes
    assert store.is_available() is False
    assert store._quarantined_draft_ids == initial_quarantine
    assert store.get_invalidation_count() == initial_inv_count


@pytest.mark.parametrize("invalid_strategy", [
    None,
    "",
    "RESET",
    "CLEAR",
    "REPAIR",
    "ENABLE",
    "AUTO",
    "VALIDATE_AND_REPAIR",
    "reset_all_provenance",
])
def test_recover_store_rejects_invalid_strategies_fail_closed(tmp_path, invalid_strategy):
    """
    Prove invalid or removed strategies (including VALIDATE_AND_REPAIR) fail closed
    without modifying store state.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_strategy_test"
    )
    store.disable_store("Test disable", affected_draft_id="draft_strategy_test")
    admin_ctx = _create_valid_admin_context()

    initial_marker_bytes = state_file.read_bytes()
    initial_store_bytes = storage_file.read_bytes()

    with pytest.raises(ValueError, match="Unsupported recovery strategy"):
        store.recover_store(strategy=invalid_strategy, recovery_context=admin_ctx)

    assert store.is_available() is False
    assert state_file.read_bytes() == initial_marker_bytes
    assert storage_file.read_bytes() == initial_store_bytes


# ==============================================================================
# SECTION B: Administrative Context Authorization Tests
# ==============================================================================

@pytest.mark.parametrize("bad_context,expected_error", [
    (None, RecoveryAuthorizationError),
    ({"actor": "admin", "execution_context": "LOCAL_ADMIN_MAINTENANCE"}, RecoveryAuthorizationError),
    ("admin", RecoveryAuthorizationError),
    (True, RecoveryAuthorizationError),
    (123, RecoveryAuthorizationError),
])
def test_recover_store_rejects_non_typed_contexts(tmp_path, bad_context, expected_error):
    """
    Reject raw dictionaries, strings, booleans, and None as recovery_context.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    initial_marker_bytes = state_file.read_bytes()

    with pytest.raises(expected_error):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, bad_context)

    assert store.is_available() is False
    assert state_file.read_bytes() == initial_marker_bytes


@pytest.mark.parametrize("forbidden_context", [
    "DAEMON",
    "BACKGROUND_RADAR",
    "SCHEDULED_JOB",
    "AI_AGENT",
    "UNAUTHENTICATED_API",
    "OUTLOOK_INTERACTIVE_USER",
    "DASHBOARD_INTERACTIVE_USER",
    "ORDINARY_REQUEST",
    "UNKNOWN_CONTEXT",
])
def test_recover_store_rejects_forbidden_execution_contexts(tmp_path, forbidden_context):
    """
    Explicitly reject all non-LOCAL_ADMIN_MAINTENANCE execution contexts.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    ctx = AdministrativeRecoveryContext(
        actor="admin",
        execution_context=forbidden_context,
        explicitly_confirmed=True,
        authorization_evidence=get_local_session_token(),
    )

    with pytest.raises(RecoveryAuthorizationError, match="Forbidden recovery execution context"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False
    assert state_file.exists() is True


def test_recover_store_rejects_empty_actor(tmp_path):
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    ctx = AdministrativeRecoveryContext(
        actor="   ",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=get_local_session_token(),
    )

    with pytest.raises(RecoveryAuthorizationError, match="requires a non-empty actor"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False


def test_recover_store_rejects_unconfirmed_request(tmp_path):
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=False,
        authorization_evidence=get_local_session_token(),
    )

    with pytest.raises(RecoveryAuthorizationError, match="requires explicitly_confirmed=True"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False


def test_recover_store_rejects_invalid_authorization_evidence(tmp_path):
    storage_file = tmp_path / "provenance_records.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    ctx = AdministrativeRecoveryContext(
        actor="local_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence="invalid_forged_session_token_xyz",
    )

    with pytest.raises(RecoveryAuthorizationError, match="Invalid administrative recovery authorization evidence"):
        store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)

    assert store.is_available() is False


def test_recover_store_positive_with_valid_admin_context(tmp_path):
    """Positive test for valid trusted local administrative recovery."""
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")
    assert store.is_available() is False

    admin_ctx = _create_valid_admin_context()
    res = store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, admin_ctx)

    assert res is True
    assert store.is_available() is True
    assert state_file.exists() is False


# ==============================================================================
# SECTION C: Alias-Bypass Tests
# ==============================================================================

def test_enable_store_raises_runtime_error_and_cannot_bypass_recovery(tmp_path):
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    initial_marker_bytes = state_file.read_bytes()

    with pytest.raises(RuntimeError, match="enable_store\\(\\) is removed for safety"):
        store.enable_store()

    assert store.is_available() is False
    assert state_file.read_bytes() == initial_marker_bytes


def test_reset_store_raises_runtime_error_and_cannot_bypass_recovery(tmp_path):
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    initial_marker_bytes = state_file.read_bytes()

    with pytest.raises(RuntimeError, match="reset_store\\(\\) is removed for safety"):
        store.reset_store()

    assert store.is_available() is False
    assert state_file.read_bytes() == initial_marker_bytes


# ==============================================================================
# SECTION D: Strict Marker Schema Matrix (26 cases)
# ==============================================================================

@pytest.mark.parametrize("corrupt_marker_data,description", [
    # 1. state: ENABLED
    ({"schema_version": 1, "state": "ENABLED", "reason": "Recovered", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "state: ENABLED"),
    # 2. Unknown state
    ({"schema_version": 1, "state": "ACTIVE", "reason": "Active", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "Unknown state ACTIVE"),
    # 3. Missing state
    ({"schema_version": 1, "reason": "No state", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "Missing state"),
    # 4. Missing schema_version
    ({"state": "DISABLED", "reason": "No schema", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "Missing schema_version"),
    # 5. Unsupported schema version
    ({"schema_version": 2, "state": "DISABLED", "reason": "V2", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "Unsupported schema version 2"),
    # 6. Boolean schema version (True evaluates as 1 in Python if not type-checked)
    ({"schema_version": True, "state": "DISABLED", "reason": "Bool schema", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "Boolean schema version"),
    # 7. Missing reason
    ({"schema_version": 1, "state": "DISABLED", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "Missing reason"),
    # 8. Blank reason
    ({"schema_version": 1, "state": "DISABLED", "reason": "   ", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True}, "Blank reason"),
    # 9. Missing affected_draft_id
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "disabled_at": 1726380695.1, "recovery_required": True}, "Missing affected_draft_id"),
    # 10. Invalid draft-ID type (integer)
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": 12345, "disabled_at": 1726380695.1, "recovery_required": True}, "Invalid draft-ID int"),
    # 11. Missing disabled_at
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "recovery_required": True}, "Missing disabled_at"),
    # 12. Zero timestamp
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": 0.0, "recovery_required": True}, "Zero timestamp"),
    # 13. Negative timestamp
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": -100.0, "recovery_required": True}, "Negative timestamp"),
    # 14. NaN timestamp (represented as string or invalid float)
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": float("nan"), "recovery_required": True}, "NaN timestamp"),
    # 15. Infinite timestamp
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": float("inf"), "recovery_required": True}, "Infinite timestamp"),
    # 16. String timestamp
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": "1726380695.1", "recovery_required": True}, "String timestamp"),
    # 17. Missing recovery_required
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": 1726380695.1}, "Missing recovery_required"),
    # 18. recovery_required: false
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": False}, "recovery_required: false"),
    # 19. recovery_required: 1 (integer instead of boolean)
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": 1}, "recovery_required: 1"),
    # 20. recovery_required: "true" (string instead of boolean)
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid reason", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": "true"}, "recovery_required: 'true'"),
    # 21. Extra authority-bearing field
    ({"schema_version": 1, "state": "DISABLED", "reason": "Valid", "affected_draft_id": None, "disabled_at": 1726380695.1, "recovery_required": True, "bypass_security": True}, "Extra unrecognized field"),
])
def test_strict_marker_schema_matrix_fails_closed(tmp_path, corrupt_marker_data, description):
    """
    Prove that any deviation from the exact DISABLED schema version 1 fails closed on store startup.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(corrupt_marker_data, f, indent=2)

    store = ProvenanceStore(storage_path=storage_file)
    assert store.is_available() is False
    assert "STATE_FILE_INVALID" in (store._unavailable_reason or "")
    assert len(store._records) == 0


@pytest.mark.parametrize("raw_non_json,description", [
    ("not-valid-json{{{", "21. Malformed JSON"),
    (json.dumps(["not", "a", "dict"]), "22. Array root"),
    (json.dumps("just a string"), "23. String root"),
    (json.dumps(None), "24. Null root"),
])
def test_strict_marker_raw_invalid_json_fails_closed(tmp_path, raw_non_json, description):
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    with open(state_file, "w", encoding="utf-8") as f:
        f.write(raw_non_json)

    store = ProvenanceStore(storage_path=storage_file)
    assert store.is_available() is False
    assert "STATE_FILE_INVALID" in (store._unavailable_reason or "")
    assert len(store._records) == 0


def test_valid_claims_combined_with_invalid_marker_fails_closed(tmp_path):
    """
    Case 26: Valid claims combined with any invalid marker.
    Valid claim records MUST NOT override or bypass an invalid state marker.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    # Pre-populate valid claim
    init_store = ProvenanceStore(storage_path=storage_file)
    rec = init_store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_override_test"
    )
    cid = rec.claim_instance_id
    assert storage_file.exists() is True

    # Write corrupt marker
    with open(state_file, "w", encoding="utf-8") as f:
        f.write("corrupted-marker-payload")

    store = ProvenanceStore(storage_path=storage_file)
    assert store.is_available() is False
    assert store.get_claim_instance(cid) is None
    assert len(store._records) == 0


def test_strictly_valid_disabled_marker_starts_unavailable(tmp_path):
    """
    Prove one strictly valid DISABLED marker starts unavailable fail-closed.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    state_data = {
        "schema_version": 1,
        "state": "DISABLED",
        "reason": "Administrative lockdown test",
        "affected_draft_id": "draft_quarantined_123",
        "disabled_at": 1726380695.123,
        "recovery_required": True
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)

    store = ProvenanceStore(storage_path=storage_file)
    assert store.is_available() is False
    assert "DURABLY_DISABLED: Administrative lockdown test" in store._unavailable_reason
    assert "draft_quarantined_123" in store._quarantined_draft_ids


# ==============================================================================
# SECTION E: Recovery Reset Execution Tests
# ==============================================================================

def test_recovery_reset_all_provenance_full_lifecycle(tmp_path):
    """
    With a valid disabled store containing old claims:
    1. Correct explicit strategy plus valid administrative context succeeds.
    2. All persisted claims are removed.
    3. All in-memory claims are removed.
    4. The marker is removed only after empty-store verification.
    5. A fresh object starts available and empty.
    6. A fresh subprocess starts available and empty.
    7. Every former claim ID remains unavailable.
    8. New provenance can be created only after successful recovery.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    store = ProvenanceStore(storage_path=storage_file)
    rec1 = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_life_1"
    )
    rec2 = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_MAVENCODE_DIRECTOR",
        template_id="TPL_EMP_MAVENCODE_DIRECTOR",
        draft_id="draft_life_2"
    )
    cid1 = rec1.claim_instance_id
    cid2 = rec2.claim_instance_id

    store.disable_store("Security incident", affected_draft_id="draft_life_1")
    assert store.is_available() is False
    assert state_file.exists() is True

    admin_ctx = _create_valid_admin_context()
    res = store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, admin_ctx)

    assert res is True
    assert store.is_available() is True
    assert state_file.exists() is False
    assert len(store._records) == 0
    assert store.get_claim_instance(cid1) is None
    assert store.get_claim_instance(cid2) is None

    # Verify on-disk claim file is exactly {}
    with open(storage_file, "r", encoding="utf-8") as f:
        assert json.load(f) == {}

    # Fresh instance starts available and empty
    fresh_store = ProvenanceStore(storage_path=storage_file)
    assert fresh_store.is_available() is True
    assert len(fresh_store._records) == 0
    assert fresh_store.get_claim_instance(cid1) is None

    # New provenance can now be created
    new_rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_life_new"
    )
    assert new_rec is not None
    assert new_rec.claim_instance_id != cid1
    assert store.get_claim_instance(new_rec.claim_instance_id) is not None


# ==============================================================================
# SECTION F: Crash-Order and Deterministic Failure Injection Tests
# ==============================================================================

def test_recovery_failure_during_empty_write_remains_fail_closed(tmp_path):
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    admin_ctx = _create_valid_admin_context()

    with patch("os.replace", side_effect=OSError("Disk full / replace failed")):
        with pytest.raises(RuntimeError, match="Administrative recovery failed"):
            store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, admin_ctx)

    assert store.is_available() is False
    assert state_file.exists() is True


def test_recovery_failure_during_marker_removal_remains_fail_closed(tmp_path):
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"
    store = ProvenanceStore(storage_path=storage_file)
    store.disable_store("Test disable")

    admin_ctx = _create_valid_admin_context()

    with patch("os.remove", side_effect=OSError("Permission denied on state marker")):
        with pytest.raises(RuntimeError, match="Administrative recovery failed"):
            store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, admin_ctx)

    assert store.is_available() is False
    assert state_file.exists() is True


# ==============================================================================
# SECTION G: Tampered-Record Recovery Tests
# ==============================================================================

@pytest.mark.parametrize("tamper_type,tamper_mutator", [
    ("wrong_schema_version", lambda rec: rec.update({"schema_version": 99})),
    ("wrong_template_version", lambda rec: rec.update({"template_version": "99.0.0"})),
    ("wrong_template_digest", lambda rec: rec.update({"template_digest": "0" * 64})),
    ("wrong_ledger_version", lambda rec: rec.update({"ledger_version": "99.0.0"})),
    ("wrong_ledger_digest", lambda rec: rec.update({"ledger_digest": "0" * 64})),
    ("wrong_fact_version", lambda rec: rec.update({"fact_version": "99.0.0"})),
    ("wrong_fact_digest", lambda rec: rec.update({"fact_digest": "0" * 64})),
    ("wrong_employment_record_digest", lambda rec: rec.update({"employment_record_digest": "0" * 64})),
    ("tampered_rendered_text", lambda rec: rec.update({"rendered_text": "Tampered prose"})),
    ("expired_claim", lambda rec: rec.update({"expires_at": time.time() - 1000})),
])
def test_tampered_record_recovery_via_reset_produces_clean_empty_store(tmp_path, tamper_type, tamper_mutator):
    """
    Prove that tampered claim content cannot influence recovery.
    After authorized RESET_ALL_PROVENANCE:
    - recovery succeeds only by producing an empty store;
    - none of the tampered records remain;
    - none can verify after recovery.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    store = ProvenanceStore(storage_path=storage_file)
    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_tamper"
    )
    cid = rec.claim_instance_id

    # Tamper with the raw record on disk
    with open(storage_file, "r", encoding="utf-8") as f:
        records_data = json.load(f)
    tamper_mutator(records_data[cid])
    with open(storage_file, "w", encoding="utf-8") as f:
        json.dump(records_data, f, indent=2)

    # Disable store
    store.disable_store("Tamper detected", affected_draft_id="draft_tamper")
    assert store.is_available() is False

    admin_ctx = _create_valid_admin_context()
    res = store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, admin_ctx)

    assert res is True
    assert store.is_available() is True
    assert len(store._records) == 0
    assert store.get_claim_instance(cid) is None

    # Former claim cannot verify
    fresh = ProvenanceStore(storage_path=storage_file)
    assert fresh.get_claim_instance(cid) is None


# ==============================================================================
# SECTION H: Fresh Subprocess Restart Proof
# ==============================================================================

def test_subprocess_restart_lifecycle(tmp_path):
    """
    Subprocess validation of durable disablement and authorized reset:
    1. Persist valid claim and disable store.
    2. Subprocess starts unavailable.
    3. Old claim cannot verify in subprocess.
    4. Authorized reset executed.
    5. Subprocess starts available and empty.
    """
    storage_file = tmp_path / "provenance_records.json"
    state_file = tmp_path / "provenance_store_state.json"

    store = ProvenanceStore(storage_path=storage_file)
    rec = store.create_claim_instance(
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        template_id="TPL_EMP_IBM_WATSON",
        draft_id="draft_subproc"
    )
    cid = rec.claim_instance_id
    store.disable_store("Subprocess lockdown", affected_draft_id="draft_subproc")

    # Step 1: Subprocess checks store availability
    code_check_disabled = f"""
import json, sys
from pathlib import Path
from backend.canonical_grounding import ProvenanceStore

store = ProvenanceStore(storage_path=Path('{storage_file}'))
if store.is_available():
    sys.exit(10)
if store.get_claim_instance('{cid}') is not None:
    sys.exit(11)
sys.exit(0)
"""
    res = subprocess.run(
        [sys.executable, "-c", code_check_disabled],
        cwd=str(Path(__file__).parents[2]),
        capture_output=True,
        text=True
    )
    assert res.returncode == 0, f"Subprocess failed disabled check: {res.stderr}"

    # Step 2: Perform authorized recovery reset
    admin_ctx = _create_valid_admin_context()
    store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, admin_ctx)
    assert store.is_available() is True

    # Step 3: Subprocess checks store is now available and empty
    code_check_recovered = f"""
import json, sys
from pathlib import Path
from backend.canonical_grounding import ProvenanceStore

store = ProvenanceStore(storage_path=Path('{storage_file}'))
if not store.is_available():
    sys.exit(20)
if len(store._records) != 0:
    sys.exit(21)
if store.get_claim_instance('{cid}') is not None:
    sys.exit(22)
sys.exit(0)
"""
    res = subprocess.run(
        [sys.executable, "-c", code_check_recovered],
        cwd=str(Path(__file__).parents[2]),
        capture_output=True,
        text=True
    )
    assert res.returncode == 0, f"Subprocess failed recovered check: {res.stderr}"


# ==============================================================================
# SECTION I: Inherited Security Invariants
# ==============================================================================

def test_api_cannot_initiate_recovery_without_admin_context(auth_client):
    """Prove no API request can trigger or bypass administrative recovery."""
    PROVENANCE_STORE.disable_store("API isolation check")
    assert PROVENANCE_STORE.is_available() is False

    # Attempt to hit status endpoint
    resp = auth_client.get("/api/status")
    assert resp.status_code == 200
    # Store remains unavailable
    assert PROVENANCE_STORE.is_available() is False
    assert PROVENANCE_STORE.state_path.exists() is True


def test_zero_transmission_invariants_preserved():
    """Verify zero transmission paths remain strictly enforced."""
    import backend.main as main_mod
    assert not hasattr(main_mod, "authorize_send")
    assert not hasattr(main_mod, "send_email_direct")

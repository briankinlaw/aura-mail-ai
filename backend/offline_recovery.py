"""
Aura Mail AI - Offline Administrative Provenance Store Recovery (Phase 5.6)
Implements strictly offline, local, destructive administrative recovery.

Security Invariants:
1. Offline Isolation: Aura server and daemon MUST be completely stopped.
2. Kernel-Enforced Mutual Exclusion: Requires an exclusive maintenance lock (fcntl.flock LOCK_EX).
3. Interactive Terminal Enforcement: Standard input and output must be real TTYs.
4. Local OS Actor Derivation: Actor identity derived directly from OS ($UID / getpass.getuser()).
5. Dual Exact Confirmation: Operator must enter exact phrases ("RESET ALL AURA PROVENANCE" + resolved path).
6. Recovery Precondition: Refuses to reset a healthy, marker-free store.
7. Marker Mutation Detection: Digest captured and verified before committing destructive changes.
8. Destructive RESET Only: In-process repair, selective recovery, and generic enable aliases are forbidden.
9. Crash Safety & Durability: Atomic file replace with fsync, parent directory fsync, and fail-closed marker restoration.
"""

import os
import sys
import json
import time
import uuid
import errno
import getpass
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from backend.runtime_lock import (
    acquire_exclusive_maintenance_lock,
    RuntimeLockError,
    AuraRuntimeLockContext,
)

logger = logging.getLogger("aura.offline_recovery")


class RecoveryError(RuntimeError):
    """Base exception for offline administrative recovery failures."""
    pass


class RecoveryPreconditionError(RecoveryError):
    """Raised when store does not satisfy the recovery precondition (e.g. store is healthy)."""
    pass


class RecoveryTerminalError(RecoveryError):
    """Raised when recovery is invoked without an interactive terminal."""
    pass


class RecoveryConfirmationError(RecoveryError):
    """Raised when operator fails to provide exact destructive confirmation."""
    pass


class RecoveryTransactionError(RecoveryError):
    """Raised when filesystem transaction or verification fails."""
    pass


def _fsync_parent_dir(path: Path) -> None:
    """
    Fsyncs the parent directory of a path on POSIX platforms.
    Fails closed on real I/O errors while ignoring unsupported filesystem errors.
    """
    if not hasattr(os, "O_RDONLY") or not hasattr(os, "fsync"):
        return
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, IOError) as err:
        unsupported_errnos = {
            getattr(errno, "EINVAL", 22),
            getattr(errno, "ENOTSUP", 45),
            getattr(errno, "EOPNOTSUPP", 45),
        }
        if getattr(err, "errno", None) in unsupported_errnos:
            logger.debug(f"Parent directory fsync unsupported for {path.parent}: {err}")
            return
        logger.critical(f"FATAL: Supported parent directory fsync failed for {path.parent}: {err}")
        raise


def get_local_os_actor() -> str:
    """Derives and validates local operating system actor identity."""
    try:
        actor = getpass.getuser()
    except Exception:
        actor = ""

    if not actor or not isinstance(actor, str) or not actor.strip():
        try:
            import pwd
            actor = pwd.getpwuid(os.getuid()).pw_name
        except Exception:
            actor = ""

    if not actor or not actor.strip():
        raise RecoveryError("Failed to derive local operating system actor identity.")

    return actor.strip()


def resolve_and_validate_paths(target_dir: Optional[Path] = None) -> Tuple[Path, Path, Path]:
    """
    Resolves canonical data directory, storage file, and state marker file.
    Strictly rejects symlinks and unexpected paths.
    """
    raw_path = Path(target_dir) if target_dir is not None else (Path(__file__).resolve().parent.parent / "data")
    if raw_path.is_symlink():
        raise RecoveryError(f"Security violation: Target directory '{raw_path}' is a symlink.")

    resolved_dir = raw_path.resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)

    if resolved_dir.is_symlink():
        raise RecoveryError(f"Security violation: Target directory '{resolved_dir}' is a symlink.")

    storage_path = resolved_dir / "provenance_records.json"
    state_path = resolved_dir / "provenance_store_state.json"
    lock_path = resolved_dir / ".aura_runtime.lock"

    if (raw_path / "provenance_records.json").is_symlink() or storage_path.is_symlink():
        raise RecoveryError(f"Security violation: Provenance records path '{storage_path}' is a symlink.")
    if (raw_path / "provenance_store_state.json").is_symlink() or state_path.is_symlink():
        raise RecoveryError(f"Security violation: State marker path '{state_path}' is a symlink.")
    if (raw_path / ".aura_runtime.lock").is_symlink() or lock_path.is_symlink():
        raise RecoveryError(f"Security violation: Lock path '{lock_path}' is a symlink.")

    return resolved_dir, storage_path, state_path


def read_and_verify_recovery_required(state_path: Path, storage_path: Path) -> Tuple[bytes, str]:
    """
    Verifies that the store requires administrative recovery.
    Refuses recovery if the store is healthy without a state marker.
    Captures exact state marker bytes and SHA-256 digest.
    """
    if not state_path.exists():
        # Marker does not exist. Check if storage_path is healthy.
        if storage_path.exists():
            try:
                content = storage_path.read_text(encoding="utf-8")
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    raise RecoveryPreconditionError(
                        "Store precondition check failed: Provenance store is healthy and available "
                        "without a disabled state marker. Recovery is forbidden on a healthy store."
                    )
            except RecoveryPreconditionError:
                raise
            except Exception as e:
                # Corrupt claim store without a marker
                raise RecoveryPreconditionError(
                    f"Store contains corrupt claims without a durable disabled marker ({e}). "
                    "Start Aura or invoke store disablement before running recovery."
                )
        else:
            raise RecoveryPreconditionError(
                "Store precondition check failed: No provenance store or state marker found. "
                "Store is healthy or uninitialized."
            )

    try:
        marker_bytes = state_path.read_bytes()
    except Exception as e:
        raise RecoveryError(f"Failed to read durable state marker: {e}") from e

    marker_digest = hashlib.sha256(marker_bytes).hexdigest()
    return marker_bytes, marker_digest


def execute_offline_recovery_transaction(
    target_dir: Optional[Path] = None,
    interactive: bool = True,
    stdin_stream=None,
    stdout_stream=None,
    is_test_harness: bool = False,
    actor_override: Optional[str] = None,
    failure_hook: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the authoritative 26-step offline administrative provenance recovery transaction.
    
    Parameters:
      - target_dir: directory containing provenance files (defaults to canonical data/)
      - interactive: if True, validates TTY and prompts for explicit confirmation phrases
      - stdin_stream: input stream for confirmation (defaults to sys.stdin)
      - stdout_stream: output stream for prompts (defaults to sys.stdout)
      - is_test_harness: allows controlled test simulation without real human interaction
      - actor_override: test-only actor override (forbidden in CLI production)
      - failure_hook: test-only injection point for crash-order matrix testing
    """
    sin = stdin_stream or sys.stdin
    sout = stdout_stream or sys.stdout

    # Step 1: Terminal verification (unless running via trusted test harness)
    if interactive and not is_test_harness:
        if not (hasattr(sin, "isatty") and sin.isatty() and hasattr(sout, "isatty") and sout.isatty()):
            raise RecoveryTerminalError(
                "Offline administrative recovery requires an interactive terminal (stdin and stdout attached to TTY). "
                "Non-interactive invocation, pipes, background execution, and redirected input are strictly forbidden."
            )

    # Step 2: Derive local operating system actor
    actor = actor_override if (is_test_harness and actor_override) else get_local_os_actor()

    # Step 3: Resolve and validate paths
    resolved_dir, storage_path, state_path = resolve_and_validate_paths(target_dir)

    # Step 4 & 5: Acquire exclusive maintenance lock and prove Aura is stopped
    if failure_hook == "fail_lock_acquisition":
        raise RuntimeLockError("Injected failure: lock acquisition failed")

    lock_ctx = acquire_exclusive_maintenance_lock(data_dir=resolved_dir, actor=actor)

    try:
        # Step 6 & 7: Re-validate paths under lock
        if resolved_dir.is_symlink() or storage_path.is_symlink() or state_path.is_symlink():
            raise RecoveryError("Security violation: Symlinked filesystem target detected under lock.")

        # Step 8, 9, 10: Read durable marker, verify recovery required, capture bytes & digest
        marker_bytes, marker_digest = read_and_verify_recovery_required(state_path, storage_path)

        # Step 11: Explicit destructive confirmation
        if interactive and not is_test_harness:
            sout.write("\n" + "=" * 70 + "\n")
            sout.write("⚠️  AURA MAIL AI — OFFLINE ADMINISTRATIVE PROVENANCE RECOVERY\n")
            sout.write("=" * 70 + "\n")
            sout.write(f"Target Directory : {resolved_dir}\n")
            sout.write(f"Local Operator   : {actor}\n")
            sout.write(f"Marker Digest    : {marker_digest}\n")
            sout.write("\nWARNING: This destructive operation will permanently erase ALL existing\n")
            sout.write("provenance claims, manifests, and signatures. All former claim IDs will\n")
            sout.write("be irrevocably invalidated.\n\n")

            sout.write("Confirmation 1: Type 'RESET ALL AURA PROVENANCE' to continue: ")
            sout.flush()
            conf1 = sin.readline()
            if not conf1 or conf1.strip() != "RESET ALL AURA PROVENANCE":
                raise RecoveryConfirmationError(
                    "Recovery aborted: First confirmation failed. Expected exact phrase 'RESET ALL AURA PROVENANCE'."
                )

            sout.write(f"Confirmation 2: Type the full resolved path '{resolved_dir}' to confirm target: ")
            sout.flush()
            conf2 = sin.readline()
            if not conf2 or conf2.strip() != str(resolved_dir):
                raise RecoveryConfirmationError(
                    f"Recovery aborted: Second confirmation failed. Expected exact target directory '{resolved_dir}'."
                )

        # Step 12: Recheck maintenance lock
        if not lock_ctx.is_held():
            raise RuntimeLockError("Maintenance lock lost during confirmation phase.")

        # Step 13: Recheck state marker still exists and matches captured digest
        if not state_path.exists():
            raise RecoveryTransactionError("State marker vanished before destructive commit.")
        current_marker_digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
        if current_marker_digest != marker_digest:
            raise RecoveryTransactionError(
                f"State marker was mutated during recovery transaction (digest mismatch). "
                f"Expected '{marker_digest}', found '{current_marker_digest}'. Aborting fail-closed."
            )

        # Step 14: Create empty claim-store temporary file in same directory
        if failure_hook == "fail_temp_creation":
            raise IOError("Injected failure: temp file creation failed")

        temp_store_path = resolved_dir / f".tmp_{uuid.uuid4().hex}_provenance_records.json"
        
        try:
            # Step 15: Serialize exactly {}
            if failure_hook == "fail_serialization":
                raise ValueError("Injected failure: serialization failed")
            payload = json.dumps({}, indent=2).encode("utf-8")

            # Step 16: Write, flush, and fsync temporary file
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            mode = 0o600
            fd = os.open(str(temp_store_path), flags, mode)
            try:
                if failure_hook == "fail_temp_write":
                    raise IOError("Injected failure: temp write failed")
                os.write(fd, payload)
                if failure_hook == "fail_temp_flush":
                    raise IOError("Injected failure: temp flush failed")
                if failure_hook == "fail_temp_fsync":
                    raise IOError("Injected failure: temp fsync failed")
                os.fsync(fd)
            finally:
                os.close(fd)

            # Step 17: Atomically replace claim store
            if failure_hook == "fail_claim_replace":
                raise IOError("Injected failure: atomic claim replacement failed")
            os.replace(temp_store_path, storage_path)

            # Step 18: Directory fsync parent directory
            if failure_hook == "fail_dir_fsync_1":
                raise IOError("Injected failure: first parent directory fsync failed")
            _fsync_parent_dir(storage_path)

            # Step 19: Reopen and verify stored value is exactly {}
            if failure_hook == "fail_claim_reread":
                raise IOError("Injected failure: claim reread failed")
            with open(storage_path, "r", encoding="utf-8") as f:
                parsed_claims = json.load(f)
            if parsed_claims != {}:
                raise RecoveryTransactionError("Failed to verify empty store after reset write.")

            if failure_hook == "fail_empty_validation":
                raise ValueError("Injected failure: empty store validation failed")

            # Step 20: Remove disabled state marker
            if failure_hook == "fail_marker_removal":
                raise IOError("Injected failure: marker removal failed")
            if failure_hook == "fail_marker_recreation":
                if state_path.exists():
                    os.remove(state_path)
                raise IOError("Injected failure: error triggering marker recreation")
            if state_path.exists():
                os.remove(state_path)

            # Step 21: Directory fsync after marker removal
            if failure_hook == "fail_dir_fsync_2":
                raise IOError("Injected failure: second parent directory fsync failed")
            _fsync_parent_dir(state_path)

            # Step 22: Verify marker is absent
            if failure_hook == "fail_marker_absence_check":
                raise RuntimeError("Injected failure: marker absence check failed")
            if state_path.exists():
                raise RecoveryTransactionError("Failed to remove disabled state marker: marker still exists.")

            # Step 23: Final reload and empty store revalidation
            if failure_hook == "fail_final_reload":
                raise IOError("Injected failure: final claim reload failed")
            with open(storage_path, "r", encoding="utf-8") as f:
                final_claims = json.load(f)
            if final_claims != {}:
                raise RecoveryTransactionError("Final validation failed: store is not empty.")
            if failure_hook == "fail_final_empty_validation":
                raise ValueError("Injected failure: final empty validation failed")

            # Step 24: Record secret-free administrative audit event
            if failure_hook == "fail_audit_write":
                raise IOError("Injected failure: audit write failed")

            audit_record = {
                "event": "PROVENANCE_STORE_OFFLINE_RESET",
                "actor": actor,
                "target_dir": str(resolved_dir),
                "timestamp": time.time(),
                "status": "SUCCESS",
                "prior_marker_digest": marker_digest,
            }
            logger.info(f"Offline recovery completed successfully by {actor}: {audit_record}")

            return {
                "success": True,
                "actor": actor,
                "target_dir": str(resolved_dir),
                "timestamp": audit_record["timestamp"],
                "prior_marker_digest": marker_digest,
            }

        except Exception as tx_err:
            # Clean up temp file if present
            if temp_store_path.exists():
                try:
                    temp_store_path.unlink()
                except Exception:
                    pass

            # Fail-Closed Safety: If marker was deleted or claim replaced, recreate a valid DISABLED marker
            if not state_path.exists():
                try:
                    if failure_hook == "fail_marker_recreation":
                        raise IOError("Injected failure: marker recreation failed")
                    fallback_state = {
                        "schema_version": 1,
                        "state": "DISABLED",
                        "reason": f"Post-recovery failure: {tx_err}",
                        "affected_draft_id": None,
                        "disabled_at": time.time(),
                        "recovery_required": True
                    }
                    tmp_state = resolved_dir / f".tmp_{uuid.uuid4().hex}_state.json"
                    with open(tmp_state, "w", encoding="utf-8") as f:
                        json.dump(fallback_state, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_state, state_path)
                    _fsync_parent_dir(state_path)
                    logger.critical(f"Recreated valid DISABLED state marker fail-closed after recovery error: {tx_err}")
                except Exception as rec_err:
                    logger.critical(f"FATAL: Failed to restore disabled marker after recovery error: {rec_err}")

            raise RecoveryTransactionError(f"Offline recovery transaction failed: {tx_err}") from tx_err

    finally:
        # Step 25: Release maintenance lock
        if failure_hook == "fail_lock_release":
            pass  # Simulation
        lock_ctx.release()


def main(argv=None) -> int:
    """CLI Entrypoint for offline administrative provenance recovery."""
    args = argv if argv is not None else sys.argv[1:]

    # Parse and strictly reject unsupported flags
    forbidden_flags = [
        "--yes", "-y", "--force", "-f", "--actor", "--strategy",
        "--repair", "--auto", "--enable", "--clear", "--reset"
    ]
    for arg in args:
        if arg.lower() in forbidden_flags or arg.startswith("--"):
            sys.stderr.write(f"Error: Unsupported or forbidden argument '{arg}'.\n")
            sys.stderr.write("Offline recovery does not accept bypass flags, custom actors, or strategy overrides.\n")
            return 1

    try:
        execute_offline_recovery_transaction(target_dir=None, interactive=True)
        print("\n✅ Provenance store administrative recovery successfully completed.")
        print("All previous provenance claims have been permanently wiped.")
        print("Aura Mail AI may now be safely restarted.\n")
        return 0
    except (RecoveryTerminalError, RecoveryConfirmationError, RecoveryPreconditionError, RuntimeLockError) as e:
        sys.stderr.write(f"\n❌ Recovery Aborted: {e}\n\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"\n❌ Recovery Failed (Fail-Closed): {e}\n\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

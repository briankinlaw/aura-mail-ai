"""
Aura Mail AI - Offline Administrative Provenance Store Recovery (Phase 5.6.1)
Implements strictly offline, local, destructive administrative recovery.

Security Invariants:
1. Offline Isolation: Aura server and daemon MUST be completely stopped.
2. Kernel-Enforced Mutual Exclusion: Requires an exclusive maintenance lock (fcntl.flock LOCK_EX).
3. Interactive Terminal Enforcement: Standard input and output must be real TTYs (sys.stdin.isatty() and sys.stdout.isatty()).
4. Local OS Actor Derivation: Actor identity derived directly from OS account database (os.getuid() and pwd.getpwuid()).
5. Dual Exact Confirmation: Operator must enter exact phrases ("RESET ALL AURA PROVENANCE" + canonical path).
6. Canonical Target Only: Operates solely on the canonical data directory; refuses caller-directed targets.
7. Recovery Precondition: Refuses to reset a healthy, marker-free store.
8. Marker Mutation Detection: Digest captured and verified before committing destructive changes.
9. Destructive RESET Only: In-process repair, selective recovery, and generic enable aliases are forbidden.
10. Crash Safety & Durability: Atomic file replace with fsync, parent directory fsync, durable local JSONL audit, and fail-closed marker restoration.
11. Zero Production Bypass: No test-mode flags, no actor overrides, no custom streams, no failure hooks in production.
"""

import os
import sys
import stat
import json
import time
import uuid
import errno
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


def _write_all(fd: int, data: bytes) -> None:
    """
    Writes the complete byte buffer to a file descriptor using a loop.
    Protects against partial/short writes.
    """
    total = 0
    while total < len(data):
        n = os.write(fd, data[total:])
        if n <= 0:
            raise IOError(f"Short write on file descriptor {fd}: wrote {total}/{len(data)} bytes")
        total += n


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


def get_local_os_actor() -> Tuple[int, str]:
    """
    Derives actor identity strictly from the operating system account database.
    Refuses environment variable overrides (LOGNAME, USER, USERNAME, LNAME).
    Returns (numeric_uid, resolved_username).
    """
    uid = os.getuid()
    if not isinstance(uid, int) or isinstance(uid, bool) or uid < 0:
        raise RecoveryPreconditionError(f"Invalid operating system UID: {uid}")
    try:
        import pwd
        pw_entry = pwd.getpwuid(uid)
        username = pw_entry.pw_name
    except Exception as e:
        raise RecoveryPreconditionError(f"Failed to resolve operating system username for UID {uid}: {e}") from e
    if not username or not isinstance(username, str) or not username.strip():
        raise RecoveryPreconditionError(f"Empty operating system username resolved for UID {uid}")
    return uid, username.strip()


def resolve_canonical_data_dir() -> Path:
    """
    Resolves the canonical repository data directory based on installed application layout.
    Strictly refuses symlinks, relative traversal, or caller-directed paths.
    """
    app_root = Path(__file__).resolve().parent.parent
    raw_data_dir = app_root / "data"
    if raw_data_dir.is_symlink():
        raise RecoveryPreconditionError(f"Security violation: Canonical data directory '{raw_data_dir}' is a symlink.")
    resolved_dir = raw_data_dir.resolve()
    if resolved_dir.is_symlink():
        raise RecoveryPreconditionError(f"Security violation: Resolved data directory '{resolved_dir}' is a symlink.")
    resolved_dir.mkdir(parents=True, exist_ok=True)
    return resolved_dir


def _validate_provenance_paths(data_dir: Path) -> Tuple[Path, Path, Path, Path]:
    """
    Validates storage_path, state_path, lock_path, audit_path within data_dir.
    Refuses symlinked files or directories.
    """
    if data_dir.is_symlink():
        raise RecoveryPreconditionError(f"Security violation: Data directory '{data_dir}' is a symlink.")

    storage_path = data_dir / "provenance_records.json"
    state_path = data_dir / "provenance_store_state.json"
    lock_path = data_dir / ".aura_runtime.lock"
    audit_path = data_dir / ".aura_recovery_audit.log"

    for p in [storage_path, state_path, lock_path, audit_path]:
        if p.is_symlink():
            raise RecoveryPreconditionError(f"Security violation: Path '{p}' cannot be a symlink.")

    return storage_path, state_path, lock_path, audit_path


def read_and_verify_recovery_required(state_path: Path, storage_path: Path) -> Tuple[bytes, str]:
    """
    Verifies that the store requires administrative recovery.
    Refuses recovery if the store is healthy without a state marker.
    Captures exact state marker bytes and SHA-256 digest.
    """
    if not state_path.exists():
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


def _write_empty_store_atomically(data_dir: Path, storage_path: Path) -> None:
    """
    Atomically writes an empty JSON object '{}' to the provenance claim store.
    Uses temporary file with 0600 mode, short-write loop, fsync, atomic replace, and parent dir fsync.
    """
    temp_store_path = data_dir / f".tmp_{uuid.uuid4().hex}_provenance_records.json"
    payload = json.dumps({}, indent=2).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    mode = 0o600

    fd = os.open(str(temp_store_path), flags, mode)
    try:
        stat_fd = os.fstat(fd)
        if not stat.S_ISREG(stat_fd.st_mode):
            raise RecoveryTransactionError("Temporary store file is not a regular file")
        os.fchmod(fd, 0o600)
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)

    os.replace(temp_store_path, storage_path)
    _fsync_parent_dir(storage_path)


def _verify_empty_store(storage_path: Path) -> None:
    """
    Reads and parses the stored claim file, verifying it contains exactly {}.
    """
    if not storage_path.exists():
        raise RecoveryTransactionError(f"Storage path '{storage_path}' does not exist after reset.")
    with open(storage_path, "r", encoding="utf-8") as f:
        parsed_claims = json.load(f)
    if parsed_claims != {}:
        raise RecoveryTransactionError("Verification failed: claim store is not empty after reset.")


def _remove_disabled_marker(state_path: Path) -> None:
    """
    Removes the disabled state marker file and fsyncs parent directory.
    """
    if state_path.exists():
        os.remove(state_path)
    _fsync_parent_dir(state_path)


def _restore_disabled_marker(data_dir: Path, state_path: Path, reason: str) -> None:
    """
    Recreates a strictly valid DISABLED state marker fail-closed after a recovery transaction error.
    """
    fallback_state = {
        "schema_version": 1,
        "state": "DISABLED",
        "reason": reason,
        "affected_draft_id": None,
        "disabled_at": time.time(),
        "recovery_required": True,
    }
    payload = json.dumps(fallback_state, indent=2).encode("utf-8")
    tmp_state = data_dir / f".tmp_{uuid.uuid4().hex}_state.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    mode = 0o600

    fd = os.open(str(tmp_state), flags, mode)
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)

    os.replace(tmp_state, state_path)
    _fsync_parent_dir(state_path)
    logger.critical(f"Recreated valid DISABLED state marker fail-closed: {reason}")


def _append_recovery_audit(
    data_dir: Path,
    uid: int,
    username: str,
    prior_marker_digest: str,
) -> None:
    """
    Durably appends a secret-free administrative recovery audit record to data/.aura_recovery_audit.log.
    """
    audit_path = data_dir / ".aura_recovery_audit.log"
    if audit_path.is_symlink():
        raise RecoveryTransactionError(f"Audit log path '{audit_path}' is a symlink.")

    record = {
        "event_type": "OFFLINE_ADMINISTRATIVE_PROVENANCE_RECOVERY",
        "uid": uid,
        "username": username,
        "target_dir": str(data_dir),
        "timestamp": time.time(),
        "prior_marker_digest": prior_marker_digest,
        "status": "SUCCESS",
    }
    line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    mode = 0o600

    fd = os.open(str(audit_path), flags, mode)
    try:
        stat_fd = os.fstat(fd)
        stat_path = os.stat(str(audit_path), follow_symlinks=False)
        if (stat_fd.st_dev, stat_fd.st_ino) != (stat_path.st_dev, stat_path.st_ino):
            raise RecoveryTransactionError(f"Audit file metadata mismatch for '{audit_path}' (symlink attack)")
        if not stat.S_ISREG(stat_fd.st_mode):
            raise RecoveryTransactionError(f"Audit file '{audit_path}' is not a regular file")
        os.fchmod(fd, 0o600)
        _write_all(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)

    _fsync_parent_dir(audit_path)


def run_offline_recovery() -> Dict[str, Any]:
    """
    Authoritative production entrypoint for offline administrative provenance recovery.
    Accepts NO arguments capable of changing or bypassing security controls.
    Always enforces real TTY stdin/stdout, OS-derived actor, canonical data directory,
    exclusive maintenance lock, dual exact interactive confirmations, destructive reset,
    and durable crash-safe audit logging.
    """
    # 1. Real TTY check
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty() and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        raise RecoveryTerminalError(
            "Offline administrative recovery requires an interactive terminal (stdin and stdout attached to TTY). "
            "Non-interactive invocation, pipes, background execution, and redirected input are strictly forbidden."
        )

    # 2. Derive OS actor from account database
    uid, username = get_local_os_actor()

    # 3. Resolve canonical data directory
    data_dir = resolve_canonical_data_dir()

    # 4. Validate paths
    storage_path, state_path, lock_path, audit_path = _validate_provenance_paths(data_dir)

    # 5. Acquire exclusive maintenance lock
    lock_ctx = acquire_exclusive_maintenance_lock(data_dir=data_dir, actor=username)

    try:
        # 6. Re-validate paths under lock
        storage_path, state_path, lock_path, audit_path = _validate_provenance_paths(data_dir)

        # 7. Read durable marker, verify recovery required, capture bytes & digest
        marker_bytes, marker_digest = read_and_verify_recovery_required(state_path, storage_path)

        # 8. Interactive confirmation sequence
        sys.stdout.write("\n" + "=" * 70 + "\n")
        sys.stdout.write("⚠️  AURA MAIL AI — OFFLINE ADMINISTRATIVE PROVENANCE RECOVERY\n")
        sys.stdout.write("=" * 70 + "\n")
        sys.stdout.write(f"Target Directory : {data_dir}\n")
        sys.stdout.write(f"Local Operator   : {username} (UID {uid})\n")
        sys.stdout.write(f"Marker Digest    : {marker_digest}\n")
        sys.stdout.write("\nWARNING: This destructive operation will permanently erase ALL existing\n")
        sys.stdout.write("provenance claims, manifests, and signatures. All former claim IDs will\n")
        sys.stdout.write("be irrevocably invalidated.\n\n")

        sys.stdout.write("Confirmation 1: Type 'RESET ALL AURA PROVENANCE' to continue: ")
        sys.stdout.flush()
        conf1 = sys.stdin.readline()
        if not conf1 or conf1.strip() != "RESET ALL AURA PROVENANCE":
            raise RecoveryConfirmationError(
                "Recovery aborted: First confirmation failed. Expected exact phrase 'RESET ALL AURA PROVENANCE'."
            )

        sys.stdout.write(f"Confirmation 2: Type the full resolved path '{data_dir}' to confirm target: ")
        sys.stdout.flush()
        conf2 = sys.stdin.readline()
        if not conf2 or conf2.strip() != str(data_dir):
            raise RecoveryConfirmationError(
                f"Recovery aborted: Second confirmation failed. Expected exact target directory '{data_dir}'."
            )

        # 9. Recheck maintenance lock
        if not lock_ctx.is_held():
            raise RuntimeLockError("Maintenance lock lost during confirmation phase.")

        # 10. Recheck state marker still exists and matches captured digest
        if not state_path.exists():
            raise RecoveryTransactionError("State marker vanished before destructive commit.")
        current_marker_digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
        if current_marker_digest != marker_digest:
            raise RecoveryTransactionError(
                f"State marker was mutated during recovery transaction (digest mismatch). "
                f"Expected '{marker_digest}', found '{current_marker_digest}'. Aborting fail-closed."
            )

        # 11. Execute destructive replacement
        _write_empty_store_atomically(data_dir, storage_path)

        # 12. Verify stored value is exactly {}
        _verify_empty_store(storage_path)

        # 13. Remove disabled marker and persist durable audit
        try:
            _remove_disabled_marker(state_path)
            if state_path.exists():
                raise RecoveryTransactionError("Failed to remove disabled state marker: marker still exists.")
            _verify_empty_store(storage_path)
            _append_recovery_audit(data_dir, uid, username, marker_digest)
        except Exception as post_remove_err:
            # Fail-closed marker restoration
            if not state_path.exists():
                try:
                    _restore_disabled_marker(data_dir, state_path, f"Post-recovery failure: {post_remove_err}")
                except Exception as rec_err:
                    logger.critical(f"FATAL: Failed to restore disabled marker after recovery error: {rec_err}")
            raise RecoveryTransactionError(f"Offline recovery transaction failed after claim replacement: {post_remove_err}") from post_remove_err

        audit_result = {
            "success": True,
            "actor": username,
            "uid": uid,
            "target_dir": str(data_dir),
            "timestamp": time.time(),
            "prior_marker_digest": marker_digest,
        }
        logger.info(f"Offline recovery completed successfully: {audit_result}")
        return audit_result

    finally:
        lock_ctx.release()


def main(argv=None) -> int:
    """CLI Entrypoint for offline administrative provenance recovery."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) > 0:
        sys.stderr.write(f"Error: Offline recovery accepts no arguments (received: {args}).\n")
        sys.stderr.write("Usage: python -m backend.offline_recovery (or scripts/aura-recover-provenance)\n")
        return 2

    try:
        res = run_offline_recovery()
        print("\n✅ Provenance store administrative recovery successfully completed.")
        print(f"Target Directory : {res['target_dir']}")
        print(f"Local Operator   : {res['actor']} (UID {res['uid']})")
        print(f"Marker Digest    : {res['prior_marker_digest']}")
        print("All previous provenance claims have been permanently wiped.")
        print("Aura Mail AI may now be safely restarted.\n")
        return 0
    except (RecoveryPreconditionError, RecoveryTerminalError, RecoveryConfirmationError, RuntimeLockError) as e:
        sys.stderr.write(f"\n❌ Recovery Aborted: {e}\n\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"\n❌ Recovery Failed (Fail-Closed): {e}\n\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""
Aura Mail AI - Runtime and Maintenance Process Locking (Phase 5.6.1)
Provides kernel-enforced mutual exclusion between active Aura runtime components
(FastAPI server, background daemon) and offline administrative recovery.

Locking Architecture:
- POSIX fcntl.flock on .aura_runtime.lock located in the canonical data directory.
- Runtime components acquire a SHARED lock (fcntl.LOCK_SH | fcntl.LOCK_NB).
- Offline recovery requires an EXCLUSIVE lock (fcntl.LOCK_EX | fcntl.LOCK_NB).

Security Invariants:
1. Multiple runtime processes (server, daemon) can run concurrently under shared locks.
2. Offline recovery CANNOT run if ANY runtime process is active (fails closed).
3. Runtime processes CANNOT start while offline recovery is executing under an exclusive lock.
4. Stale lock files from crashed processes are automatically released by the OS kernel.
5. Symlink refusal before open and O_NOFOLLOW open with fstat/stat validation.
6. File mode is strictly 0600 (user-read/write only) and ownership is validated.
"""

import os
import stat
import fcntl
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("aura.runtime_lock")


class RuntimeLockError(RuntimeError):
    """Raised when runtime or maintenance lock cannot be acquired due to active concurrency conflict."""
    pass


class AuraRuntimeLockContext:
    """Context manager for acquiring and safely releasing shared/exclusive process locks."""

    def __init__(self, lock_path: Path, is_exclusive: bool = False, actor: Optional[str] = None):
        self.raw_lock_path = Path(lock_path)
        self.is_exclusive = is_exclusive
        self.actor = actor or "unknown"
        self._fd: Optional[int] = None
        self._is_held: bool = False

    @property
    def lock_path(self) -> Path:
        return self.raw_lock_path

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def acquire(self) -> None:
        if self._is_held:
            return

        # Refuse symlink lock paths before opening
        if self.raw_lock_path.is_symlink():
            raise RuntimeLockError(f"Security violation: Lock path '{self.raw_lock_path}' is a symlink.")

        # Ensure parent directory exists and is not a symlink
        parent_dir = self.raw_lock_path.parent
        if parent_dir.is_symlink():
            raise RuntimeLockError(f"Security violation: Lock parent directory '{parent_dir}' is a symlink.")
        parent_dir.mkdir(parents=True, exist_ok=True)
        if parent_dir.is_symlink():
            raise RuntimeLockError(f"Security violation: Lock parent directory '{parent_dir}' is a symlink.")

        # Open lock file with O_NOFOLLOW and 0600 mode
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        mode = 0o600
        try:
            self._fd = os.open(str(self.raw_lock_path), flags, mode)
        except Exception as e:
            raise RuntimeLockError(f"Failed to open process lock file at '{self.raw_lock_path}': {e}") from e

        # Post-open metadata validation
        try:
            stat_fd = os.fstat(self._fd)
            stat_path = os.stat(str(self.raw_lock_path), follow_symlinks=False)

            # Compare device and inode to defeat TOCTOU substitution
            if (stat_fd.st_dev, stat_fd.st_ino) != (stat_path.st_dev, stat_path.st_ino):
                raise RuntimeLockError(
                    f"Security violation: Lock file '{self.raw_lock_path}' metadata mismatch (possible symlink attack)."
                )

            # Validate regular file
            if not stat.S_ISREG(stat_fd.st_mode):
                raise RuntimeLockError(
                    f"Security violation: Lock file '{self.raw_lock_path}' is not a regular file."
                )

            # Verify ownership
            if stat_fd.st_uid != os.getuid():
                raise RuntimeLockError(
                    f"Security violation: Lock file '{self.raw_lock_path}' owned by UID {stat_fd.st_uid}, expected {os.getuid()}."
                )

            # Enforce 0600 mode on open descriptor
            try:
                os.fchmod(self._fd, 0o600)
            except Exception:
                pass

        except Exception as validation_err:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
            raise RuntimeLockError(f"Lock file validation failed: {validation_err}") from validation_err

        # Determine flock operation
        op = fcntl.LOCK_EX if self.is_exclusive else fcntl.LOCK_SH
        op |= fcntl.LOCK_NB  # Always non-blocking

        try:
            fcntl.flock(self._fd, op)
            self._is_held = True
        except (BlockingIOError, PermissionError, OSError) as err:
            self.release()
            lock_type = "exclusive maintenance" if self.is_exclusive else "shared runtime"
            if self.is_exclusive:
                msg = (
                    f"Cannot acquire {lock_type} lock on '{self.raw_lock_path}'. "
                    "Aura runtime (server or background daemon) is currently running. "
                    "Aura must be completely stopped before performing administrative recovery."
                )
            else:
                msg = (
                    f"Cannot acquire {lock_type} lock on '{self.raw_lock_path}'. "
                    "Offline administrative maintenance or recovery is currently in progress."
                )
            logger.warning(msg)
            raise RuntimeLockError(msg) from err

        # Record diagnostic metadata if exclusive
        if self.is_exclusive and self._fd is not None:
            try:
                os.ftruncate(self._fd, 0)
                os.lseek(self._fd, 0, os.SEEK_SET)
                meta = {
                    "pid": os.getpid(),
                    "type": "EXCLUSIVE_MAINTENANCE",
                    "actor": self.actor,
                    "acquired_at": time.time(),
                }
                payload = json.dumps(meta, indent=2).encode("utf-8")
                total = 0
                while total < len(payload):
                    n = os.write(self._fd, payload[total:])
                    if n <= 0:
                        break
                    total += n
                os.fsync(self._fd)
            except Exception:
                pass

    def is_held(self) -> bool:
        return self._is_held

    def release(self) -> None:
        if self._fd is not None:
            try:
                if self._is_held:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            except Exception:
                pass
            finally:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
                self._is_held = False


def get_default_lock_path(data_dir: Optional[Path] = None) -> Path:
    """Returns canonical process lock file path in the data directory."""
    if data_dir is not None:
        return Path(data_dir) / ".aura_runtime.lock"
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "data" / ".aura_runtime.lock"


def acquire_shared_runtime_lock(data_dir: Optional[Path] = None) -> AuraRuntimeLockContext:
    """
    Acquires the shared runtime lock held by running Aura server and daemon processes.
    Fails immediately if offline maintenance holds an exclusive lock.
    """
    lock_path = get_default_lock_path(data_dir)
    ctx = AuraRuntimeLockContext(lock_path, is_exclusive=False, actor="aura_runtime")
    ctx.acquire()
    return ctx


def acquire_exclusive_maintenance_lock(data_dir: Optional[Path] = None, actor: Optional[str] = None) -> AuraRuntimeLockContext:
    """
    Acquires the exclusive maintenance lock required for offline administrative recovery.
    Fails immediately if any Aura runtime process is active or another recovery is running.
    """
    lock_path = get_default_lock_path(data_dir)
    ctx = AuraRuntimeLockContext(lock_path, is_exclusive=True, actor=actor)
    ctx.acquire()
    return ctx

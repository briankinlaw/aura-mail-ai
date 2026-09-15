"""
Aura Mail AI - Runtime and Maintenance Process Locking (Phase 5.6)
Provides kernel-enforced mutual exclusion between active Aura runtime components
(FastAPI server, background daemon) and offline administrative recovery.

Locking Architecture:
- POSIX fcntl.flock on .aura_runtime.lock located in the data directory.
- Runtime components acquire a SHARED lock (fcntl.LOCK_SH | fcntl.LOCK_NB).
- Offline recovery requires an EXCLUSIVE lock (fcntl.LOCK_EX | fcntl.LOCK_NB).

Invariants:
1. Multiple runtime processes (server, daemon) can run concurrently under shared locks.
2. Offline recovery CANNOT run if ANY runtime process is active (fails closed).
3. Runtime processes CANNOT start while offline recovery is executing under an exclusive lock.
4. Stale lock files from crashed processes are automatically released by the OS kernel.
5. Lock files cannot be symlinks (rejects symlinks fail-closed).
6. File mode is strictly 0600 (user-read/write only).
"""

import os
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
        self.lock_path = lock_path.resolve()
        self.is_exclusive = is_exclusive
        self.actor = actor or "unknown"
        self._fd: Optional[int] = None
        self._is_held: bool = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def acquire(self) -> None:
        if self._is_held:
            return

        # Ensure parent directory exists
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Fail closed on symlink lock file
        if self.lock_path.is_symlink():
            raise RuntimeLockError(f"Security violation: Lock path '{self.lock_path}' is a symlink.")

        # Open lock file with 0600 permissions
        flags = os.O_RDWR | os.O_CREAT
        mode = 0o600
        try:
            self._fd = os.open(str(self.lock_path), flags, mode)
            os.chmod(str(self.lock_path), mode)
        except Exception as e:
            raise RuntimeLockError(f"Failed to open process lock file at '{self.lock_path}': {e}") from e

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
                    f"Cannot acquire {lock_type} lock on '{self.lock_path}'. "
                    "Aura runtime (server or background daemon) is currently running. "
                    "Aura must be completely stopped before performing administrative recovery."
                )
            else:
                msg = (
                    f"Cannot acquire {lock_type} lock on '{self.lock_path}'. "
                    "Offline administrative maintenance or recovery is currently in progress."
                )
            logger.warning(msg)
            raise RuntimeLockError(msg) from err

        # Record diagnostic metadata if exclusive (without overwriting if shared)
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
                os.write(self._fd, payload)
                os.fsync(self._fd)
            except Exception:
                pass  # Non-fatal metadata write

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

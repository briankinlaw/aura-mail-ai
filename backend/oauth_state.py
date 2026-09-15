"""
Aura Mail AI - Server-Created OAuth State Transaction Management (Phase 6).
Provides cryptographically random, purpose-bound, canonical-redirect-bound,
expiring, single-use OAuth authorization state records.
"""

import time
import secrets
import logging
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger("aura.oauth_state")

OAUTH_STATE_LIFETIME_SECONDS = 300  # 5 minutes
MAX_ACTIVE_OAUTH_STATES = 200


@dataclass
class OAuthStateRecord:
    state_token: str
    provider: str  # "MICROSOFT_GRAPH" or "GMAIL"
    redirect_uri: str
    account_id: Optional[str]
    issued_at: float
    expires_at: float
    consumed: bool = False


class OAuthStateManager:
    """
    Thread-safe in-memory manager for single-use, expiring OAuth state transactions.
    """
    def __init__(
        self,
        lifetime_seconds: float = OAUTH_STATE_LIFETIME_SECONDS,
        max_entries: int = MAX_ACTIVE_OAUTH_STATES,
        time_func=None
    ):
        self._lifetime = lifetime_seconds
        self._max_entries = max_entries
        self._time_func = time_func or time.time
        self._lock = threading.Lock()
        self._records: Dict[str, OAuthStateRecord] = {}

    def _cleanup_expired_locked(self, now: float):
        """Removes expired or consumed records under lock."""
        expired_keys = [
            k for k, rec in self._records.items()
            if rec.consumed or rec.expires_at < now
        ]
        for k in expired_keys:
            del self._records[k]

    def create_state(
        self,
        provider: str,
        redirect_uri: str,
        account_id: Optional[str] = None
    ) -> str:
        """
        Creates a new 256-bit cryptographically random, purpose-bound OAuth state token.
        """
        now = self._time_func()
        with self._lock:
            self._cleanup_expired_locked(now)
            if len(self._records) >= self._max_entries:
                logger.error("OAuth state registry capacity exceeded. Rejecting new state creation.")
                raise RuntimeError("OAuth state capacity exceeded. Please retry.")

            token = secrets.token_urlsafe(32)
            record = OAuthStateRecord(
                state_token=token,
                provider=provider.upper(),
                redirect_uri=redirect_uri,
                account_id=account_id.lower() if account_id else None,
                issued_at=now,
                expires_at=now + self._lifetime,
                consumed=False
            )
            self._records[token] = record
            logger.info(f"Created OAuth state for provider={provider.upper()} (expires in {self._lifetime}s)")
            return token

    def validate_and_consume(
        self,
        state_token: Optional[str],
        expected_provider: str,
        expected_redirect_uri: Optional[str] = None
    ) -> Optional[OAuthStateRecord]:
        """
        Atomically validates and consumes an OAuth state token.
        Fails closed (returns None) if state is missing, malformed, unknown, expired,
        already consumed, or bound to a different provider or redirect URI.
        """
        if not state_token or not isinstance(state_token, str):
            return None

        clean_token = state_token.strip()
        now = self._time_func()
        expected_prov = expected_provider.upper()

        with self._lock:
            self._cleanup_expired_locked(now)
            record = self._records.get(clean_token)
            if not record:
                logger.warning("OAuth callback rejected: State token not found or already purged.")
                return None

            if record.consumed:
                logger.warning("OAuth callback rejected: State token already consumed (replay attempt).")
                del self._records[clean_token]
                return None

            if record.expires_at < now:
                logger.warning("OAuth callback rejected: State token has expired.")
                del self._records[clean_token]
                return None

            if record.provider != expected_prov:
                logger.warning(f"OAuth callback rejected: State provider mismatch (expected {expected_prov}, got {record.provider}).")
                del self._records[clean_token]
                return None

            if expected_redirect_uri and record.redirect_uri != expected_redirect_uri:
                logger.warning(f"OAuth callback rejected: Redirect URI mismatch (expected {expected_redirect_uri}, got {record.redirect_uri}).")
                del self._records[clean_token]
                return None

            # Mark consumed and remove atomically
            record.consumed = True
            consumed_copy = OAuthStateRecord(
                state_token=record.state_token,
                provider=record.provider,
                redirect_uri=record.redirect_uri,
                account_id=record.account_id,
                issued_at=record.issued_at,
                expires_at=record.expires_at,
                consumed=True
            )
            del self._records[clean_token]
            logger.info(f"Successfully validated and consumed OAuth state for provider={expected_prov}.")
            return consumed_copy

    def count_active_states(self) -> int:
        """Returns the number of unexpired active states."""
        now = self._time_func()
        with self._lock:
            self._cleanup_expired_locked(now)
            return len(self._records)

    def reset(self):
        """Clears all state records (for testing)."""
        with self._lock:
            self._records.clear()


# Global singleton instance
OAUTH_STATE_MANAGER = OAuthStateManager()

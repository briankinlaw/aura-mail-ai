"""
Aura Mail AI - Local API Trust Boundary & Request Authorization (Phase 2).
Provides cryptographically secure local session token generation, verification,
and FastAPI dependencies to protect privileged endpoints from unauthorized or
cross-origin browser invocation.
"""

import os
import hmac
import secrets
import logging
from typing import Optional, Dict
from fastapi import Request, Header, HTTPException, status

logger = logging.getLogger("aura.auth")

# In-memory storage for the active local session token
_LOCAL_SESSION_TOKEN: Optional[str] = None


def get_local_session_token() -> str:
    """
    Retrieves or initializes the active local session secret token.
    Uses environment variable AURA_SESSION_TOKEN if provided, otherwise generates
    a 256-bit cryptographically secure hex token on startup.
    """
    global _LOCAL_SESSION_TOKEN
    if _LOCAL_SESSION_TOKEN is None:
        env_token = os.environ.get("AURA_SESSION_TOKEN")
        if env_token and len(env_token.strip()) >= 32:
            _LOCAL_SESSION_TOKEN = env_token.strip()
        else:
            _LOCAL_SESSION_TOKEN = secrets.token_hex(32)
        logger.info("Initialized secure local session token.")
    return _LOCAL_SESSION_TOKEN


def reset_local_session_token() -> str:
    """Rotates or resets the local session token (primarily for testing and security rotation)."""
    global _LOCAL_SESSION_TOKEN
    _LOCAL_SESSION_TOKEN = secrets.token_hex(32)
    return _LOCAL_SESSION_TOKEN


def get_auth_headers() -> Dict[str, str]:
    """Returns standard authorization headers containing the active local session token."""
    return {
        "Authorization": f"Bearer {get_local_session_token()}",
        "X-Aura-Session-Token": get_local_session_token()
    }


def verify_local_token(candidate_token: Optional[str]) -> bool:
    """
    Constant-time comparison of the provided candidate token against the active session token.
    Prevents timing attacks.
    """
    if not candidate_token or not isinstance(candidate_token, str):
        return False
    active = get_local_session_token()
    return hmac.compare_digest(candidate_token.strip(), active)


def require_local_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_aura_session_token: Optional[str] = Header(None, alias="X-Aura-Session-Token"),
    x_aura_token: Optional[str] = Header(None, alias="X-Aura-Token")
) -> str:
    """
    FastAPI security dependency protecting privileged state-changing endpoints.
    Accepts tokens via:
      1. Header: Authorization: Bearer <token>
      2. Header: X-Aura-Session-Token: <token>
      3. Header: X-Aura-Token: <token>
    
    Fail-closed behaviors:
      - Missing token: returns 401 Unauthorized
      - Malformed authorization scheme (e.g. Basic ...): returns 403 Forbidden
      - Invalid / mismatch token: returns 403 Forbidden
    """
    candidate: Optional[str] = None

    if x_aura_session_token:
        candidate = x_aura_session_token.strip()
    elif x_aura_token:
        candidate = x_aura_token.strip()
    elif authorization:
        auth_clean = authorization.strip()
        if auth_clean.lower().startswith("bearer "):
            candidate = auth_clean[7:].strip()
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed authorization header. Expected 'Bearer <token>'."
            )

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Missing local session authorization token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not verify_local_token(candidate):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication failed: Invalid local authorization token."
        )

    return candidate

"""
Aura Mail AI - Local API Trust Boundary & Request Authorization (Phase 2).
Provides cryptographically secure local session token generation, filesystem
token storage (with strict 0600 user-only permissions), constant-time verification,
and FastAPI dependencies to protect privileged endpoints from unauthorized or
cross-origin invocation.
"""

import os
import hmac
import secrets
import logging
from pathlib import Path
from typing import Optional, Dict
from fastapi import Request, Header, HTTPException, status

logger = logging.getLogger("aura.auth")

# In-memory storage for the active local session token
_LOCAL_SESSION_TOKEN: Optional[str] = None
TOKEN_FILE_PATH = Path.home() / ".aura_session_token"


def get_local_session_token() -> str:
    """
    Retrieves or initializes the active local session secret token.
    1. Checks in-memory cache.
    2. Checks environment variable AURA_SESSION_TOKEN.
    3. Checks ~/.aura_session_token file (created with 0600 user-only permissions).
    4. Generates a 256-bit cryptographically secure hex token and saves to file (0600).
    """
    global _LOCAL_SESSION_TOKEN
    if _LOCAL_SESSION_TOKEN is not None:
        return _LOCAL_SESSION_TOKEN

    env_token = os.environ.get("AURA_SESSION_TOKEN")
    if env_token and len(env_token.strip()) >= 32:
        _LOCAL_SESSION_TOKEN = env_token.strip()
        logger.info("Initialized local session token from environment.")
        return _LOCAL_SESSION_TOKEN

    # Check local filesystem token file
    try:
        if TOKEN_FILE_PATH.is_file():
            saved_token = TOKEN_FILE_PATH.read_text(encoding="utf-8").strip()
            if len(saved_token) >= 32:
                _LOCAL_SESSION_TOKEN = saved_token
                logger.info("Loaded local session token from user token file.")
                return _LOCAL_SESSION_TOKEN
    except Exception as e:
        logger.warning(f"Could not read session token file: {e}")

    # Generate new cryptographically secure 256-bit entropy token
    new_token = secrets.token_hex(32)
    _LOCAL_SESSION_TOKEN = new_token
    try:
        # Create with strict 0600 permissions (user-read/write only)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(str(TOKEN_FILE_PATH), flags, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_token)
        os.chmod(str(TOKEN_FILE_PATH), 0o600)
        logger.info("Generated and saved secure local session token to ~/.aura_session_token (0600).")
    except Exception as e:
        logger.warning(f"Could not write session token to disk ({e}); keeping in-memory only.")

    return _LOCAL_SESSION_TOKEN


def reset_local_session_token() -> str:
    """Rotates or resets the local session token (primarily for testing and security rotation)."""
    global _LOCAL_SESSION_TOKEN
    new_token = secrets.token_hex(32)
    _LOCAL_SESSION_TOKEN = new_token
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(str(TOKEN_FILE_PATH), flags, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_token)
        os.chmod(str(TOKEN_FILE_PATH), 0o600)
    except Exception:
        pass
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

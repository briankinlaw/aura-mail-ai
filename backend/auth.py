"""
Aura Mail AI - Local Desktop Request Authorization & Browser Origin Protection (Phase 2).
Provides cryptographically secure session token management, constant-time verification,
FastAPI dependencies protecting privileged endpoints from unauthorized/cross-origin browser invocation,
and server-side Origin verification as defense in depth.

Approved Threat Model:
- In-Scope: Unauthorized browser origins, cross-site request attacks (CSRF), sandboxed/null
  browser contexts, and accidental unauthenticated API access.
- Out-of-Scope: Malicious software already executing as the logged-in macOS user ($UID),
  same-user filesystem access, or root compromise.
"""

import os
import hmac
import secrets
import logging
import time
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any
from fastapi import Request, Header, HTTPException, status

logger = logging.getLogger("aura.auth")

# Canonical CORS and Origin Allowlist for Local Desktop & Office.js Webview (Phase 2.1)
# Note: Office.js taskpane executes from same-origin https://localhost:8000/add-in/taskpane.html
# Parent framing domains (e.g. outlook.office.com) are controlled separately via CSP frame-ancestors.
ALLOWED_ORIGINS: List[str] = [
    "https://localhost:8000",
]

# Allow optional development origins on port 3000 only when explicitly configured
if os.environ.get("AURA_DEV_MODE") == "1" or os.environ.get("AURA_ALLOW_PORT_3000") == "1":
    ALLOWED_ORIGINS.extend([
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://localhost:3000",
        "https://127.0.0.1:3000",
    ])


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
    x_aura_token: Optional[str] = Header(None, alias="X-Aura-Token"),
    origin: Optional[str] = Header(None)
) -> str:
    """
    FastAPI security dependency protecting privileged state-changing endpoints.
    Accepts tokens via:
      1. Header: Authorization: Bearer <token>
      2. Header: X-Aura-Session-Token: <token>
      3. Header: X-Aura-Token: <token>
    
    Fail-closed behaviors:
      - Origin verification failure (unauthorized or null origin): returns 403 Forbidden
      - Missing token: returns 401 Unauthorized
      - Malformed authorization scheme (e.g. Basic ...): returns 403 Forbidden
      - Invalid / mismatch token: returns 403 Forbidden
    """
    # Server-Side Origin Defense: When present on browser requests, reject unauthorized or null origins
    if origin is not None:
        origin_clean = origin.strip()
        if origin_clean == "null" or origin_clean not in ALLOWED_ORIGINS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Origin verification failed: Unauthorized browser origin '{origin_clean}'."
            )

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


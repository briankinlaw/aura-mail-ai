"""
Aura Mail AI - Local Desktop Request Authorization, Origin Protection, and Peer Enforcement (Phase 6).

Implements:
1. Loopback-only ASGI socket-peer enforcement (defense-in-depth against remote network reachability).
2. Canonical immutable CORS and server-side Origin / Fetch Metadata verification.
3. Strict, unambiguous multi-header credential parsing and conflict rejection.
4. Cryptographically secure constant-time session token verification.
"""

import os
import hmac
import secrets
import logging
import ipaddress
from pathlib import Path
from typing import Optional, Dict, List, Any
from fastapi import Request, Header, HTTPException, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("aura.auth")

# Canonical Origin for Local Desktop & Office.js Webview (Phase 6)
# Immutable: Exactly the canonical local HTTPS origin.
ALLOWED_ORIGINS: List[str] = [
    "https://localhost:8000",
]


class LoopbackPeerMiddleware:
    """
    ASGI middleware enforcing that all incoming connections originate strictly
    from a verified loopback IP address (127.0.0.0/8 or ::1).
    Rejects private LAN, link-local, public, hostname-valued, malformed, or missing client peers.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if not client or not isinstance(client, (list, tuple)) or len(client) < 1:
                response = JSONResponse(
                    {"detail": "Access forbidden: Missing or malformed client socket peer."},
                    status_code=403
                )
                await response(scope, receive, send)
                return

            peer_ip_str = client[0]
            if not isinstance(peer_ip_str, str):
                response = JSONResponse(
                    {"detail": "Access forbidden: Invalid client socket peer representation."},
                    status_code=403
                )
                await response(scope, receive, send)
                return

            try:
                ip_obj = ipaddress.ip_address(peer_ip_str.strip())
                if not ip_obj.is_loopback:
                    response = JSONResponse(
                        {"detail": "Access forbidden: Non-loopback peer address rejected."},
                        status_code=403
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                response = JSONResponse(
                    {"detail": "Access forbidden: Unparseable client IP address rejected."},
                    status_code=403
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


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
    origin: Optional[str] = Header(None),
    sec_fetch_site: Optional[str] = Header(None, alias="Sec-Fetch-Site")
) -> str:
    """
    FastAPI security dependency protecting privileged endpoints.
    Enforces:
    1. Origin verification (when Origin header is supplied, must match canonical origin exactly).
    2. Fetch Metadata verification (Sec-Fetch-Site: cross-site is rejected).
    3. Multi-credential parsing with strict rejection of malformed, empty, duplicate, or conflicting tokens.
    4. Constant-time token verification against the active local session token.
    """
    # 1. Server-Side Origin Defense
    if origin is not None:
        origin_clean = origin.strip()
        if origin_clean == "null" or origin_clean not in ALLOWED_ORIGINS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Origin verification failed: Unauthorized browser origin '{origin_clean}'."
            )

    # 2. Fetch Metadata Verification
    if sec_fetch_site is not None:
        site_clean = sec_fetch_site.strip().lower()
        if site_clean == "cross-site":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Browser context verification failed: Cross-site request rejected."
            )

    # 3. Credential Parsing and Conflict Detection
    provided_tokens: List[str] = []

    if authorization is not None:
        auth_clean = authorization.strip()
        if not auth_clean:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty Authorization header."
            )
        if not auth_clean.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed authorization header. Expected 'Bearer <token>'."
            )
        bearer_val = auth_clean[7:].strip()
        if not bearer_val:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty Bearer token."
            )
        if "," in bearer_val or " " in bearer_val:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed Bearer token."
            )
        provided_tokens.append(bearer_val)

    if x_aura_session_token is not None:
        x_clean = x_aura_session_token.strip()
        if not x_clean:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty X-Aura-Session-Token header."
            )
        if "," in x_clean or " " in x_clean:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed X-Aura-Session-Token header."
            )
        provided_tokens.append(x_clean)

    if x_aura_token is not None:
        xtok_clean = x_aura_token.strip()
        if not xtok_clean:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty X-Aura-Token header."
            )
        if "," in xtok_clean or " " in xtok_clean:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed X-Aura-Token header."
            )
        provided_tokens.append(xtok_clean)

    if not provided_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Missing local session authorization token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Check for conflicting credentials
    first_token = provided_tokens[0]
    for other_tok in provided_tokens[1:]:
        if not hmac.compare_digest(first_token, other_tok):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Conflicting credential headers provided."
            )

    # 4. Constant-Time Verification
    if not verify_local_token(first_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication failed: Invalid local authorization token."
        )

    return first_token

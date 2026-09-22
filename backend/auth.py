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
from typing import Optional, Dict, List, Any, Tuple, Set
from fastapi import Request, Header, HTTPException, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("aura.auth")

# Canonical Origin for Local Desktop & Office.js Webview (Phase 6)
# Immutable: Exactly the canonical local HTTPS origin.
ALLOWED_ORIGINS: List[str] = [
    "https://localhost:8000",
]

# Immutable exact allowlist for legitimate cross-site document navigations (Phase 6.3).
# Permits external identity-provider OAuth callback redirects and Outlook taskpane iframe framing.
CROSS_SITE_NAVIGATION_ALLOWLIST: Set[Tuple[str, str]] = {
    ("GET", "/api/auth/callback"),
    ("GET", "/api/auth/google/callback"),
    ("GET", "/add-in/taskpane.html"),
    ("HEAD", "/add-in/taskpane.html"),
}


# Exact case-sensitive Fetch Metadata protocol tokens (Phase 6.4)
EXACT_FETCH_SITE_TOKENS: Set[str] = {
    "same-origin",
    "same-site",
    "none",
    "cross-site",
}


class LoopbackPeerMiddleware:
    """
    ASGI middleware enforcing that all incoming connections originate strictly
    from a verified loopback IP address (127.0.0.0/8 or ::1).
    Rejects private LAN, link-local, public, hostname-valued, malformed, or missing client peers.
    Also validates that duplicate Host headers are rejected per RFC 9112 Section 7.2 before
    downstream host or routing processing.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            # 1. Peer validation from direct ASGI socket client
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

            # 2. Duplicate Host header check (RFC 9112 Section 7.2)
            raw_headers = scope.get("headers", [])
            host_count = sum(1 for k, _ in raw_headers if k.lower() == b"host")
            if host_count > 1:
                from starlette.responses import PlainTextResponse
                response = PlainTextResponse("Invalid host header", status_code=400)
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


def validate_browser_context(scope: Scope) -> Optional[str]:
    """
    Authoritative structural browser-context validator (Origin and Sec-Fetch-Site).
    Returns None if valid, or an error detail string if invalid/conflicting.
    Shared between BrowserContextValidationMiddleware and require_local_auth().
    """
    # 1. Server-Side Origin Defense
    origin_headers = _get_raw_header_values(scope, "Origin")
    if len(origin_headers) > 1:
        return "Origin verification failed: Duplicate Origin headers rejected."
    elif len(origin_headers) == 1:
        raw_origin = origin_headers[0]
        if not raw_origin or not raw_origin.strip():
            return "Origin verification failed: Empty Origin header rejected."
        if "," in raw_origin:
            return "Origin verification failed: Comma-joined Origin header rejected."
        if raw_origin != raw_origin.strip():
            return "Origin verification failed: Malformed Origin whitespace rejected."
        if raw_origin == "null":
            return "Origin verification failed: Opaque null origin rejected."
        if raw_origin not in ALLOWED_ORIGINS:
            return "Origin verification failed: Unauthorized browser origin rejected."

    # 2. Fetch Metadata Verification
    sec_fetch_headers = _get_raw_header_values(scope, "Sec-Fetch-Site")
    if len(sec_fetch_headers) > 1:
        return "Browser context verification failed: Duplicate Sec-Fetch-Site headers rejected."
    elif len(sec_fetch_headers) == 1:
        site_raw = sec_fetch_headers[0]
        if not site_raw or not site_raw.strip():
            return "Browser context verification failed: Empty Sec-Fetch-Site header rejected."
        if "," in site_raw:
            return "Browser context verification failed: Comma-joined Sec-Fetch-Site header rejected."
        if site_raw != site_raw.strip():
            return "Browser context verification failed: Malformed Sec-Fetch-Site whitespace rejected."
        if site_raw not in EXACT_FETCH_SITE_TOKENS:
            return "Browser context verification failed: Malformed Sec-Fetch-Site value rejected."
        if site_raw == "cross-site":
            if origin_headers:
                return "Browser context verification failed: Cross-site request with Origin rejected."
            method = scope.get("method", "").upper()
            path = scope.get("path", "")

            # Permits top-level OAuth callback completion landing redirects (e.g. /?auth=success&provider=google)
            is_oauth_landing = False
            if method in ("GET", "HEAD") and path in ("/", "/index.html"):
                qs = scope.get("query_string", b"")
                qs_str = qs.decode("utf-8", errors="ignore") if isinstance(qs, bytes) else str(qs or "")
                if "auth=success" in qs_str or "auth_error=" in qs_str:
                    is_oauth_landing = True

            if not is_oauth_landing and (method, path) not in CROSS_SITE_NAVIGATION_ALLOWLIST:
                return "Browser context verification failed: Cross-site request rejected."

    return None


class BrowserContextValidationMiddleware:
    """
    ASGI middleware enforcing structural browser-context validation (Origin and Sec-Fetch-Site)
    on all incoming HTTP requests before CORSMiddleware can process or answer preflights.
    Rejects duplicate, malformed, comma-joined, whitespace-obfuscated, non-canonical Origin,
    or cross-site Fetch Metadata headers fail-closed with 403 Forbidden and zero CORS headers.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            err = validate_browser_context(scope)
            if err is not None:
                response = JSONResponse(
                    {"detail": err},
                    status_code=403
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _get_raw_header_values(scope: Scope, name: str) -> List[str]:
    """
    Extracts all raw values for a given header name from ASGI scope headers,
    matching the header name case-insensitively.
    Preserves every repeated occurrence.
    """
    target_bytes = name.lower().encode("latin-1")
    raw_headers = scope.get("headers", [])
    values: List[str] = []
    for k, v in raw_headers:
        if k.lower() == target_bytes:
            try:
                values.append(v.decode("utf-8"))
            except UnicodeDecodeError:
                values.append(v.decode("latin-1", errors="replace"))
    return values


def require_local_auth(request: Request) -> str:
    """
    FastAPI security dependency protecting privileged endpoints.
    Enforces:
    1. Browser-Context Verification:
       - Uses the authoritative validate_browser_context() parser.
    2. Multi-Header Credential Parsing & Conflict Rejection:
       - Supports Authorization (Bearer), X-Aura-Session-Token, and X-Aura-Token.
       - Duplicate occurrences of any credential header are rejected (even identical values).
       - Empty, comma-joined, whitespace-bearing, or malformed credentials fail closed.
       - If multiple distinct credential mechanisms are provided simultaneously, all normalized values
         must be identical (compatibility policy for clients sending Authorization + X-Aura-Session-Token);
         any conflicting credentials fail closed.
    3. Constant-Time Verification:
       - Verified against the active local session token using constant-time comparison.
       - No credential values appear in logs or error details.
    """
    # 1. Browser-Context Verification
    err = validate_browser_context(request.scope)
    if err is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=err
        )

    # 2. Credential Parsing and Conflict Detection
    provided_tokens: List[Tuple[str, str]] = []

    # 2a. Authorization header
    auth_headers = _get_raw_header_values(request.scope, "Authorization")
    if len(auth_headers) > 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication failed: Duplicate Authorization headers rejected."
        )
    elif len(auth_headers) == 1:
        auth_raw = auth_headers[0]
        auth_trimmed = auth_raw.strip()
        if not auth_trimmed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty Authorization header."
            )
        if not auth_trimmed.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed authorization header. Expected 'Bearer <token>'."
            )
        bearer_val = auth_trimmed[7:]
        if not bearer_val or not bearer_val.strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty Bearer token."
            )
        if bearer_val != bearer_val.strip() or any(c in bearer_val for c in (",", " ", "\t", "\r", "\n")):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed Bearer token."
            )
        provided_tokens.append(("Authorization", bearer_val))

    # 2b. X-Aura-Session-Token header
    session_headers = _get_raw_header_values(request.scope, "X-Aura-Session-Token")
    if len(session_headers) > 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication failed: Duplicate X-Aura-Session-Token headers rejected."
        )
    elif len(session_headers) == 1:
        x_raw = session_headers[0]
        x_trimmed = x_raw.strip()
        if not x_trimmed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty X-Aura-Session-Token header."
            )
        if x_raw != x_trimmed or any(c in x_trimmed for c in (",", " ", "\t", "\r", "\n")):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed X-Aura-Session-Token header."
            )
        provided_tokens.append(("X-Aura-Session-Token", x_trimmed))

    # 2c. X-Aura-Token header
    token_headers = _get_raw_header_values(request.scope, "X-Aura-Token")
    if len(token_headers) > 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication failed: Duplicate X-Aura-Token headers rejected."
        )
    elif len(token_headers) == 1:
        xtok_raw = token_headers[0]
        xtok_trimmed = xtok_raw.strip()
        if not xtok_trimmed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Empty X-Aura-Token header."
            )
        if xtok_raw != xtok_trimmed or any(c in xtok_trimmed for c in (",", " ", "\t", "\r", "\n")):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Malformed X-Aura-Token header."
            )
        provided_tokens.append(("X-Aura-Token", xtok_trimmed))

    # 2d. Check presence
    if not provided_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Missing local session authorization token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # 2e. Cross-mechanism conflict detection & compatibility
    # Compatibility policy: Simultaneous presentation of different valid credential headers
    # (e.g. Authorization and X-Aura-Session-Token) is accepted if and only if all token values are identical.
    first_hdr_name, first_token = provided_tokens[0]
    for other_hdr_name, other_token in provided_tokens[1:]:
        if not hmac.compare_digest(first_token, other_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication failed: Conflicting credential headers provided."
            )

    # 3. Constant-Time Verification
    if not verify_local_token(first_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication failed: Invalid local authorization token."
        )

    return first_token

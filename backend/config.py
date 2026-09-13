import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

from backend.models import UserProfile
from backend.security import get_secret, set_secret, mask_secret, startup_security_audit
from backend.migration import migrate_v1_to_v1_1

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESUMES_DIR = DATA_DIR / "resumes"
SETTINGS_FILE = DATA_DIR / "settings.json"
EMAILS_CACHE_FILE = DATA_DIR / "emails_cache.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
RESUMES_DIR.mkdir(parents=True, exist_ok=True)

# Least-privilege Graph scopes required for New Outlook / M365 Mail Sync
# Mail.ReadWrite: read inbox and create threaded drafts in Drafts folder
# Mail.Send: send approved email replies (SAFE_REVIEW default requires explicit user action)
# User.Read: retrieve authenticated mailbox profile and primary email
# offline_access: token refresh via MSAL
GRAPH_SCOPES = [
    "User.Read",
    "Mail.ReadWrite",
    "Mail.Send"
]

def load_settings() -> Dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return migrate_v1_to_v1_1(SETTINGS_FILE, BASE_DIR)
    
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
            # If settings file contains plain secrets, run migration
            if "gemini_api_key" in settings and settings["gemini_api_key"].startswith("AQ."):
                return migrate_v1_to_v1_1(SETTINGS_FILE, BASE_DIR)
            if not settings.get("user_profile") or settings.get("user_profile", {}).get("full_name") == "Jane Doe":
                settings["user_profile"] = UserProfile().model_dump()
            return settings
    except Exception:
        return migrate_v1_to_v1_1(SETTINGS_FILE, BASE_DIR)

def save_settings(settings: Dict[str, Any]):
    # Ensure no secrets accidentally leak into settings.json
    clean_settings = dict(settings)
    if "gemini_api_key" in clean_settings and clean_settings["gemini_api_key"]:
        raw_key = clean_settings["gemini_api_key"]
        if not raw_key.startswith("YOUR_") and len(raw_key) > 10:
            set_secret("gemini_api_key", raw_key)
        clean_settings.pop("gemini_api_key", None)
    
    if "google_client_secret" in clean_settings and clean_settings["google_client_secret"]:
        raw_gsec = clean_settings["google_client_secret"]
        if len(raw_gsec) > 3:
            set_secret("google_client_secret", raw_gsec)
        clean_settings.pop("google_client_secret", None)
    
    if "imap_config" in clean_settings:
        cfg = clean_settings["imap_config"]
        if isinstance(cfg, dict) and "password" in cfg:
            pwd = cfg.pop("password", "")
            if pwd and "email" in cfg:
                set_secret(f"imap_password_{cfg['email']}", pwd)
    
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_settings, f, indent=2)

def get_user_profile() -> UserProfile:
    settings = load_settings()
    profile_data = settings.get("user_profile", {})
    return UserProfile(**profile_data)

def update_user_profile(profile: UserProfile):
    settings = load_settings()
    settings["user_profile"] = profile.model_dump()
    save_settings(settings)

# Canonical HTTPS Origin for Aura Mail AI (Phase 2.1)
CANONICAL_ORIGIN = "https://localhost:8000"

def get_ssl_context_paths() -> tuple:
    """
    Resolves locally trusted development TLS certificate and private key paths.
    1. Checks environment variables AURA_SSL_CERT and AURA_SSL_KEY.
    2. Checks standard user directory ~/.aura_certs/localhost.pem and localhost-key.pem.
    Returns (cert_path, key_path) if both exist, else (None, None).
    """
    cert_env = os.getenv("AURA_SSL_CERT")
    key_env = os.getenv("AURA_SSL_KEY")
    if cert_env or key_env:
        if cert_env and key_env:
            cert_p, key_p = Path(cert_env), Path(key_env)
            if cert_p.is_file() and key_p.is_file():
                return cert_p, key_p
        return None, None

    default_dir = Path.home() / ".aura_certs"
    default_cert = default_dir / "localhost.pem"
    default_key = default_dir / "localhost-key.pem"
    if default_cert.is_file() and default_key.is_file():
        return default_cert, default_key

    return None, None

def require_ssl_context_paths() -> tuple:
    """
    Resolves locally trusted development TLS certificate and private key paths.
    Enforces fail-closed behavior: raises RuntimeError if either certificate or private key is missing.
    Returns (cert_path, key_path) when both files exist.
    """
    cert_p, key_p = get_ssl_context_paths()
    if not cert_p or not key_p:
        raise RuntimeError(
            "FATAL: Missing local TLS certificate or private key for Aura Mail AI.\n"
            "Canonical origin https://localhost:8000 requires HTTPS.\n"
            "Expected certificate: ~/.aura_certs/localhost.pem (or AURA_SSL_CERT)\n"
            "Expected private key:  ~/.aura_certs/localhost-key.pem (or AURA_SSL_KEY)\n"
            "To generate local development certificates with mkcert:\n"
            "  mkdir -p ~/.aura_certs\n"
            "  mkcert -install\n"
            "  mkcert -key-file ~/.aura_certs/localhost-key.pem -cert-file ~/.aura_certs/localhost.pem localhost 127.0.0.1"
        )
    return cert_p, key_p

# Execute startup security check
startup_security_audit(BASE_DIR)

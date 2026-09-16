"""Aura Mail AI - Enterprise Security & Keychain Vault.

Provides secure credential storage via macOS Keychain (keyring),
environment variable fallbacks, secret masking, and startup repository audits.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("aura_security")

SERVICE_NAME = "aura_mail_ai"

# Secret Pattern Signatures for Repository Auditing
SECRET_PATTERNS = [
    ("GEMINI_KEY_OLD", re.compile(r"\bAQ\.[A-Za-z0-9_-]{35,}\b")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIzaSy[A-Za-z0-9_-]{33}\b")),
    ("GENERIC_API_KEY", re.compile(r"""['"](?:api[_-]?key|client[_-]?secret|auth[_-]?token)['"]\s*:\s*['"][a-zA-Z0-9_\-\.]{16,}['"]""", re.IGNORECASE)),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    ("PASSWORD_IN_JSON", re.compile(r"""['"]password['"]\s*:\s*['"][^'"]{4,}['"]""", re.IGNORECASE))
]

def get_keyring():
    try:
        import keyring
        return keyring
    except Exception as e:
        logger.warning(f"Keyring module unavailable: {e}")
        return None

def get_secret(key_name: str, fallback_env: Optional[str] = None) -> Optional[str]:
    """Retrieves a secret from macOS Keychain, falling back to environment variables."""
    kr = get_keyring()
    if kr:
        try:
            val = kr.get_password(SERVICE_NAME, key_name)
            if val:
                return val
        except Exception as e:
            logger.debug(f"Keyring read failed for {key_name}: {e}")
    
    # Fallback to Environment Variables
    env_name = fallback_env or key_name.upper()
    return os.getenv(env_name)

def set_secret(key_name: str, secret_value: str) -> bool:
    """Stores a secret securely in macOS Keychain."""
    if not secret_value:
        return False
    kr = get_keyring()
    if kr:
        try:
            kr.set_password(SERVICE_NAME, key_name, secret_value)
            return True
        except Exception as e:
            logger.error(f"Failed to save secret '{key_name}' to Keychain: {e}")
            return False
    return False

def delete_secret(key_name: str) -> bool:
    """Removes a secret from macOS Keychain."""
    kr = get_keyring()
    if kr:
        try:
            kr.delete_password(SERVICE_NAME, key_name)
            return True
        except Exception:
            return False
    return False

def mask_secret(secret_value: Optional[str]) -> str:
    """Returns a safe, masked representation of a secret for UI display."""
    if not secret_value:
        return ""
    if len(secret_value) <= 8:
        return "****"
    return f"{secret_value[:4]}...{secret_value[-4:]}"

def scan_repository_for_secrets(base_dir: Path) -> List[Dict[str, Any]]:
    """Scans repository files for any accidentally exposed secrets or API keys."""
    findings = []
    ignore_dirs = {".git", ".venv", "venv", "node_modules", ".pytest_cache", "__pycache__"}
    scan_exts = {".json", ".py", ".md", ".txt", ".yaml", ".yml", ".env", ".sh"}

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [
            d for d in dirs
            if d not in ignore_dirs
            and not d.startswith(".venv")
            and not d.startswith("venv")
            and not d.startswith(".env")
        ]
        for f in files:
            file_path = Path(root) / f
            # Skip binary and example files
            if file_path.suffix not in scan_exts or file_path.name.endswith(".example"):
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for label, pattern in SECRET_PATTERNS:
                    matches = pattern.findall(content)
                    if matches:
                        # Exclude harmless examples or placeholders
                        for m in matches:
                            if "YOUR_" in m or "example" in m.lower() or "placeholder" in m.lower():
                                continue
                            findings.append({
                                "file": str(file_path.relative_to(base_dir)),
                                "rule": label,
                                "matched_sample": mask_secret(m if isinstance(m, str) else m[0])
                            })
            except Exception:
                continue

    return findings

def startup_security_audit(base_dir: Path):
    """Executes on startup. Emits warnings if unmasked secrets are detected in repository files."""
    findings = scan_repository_for_secrets(base_dir)
    if findings:
        logger.warning("=" * 70)
        logger.warning("🚨 SECURITY WARNING: Potential unmanaged secrets detected in files:")
        for finding in findings:
            logger.warning(f"   - File: {finding['file']} | Type: {finding['rule']}")
        logger.warning("Ensure runtime secrets are stored in macOS Keychain, not tracked JSON files.")
        logger.warning("=" * 70)
    else:
        logger.info("🔒 Startup Security Audit: Repository configuration files verified sanitized.")

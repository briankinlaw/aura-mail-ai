# Security Remediation & Secrets Audit Report (v1.1)

**Date**: September 10, 2026  
**Project**: Aura Mail AI  
**Classification**: Engineering Security Advisory  

---

## 1. Incident Remediation: Compromised Gemini Key in v1.0

### Background
In v1.0, an unmasked Google Gemini API key was stored in the tracked repository file `data/settings.json`.

### Remediation Actions Taken
1. **Compromised Key Treatment**: The key has been marked as compromised and purged from all tracked files, templates, and distributable archives.
2. **Mandatory Revocation Notice**:
   > [!CAUTION]
   > **ACTION REQUIRED OUTSIDE THE APPLICATION**: The original Gemini API key must be manually revoked and replaced in [Google AI Studio](https://aistudio.google.com/) or the Google Cloud Console. Aura Mail AI does not attempt to revoke API keys programmatically.
3. **Repository History Checkpoint**: Legacy state was isolated on branch `v1.0-legacy-checkpoint`. The active `main` branch has untracked `data/settings.json`.
4. **Purge of Legacy Archives**: The untracked archive `outlook-ai-assistant-v1.0-peer-review.zip` was permanently deleted.

---

## 2. Hardened Secret Management Architecture

### macOS Keychain Vault Integration
- Aura Mail AI v1.1 integrates Python `keyring` backed by the native **macOS Keychain** (`keyring.backends.macOS.Keyring`).
- Secrets managed in Keychain:
  - Google Gemini API Key (`gemini_api_key`)
  - Microsoft Graph OAuth Tokens & MSAL Caches (`msal_cache_<account_id>`, `graph_token_<account_id>`)
  - Gmail API Access & Refresh Tokens (`gmail_access_<account_id>`, `gmail_refresh_<account_id>`)
  - IMAP/SMTP Passwords (`imap_password_<account_id>`)

### On-Disk Sanitization
- `data/settings.json` contains only non-secret user preferences, role models, and account metadata.
- `data/settings.json.example` contains only sanitized placeholder values (`YOUR_GEMINI_API_KEY_HERE`).

---

## 3. Automated Security Guards

1. **Startup Security Scanner** ([backend/security.py](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/security.py)):
   - Analyzes all `.json`, `.py`, `.yaml`, `.env`, and `.sh` files in the repository during boot.
   - Detects API key regex signatures (`AQ.*`, `AIzaSy*`, RSA/EC private keys, JSON password blocks).
   - Emits prominent console warnings if unmasked secrets are detected.
2. **Automated Test Guard** ([backend/tests/test_multi_account.py](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/tests/test_multi_account.py)):
   - `test_repository_secrets_sanitized()` scans the repository during `pytest` runs and fails if any secrets are present.
3. **Git Tracking Lockdown** ([.gitignore](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/.gitignore)):
   - Ignores `data/settings.json`, `data/analytics.db*`, `data/emails_cache.json`, `token_cache*`, `*.bin`, `.env*`, and `*.zip`.

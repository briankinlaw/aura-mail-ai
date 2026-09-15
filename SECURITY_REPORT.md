# Security & Architecture Audit Report (v1.1)

**Date**: September 13, 2026  
**Project**: Aura Mail AI  
**Classification**: Engineering Security & Compliance Advisory  

---

## 1. Executive Summary & Security Posture

Aura Mail AI implements a multi-layered local-desktop defense-in-depth architecture designed for executive recruitment workflows, cloud synchronization, and native Microsoft Outlook integration. For the complete approved threat model, boundary definitions, and route inventory, see [THREAT_MODEL.md](file:///Users/briankinlaw/aura-mail-ai/THREAT_MODEL.md).

### Core Security Principles Enforced:
1. **Zero Secret Persistence on Disk**: All API keys, OAuth refresh tokens, and IMAP credentials are vault-isolated in the **macOS Keychain** (`keyring`).
2. **Strict Draft-First Policy & Native Send**: The system is architecturally incapable of autonomously sending outbound emails without explicit human staging and review. Aura's local API has zero transmission authority.
3. **Localhost Trust Boundary**: Strict loopback-only peer verification, exact approved Host allowlisting, immutable canonical CORS (`https://localhost:8000`), server-side Origin verification, and purpose-bound, single-use, expiring OAuth state transactions.
4. **Dual-Model Risk Sentinel (Second Opinion)**: Inbound opportunities and generated drafts are audited by an independent **Gemini Risk Sentinel** that flags unverified claims, compensation commitments, and external threats.
5. **Office.js Surface Isolation**: The Native Outlook Add-in is constrained to `ReadWriteItem` permissions and serves taskpane assets via CSP frame-ancestors.

---

## 2. Hardened Secret Management Architecture

### macOS Keychain Vault Integration
- Aura Mail AI integrates Python `keyring` backed by the native **macOS Keychain** (`keyring.backends.macOS.Keyring`).
- Secrets managed in Keychain:
  - Google Gemini API Key (`gemini_api_key`)
  - Microsoft Graph OAuth Tokens & MSAL Caches (`msal_cache_<account_id>`, `graph_token_<account_id>`)
  - Gmail API Access & Refresh Tokens (`gmail_access_<account_id>`, `gmail_refresh_<account_id>`)
  - IMAP Passwords (`imap_password_<account_id>`)

### On-Disk Sanitization
- `data/settings.json` contains only non-secret user preferences, role models, and account metadata.
- `data/settings.json.example` contains only sanitized placeholder values (`YOUR_GEMINI_API_KEY_HERE`).

---

## 3. Native Outlook Web Add-in Security Model

### Office.js Permissions
- **Permission Level**: `ReadWriteItem`
- **Scope**: Scoped strictly to the active message item being read or composed.
- **Form Factors**: Declares `MessageReadCommandSurface` and `MessageComposeCommandSurface` ribbon buttons.
- **Zero Third-Party Data Exfiltration**: Office.js interactions execute locally between the Outlook client and the local/authenticated Aura Mail AI backend server.

---

## 4. Gemini Risk Sentinel (Independent Second Opinion)

To safeguard against unintended commitments or metric drift, `backend/radar/risk_evaluator.py` provides:
- **Heuristic Pre-Screen**: Real-time evaluation of phishing URLs, shortened links, and unverified phrasing.
- **Gemini Adversarial Audit**: Independent LLM second-opinion evaluation against Brian Kinlaw's Canonical Accomplishment Ledger ($8M Google Cloud, $100M+ enterprise revenue).
- **Automated Quarantine**: Action ratings (*SAFE*, *CAUTION*, *BLOCKED*) presented to the executive before any reply is staged.

---

## 5. Automated Security Guards & Verification

1. **Startup Security Scanner** ([`backend/security.py`](file:///Users/briankinlaw/aura-mail-ai/backend/security.py)):
   - Analyzes all `.json`, `.py`, `.yaml`, `.env`, and `.sh` files in the repository during boot.
   - Detects API key regex signatures (`AQ.*`, `AIzaSy*`, RSA/EC private keys, JSON password blocks).
2. **Automated Test Guard** ([`backend/tests/test_multi_account.py`](file:///Users/briankinlaw/aura-mail-ai/backend/tests/test_multi_account.py)):
   - `test_repository_secrets_sanitized()` scans the entire repository during `pytest` runs and fails if any secrets are present.
3. **Automated Test Suite**:
   - **Comprehensive automated test suite passing across all modules** (0 failures).

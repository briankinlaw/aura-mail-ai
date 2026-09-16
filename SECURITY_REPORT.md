# Security & Architecture Audit Report (v1.1)

**Date**: September 15, 2026
**Project**: Aura Mail AI
**Classification**: Engineering Security & Compliance Advisory

---

## 1. Executive Summary & Security Posture

Aura Mail AI implements a multi-layered local-desktop defense-in-depth architecture designed for executive recruitment workflows, cloud synchronization, and native Microsoft Outlook integration. For the complete approved threat model, boundary definitions, and route inventory, see [THREAT_MODEL.md](file:///Users/briankinlaw/aura-mail-ai/THREAT_MODEL.md).

### Core Security Principles Enforced:

1. **Zero Secret Persistence on Disk**: All API keys, OAuth refresh tokens, and IMAP credentials are vault-isolated in the **macOS Keychain** (`keyring.backends.macOS.Keyring`).
2. **Strict Draft-First Policy & Native Send Invariant**:
   - Invariant: `ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN`.
   - **`DRAFT_ONLY`**: Direct mail transmission by Aura is forbidden. Aura generates, triages, and stages drafts locally or in cloud drafts.
   - **`MANUAL_SEND_ONLY`**: Direct mail transmission by Aura is also forbidden. Aura prepares and stages drafts; final outbound transmission is executed exclusively by the human operator through their native mail client (Outlook / Gmail / Webmail).
   - Aura application routes expose zero outbound mail transmission endpoints (`send_reply` fails closed with `SEND_FORBIDDEN`).
3. **Provider Capability vs Application Capability vs Authorization**:
   - **Provider Technical Capability**: What a cloud credential may technically permit on the provider's API.
   - **Aura Application Capability**: What code paths exist in the application (read, triage, draft compose/stage, folder management; zero transmission routes).
   - **Aura Authorization**: What Aura policy permits (drafting and staging only; direct transmission forbidden).
   - Microsoft Graph configuration omits direct send (`Mail.Send` is omitted).
   - Gmail configuration declares `gmail.modify`; while Google OAuth tokens may technically permit broader provider API actions, Aura's application code intentionally exposes no direct-send execution, and Aura policy strictly forbids direct transmission.
4. **Localhost Trust Boundary & Threat Model**: Strict loopback-only peer verification, exact approved Host allowlisting, immutable canonical CORS (`https://localhost:8000`), pre-CORS `Sec-Fetch-Site` browser-context verification, and purpose-bound, single-use, expiring OAuth state transactions. The local session credential protects against remote web origins and cross-site requests, but is not an OS-level isolation boundary against arbitrary same-user local processes. CORS is a browser-origin policy control, not caller authentication.
5. **Dual-Model Risk Sentinel (Second Opinion)**: Inbound opportunities and generated drafts are audited by an independent **Gemini Risk Sentinel** operating under a monotonic risk floor (`FINAL_RISK >= DETERMINISTIC_RISK`). Gemini/LLM output cannot downgrade deterministic findings. Normalization resolves contradictory signals upward without fabricating evidence. `SAFE` / `PROCEED` does not authorize mail transmission.
6. **Information-Integrity Grounding**: Draft generation is constrained to verified metrics from Brian Kinlaw's Canonical Accomplishment Ledger ($8M Google Cloud, $100M+ enterprise revenue), operating as an information-integrity control that reduces unsupported generation risk.
7. **Calendar Availability Provenance**: Distinguishes proposed booking windows from trusted provider-verified availability (`CALENDAR_VERIFIED_CLEAR`, `CALENDAR_VERIFIED_WITH_CONFLICTS`). Verified availability requires trusted server-side provider execution; untrusted caller assertions strictly remain `CALENDAR_NOT_CHECKED`.
8. **Office.js Surface Isolation & Untrusted Content Escaping**: The Native Outlook Add-in is constrained to `ReadWriteItem` permissions and serves taskpane assets over HTTPS localhost (`https://localhost:8000`). All model-generated and user-controlled reply text is treated as untrusted content and HTML-escaped at the rendering boundary (`formatReplyAsSafeHtml`).
9. **Offline Recovery Authority**: Administrative provenance store recovery is strictly an offline maintenance tool executed via CLI (`scripts/aura-recover-provenance`) outside the running FastAPI HTTP server.

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

## 3. Provider Capabilities, Scopes, and Boundaries

### Provider Scope Truth Table

| Provider | Declared Scope | Provider Technical Capability | Aura Exposed Application Capability | Aura Policy Authorization |
| :--- | :--- | :--- | :--- | :--- |
| **Microsoft Graph** | `User.Read`, `Mail.ReadWrite`, `offline_access` | Read/write mail, create drafts, manage folders (`Mail.Send` omitted) | Read inbox, compose/stage drafts, upload attachments, manage folders | Staging and inbox reading only; direct mail transmission forbidden |
| **Gmail API** | `https://www.googleapis.com/auth/gmail.modify` | Read/write mail, create drafts, modify labels (Token technically permits broader provider actions) | Read inbox, compose/stage MIME drafts, label quarantine/trash | Staging and inbox reading only; direct mail transmission forbidden |
| **RFC 3501 IMAP** | User-configured mailbox credentials | Read/append/delete mailbox messages | Read inbox, append MIME drafts directly to Drafts folder | Staging and inbox reading only; direct mail transmission forbidden |
| **Demo Provider** | None (in-memory mock data) | Isolated mock generation | Offline sandbox triage and draft simulation | Sandboxed simulation; transmission impossible |

---

## 4. Gemini Risk Sentinel (Independent Second Opinion)

To safeguard against unintended commitments or metric drift, `backend/radar/risk_evaluator.py` provides:
- **Heuristic Pre-Screen**: Real-time deterministic evaluation of phishing URLs, shortened links, compensation commitments, and unverified phrasing.
- **Monotonic Security Floor**: `FINAL_RISK >= DETERMINISTIC_RISK`. Gemini/LLM output cannot downgrade deterministic security findings below the heuristic floor.
- **Universal Upward Normalization**: Resolves contradictory signals upward to the strongest valid security rank without fabricating evidence.
- **Decision Verdict**: `SAFE` / `PROCEED` indicates that evaluated content passed the Risk Sentinel decision process for the exact evaluated draft; it never acts as mail transmission authorization.
- **Exact-Draft Correlation**: Verification state is bound to the exact content hash of the draft; manual edits or regeneration invalidate prior verification and fail closed until re-audited.

---

## 5. Information-Integrity Grounding

- **Accomplishment Ledger Binding**: Draft responses are strictly bounded by verified accomplishments from `Accomplishment_Ledger_CURRENT.docx` ($8M Google Cloud revenue influenced, $100M+ enterprise platform revenue delivered, Promevo pipeline $2M+).
- **Control Classification**: Operates as an **information-integrity control**, reducing unsupported generation risk and binding claims to canonical evidence.

---

## 6. Calendar Availability & Verification Provenance

- **Availability States**:
  - `CALENDAR_NOT_CHECKED`: Default initial state or unverified caller request.
  - `CALENDAR_VERIFIED_CLEAR`: Server-side provider execution confirmed zero calendar conflicts.
  - `CALENDAR_VERIFIED_WITH_CONFLICTS`: Server-side provider execution detected calendar conflicts.
  - `CALENDAR_UNAVAILABLE`: Calendar provider unreachable or disabled.
  - `CALENDAR_ERROR`: Provider query encountered an unhandled error.
- **Trust Boundary**: Verified states require trusted server-side `TrustedCalendarEvidence`; untrusted client assertions are strictly rejected.

---

## 7. Native Outlook Web Add-in Security Model

### Office.js Permissions & Boundary
- **Permission Level**: `ReadWriteItem`
- **Scope**: Scoped strictly to the active message item being read or composed.
- **Transport**: Requires HTTPS localhost (`https://localhost:8000`).
- **Cloud Draft Staging**: Dispatches to `POST /api/emails/{id}/save-draft` and requires provider-confirmed `remote_object_id` before reporting success.
- **Untrusted Generated Content Escaping**: All model-generated and user-controlled reply text is treated as untrusted content and HTML-escaped at the rendering boundary (`formatReplyAsSafeHtml`) before injection into Outlook.
- **Native Send Boundary**: Aura prepares and stages drafts; final outbound transmission is executed exclusively by the user via Outlook's native Send button.

---

## 8. Offline Recovery Authority

- **Isolation**: Administrative provenance store recovery is strictly an offline maintenance utility executed via CLI (`scripts/aura-recover-provenance`).
- **Safeguards**: Requires an interactive terminal/TTY, validates runtime lock files to ensure the backend is offline, and is completely isolated from the running HTTP API.

---

## 9. Automated Security Guards & Verification

1. **Startup Security Scanner** ([`backend/security.py`](file:///Users/briankinlaw/aura-mail-ai/backend/security.py)):
   - Analyzes all `.json`, `.py`, `.yaml`, `.env`, and `.sh` files in the repository during boot.
   - Detects API key regex signatures (`AQ.*`, `AIzaSy*`, RSA/EC private keys, JSON password blocks) while excluding virtual environments.
2. **Automated Test Guards**:
   - `test_repository_secrets_sanitized()` scans the repository during `pytest` runs and fails if any secrets are present.
   - Comprehensive automated unit and integration suites in `backend/tests/` (1006 tests passing, 0 failures).
   - Dedicated JavaScript security test suites for Outlook content escaping (48/48), cloud draft staging (52/52), and frontend risk validation (17/17).

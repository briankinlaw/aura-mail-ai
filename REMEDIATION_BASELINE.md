# Aura Mail AI v1.1 — Security Remediation Baseline (Phase 0)

**Baseline Commit**: `6575b38c9539712a20775da73d69760f0db97ae0`  
**Date**: September 13, 2026  
**Status**: Baseline Established & Invariant Verified  

---

## 1. Inventory of Codebase Components

### Production Python Modules
- `backend/main.py`: FastAPI application server & REST routing.
- `backend/models.py`: Pydantic schemas and enums.
- `backend/config.py`: Environment and user settings management.
- `backend/security.py`: macOS Keychain vault & repository secret scanner.
- `backend/ai_agent.py`: Gemini & heuristic email classification.
- `backend/canonical_engine.py`: Canonical Career System indexing & document resolution.
- `backend/analytics.py`: SQLite telemetry, KPIs, and grounding audit stream.
- `backend/desktop_helper.py`: Local macOS process check helpers.
- `backend/daemon.py`: Autonomous background daemon cycle & macOS notifications.
- `backend/daemon_cli.py`: CLI driver & `launchd` plist generator.
- `backend/menubar_app.py`: macOS status bar companion app (`rumps`).

### Subsystem Packages
- `backend/radar/`:
  - `triage_service.py`: Opportunity Radar triage & fit scoring.
  - `scribe_service.py`: Grounded recruiter reply synthesis.
  - `risk_evaluator.py`: Gemini Risk Sentinel & independent second-opinion auditor.
- `backend/calendar_broker/`:
  - `availability_service.py`: Working-hour free/busy booking window calculation.
  - `models.py`: Calendar slot data models.
- `backend/providers/`:
  - `base.py`: Provider interface abstractions & `ProviderOperationResult`.
  - `graph.py`: Microsoft Graph (MSAL) OAuth & device flow.
  - `gmail.py`: Google Cloud OAuth2 / Gmail API.
  - `imap.py`: RFC 3501 IMAP / SMTP.
  - `demo.py`: Offline mock provider.

### Frontend & Outlook Add-in Modules
- `frontend/index.html`, `app.js`, `style.css`: Web Cockpit Dashboard.
- `frontend/add-in/taskpane.html`, `taskpane.css`, `taskpane.js`: Native Outlook Office.js Add-in Taskpane.
- `manifest.xml`: Outlook Web Add-in manifest definition (`MessageReadCommandSurface`, `MessageComposeCommandSurface`).
- `frontend/icon-*.png`: High-resolution add-in iconography (`16`, `32`, `64`, `80`, `128` px).

---

## 2. Test Execution & Baseline Verification

- **Total Test Count**: 60 automated tests collected across 10 test modules.
- **Results**:
  - `backend/tests/test_addin.py`: 5 passed
  - `backend/tests/test_analytics.py`: 6 passed
  - `backend/tests/test_assistant.py`: 9 passed
  - `backend/tests/test_canonical_engine.py`: 7 passed
  - `backend/tests/test_daemon.py`: 4 passed (including explicit invariant regression test)
  - `backend/tests/test_menubar.py`: 2 passed
  - `backend/tests/test_multi_account.py`: 5 passed
  - `backend/tests/test_providers.py`: 14 passed
  - `backend/tests/test_radar_and_calendar.py`: 4 passed
  - `backend/tests/test_risk_evaluator.py`: 4 passed (5 test functions)
- **Summary**: **60 PASSED, 0 FAILED, 0 SKIPPED** (in 12.31s).
- **Static Compilation**: `python -m compileall backend` completed with 0 errors.
- **Repository Secret Scan**: 0 unmanaged secrets detected across repository files.

---

## 3. Dependency Analysis & Identified Issues

### Undeclared Runtime Dependencies in `requirements.txt`
The following packages are installed in `.venv` and utilized by optional features, but were missing from `requirements.txt`:
1. `rumps` (v0.4.0) — Used by `backend/menubar_app.py`.
2. `pyobjc-core` & `pyobjc-framework-Cocoa` (v10.3.2) — Required backend for macOS native menu bar.
3. `pillow` (v11.3.0) — Used for add-in icon generation.

---

## 4. Permanent Safety Invariants Enforced

1. **`BACKGROUND EXECUTION → SEND FORBIDDEN`**:
   - Explicitly verified by `test_permanent_invariant_daemon_never_calls_send_reply` in `test_daemon.py`.
   - In non-dry-run mode, `run_daemon_cycle()` invokes `save_draft_reply()` and strictly never calls `send_reply()`.
2. **`Zero Plaintext Secrets on Disk`**:
   - All OAuth tokens and passwords remain isolated in macOS Keychain (`keyring`).
3. **`Canonical Grounding & Accomplishment Ledger Accuracy`**:
   - Zero-hallucination constraint matrix enforced across `canonical_engine.py` and `risk_evaluator.py`.
4. **`Provider Abstraction Compatibility`**:
   - Graph, Gmail, IMAP, and Demo providers conform to `ProviderManager` contracts.

---

## 5. Phase 2 Local-Desktop Threat Model & Security Boundaries

### Approved In-Scope Protections
- **Unauthorized Browser Origins**: Enforced via explicit CORS allowlist containing only local desktop and Office.js webview origins (`localhost:8000`, `127.0.0.1:8000`, `localhost:3000`, `127.0.0.1:3000`).
- **Cross-Site Request Attacks (CSRF)**: Prevented via mandatory custom headers (`Authorization: Bearer <token>` or `X-Aura-Session-Token: <token>`) and server-side `Origin` header verification on all privileged endpoints.
- **Sandboxed & Opaque Origins**: `Origin: null` is strictly rejected by CORS preflight and server-side verification.
- **DNS Rebinding & Host Manipulation**: Enforced via `TrustedHostMiddleware` (rejecting any unexpected `Host` header).
- **Accidental Unauthenticated Access**: All 22 state-changing, credential-mutating, or execution-triggering routes require authentication and fail closed (`401 Unauthorized` or `403 Forbidden`).
- **Loopback-Only Network Isolation**: All launchers bind strictly to `127.0.0.1` / `localhost` (zero `0.0.0.0` exposure).

### Explicit Out-of-Scope / Accepted Risks
- **Same-User Process Compromise**: Malicious processes already executing under the same logged-in macOS user account ($UID) operate within the same operating-system privilege domain and can access user-space files (`~/.aura_session_token`), databases, and process memory. Aura does not claim OS-process-level isolation against same-user software.
- **Same-Origin XSS**: If arbitrary JavaScript execution occurs within the same origin (`http://localhost:8000`), in-memory session tokens can be accessed. (CSP hardening is tracked for future UI refinement).
- **Root/Admin Compromise**: System-wide administrative compromise supersedes application-level controls.


# Peer Review & Evaluation Guide (v1.1)

## Aura Mail AI: Executive Outlook Assistant & Canonical Career Co-Pilot

Welcome! This guide provides peer reviewers with a structured walkthrough of the codebase, key design patterns, security controls, risk evaluation mechanisms, and verification instructions.

---

## 🧭 Key Files to Review

| Component | Primary File(s) | Key Review Points |
| :--- | :--- | :--- |
| **Native Outlook Web Add-in** | [`manifest.xml`](file:///Users/briankinlaw/aura-mail-ai/manifest.xml)<br>[`frontend/add-in/`](file:///Users/briankinlaw/aura-mail-ai/frontend/add-in/) | Office.js `MessageReadCommandSurface` & `MessageComposeCommandSurface`, `ReadWriteItem` permission scoping, HTTPS localhost requirement, HTML-escaping of untrusted text (`formatReplyAsSafeHtml`), 1-click cloud draft staging (`POST /api/emails/{id}/save-draft` with `remote_object_id` confirmation), and native client send boundary. |
| **Gemini Risk Sentinel (Second Opinion)** | [`backend/radar/risk_evaluator.py`](file:///Users/briankinlaw/aura-mail-ai/backend/radar/risk_evaluator.py) | Independent AI second-opinion auditor enforcing monotonic risk floor `FINAL_RISK >= DETERMINISTIC_RISK`. Gemini cannot downgrade deterministic findings. Normalization resolves upward without fabricating evidence. Exact-draft hash binding; `SAFE`/`PROCEED` is not send authorization. |
| **Autonomous Background Daemon** | [`backend/daemon.py`](file:///Users/briankinlaw/aura-mail-ai/backend/daemon.py)<br>[`aura-daemon`](file:///Users/briankinlaw/aura-mail-ai/aura-daemon) | macOS `launchd` background service, headless opportunity triage, local notification alerts, idempotent single-cycle (`--once`) & continuous loop (`--loop`). Strict `SEND_FORBIDDEN` invariant. |
| **macOS Menu Bar Companion** | [`backend/menubar_app.py`](file:///Users/briankinlaw/aura-mail-ai/backend/menubar_app.py)<br>[`aura-menubar`](file:///Users/briankinlaw/aura-mail-ai/aura-menubar) | Native macOS status bar tray app (`rumps`), 1-click clipboard booking slot copying, pending lead inspection, web cockpit launcher. |
| **Opportunity Radar & Scribe** | [`backend/radar/triage_service.py`](file:///Users/briankinlaw/aura-mail-ai/backend/radar/triage_service.py)<br>[`backend/radar/scribe_service.py`](file:///Users/briankinlaw/aura-mail-ai/backend/radar/scribe_service.py) | Deterministic 0–100% fit scoring, recruiter detail extraction, evidence-bounded reply generator operating as an information-integrity control tied to Canonical Career System. |
| **Calendar Availability Broker** | [`backend/calendar_broker/`](file:///Users/briankinlaw/aura-mail-ai/backend/calendar_broker/) | Working-hour buffer calculation, Free-Busy time slot extraction, timezone localization, and distinction between proposed availability vs trusted provider-verified availability (`CALENDAR_VERIFIED_CLEAR`, `CALENDAR_VERIFIED_WITH_CONFLICTS`). |
| **Cloud Provider Dispatcher** | [`backend/provider_manager.py`](file:///Users/briankinlaw/aura-mail-ai/backend/provider_manager.py)<br>[`backend/providers/`](file:///Users/briankinlaw/aura-mail-ai/backend/providers/) | Multi-account cloud routing across Microsoft Graph (`Mail.Send` omitted), Google Cloud OAuth (Gmail API, `gmail.modify`), and RFC 3501 IMAP. Explicitly distinguishes provider capability, application capability, and authorization. Fail-closed `send_reply()` returns `SEND_FORBIDDEN`. |
| **macOS Keychain Security & Trust Boundary** | [`backend/security.py`](file:///Users/briankinlaw/aura-mail-ai/backend/security.py)<br>[`backend/auth.py`](file:///Users/briankinlaw/aura-mail-ai/backend/auth.py) | Zero plaintext secrets on disk. Keyring-backed macOS Keychain vault, boot-time repository secret scanner. Localhost session credential binds browser/add-in origin, not an OS-level isolation boundary against same-user processes. CORS is not caller authentication. |
| **Canonical Career Engine** | [`backend/canonical_engine.py`](file:///Users/briankinlaw/aura-mail-ai/backend/canonical_engine.py) | 36-document local indexer, pure-Python OpenXML parser, 3-level role taxonomy matrix, token affinity scoring, locked facts grounding as an information-integrity control. |
| **Telemetry & Observability** | [`backend/analytics.py`](file:///Users/briankinlaw/aura-mail-ai/backend/analytics.py) | SQLite database layer, compensation range parser, conversion funnel metrics, resume ROI tracking, append-only audit stream. |
| **Automated Test Suite** | [`backend/tests/`](file:///Users/briankinlaw/aura-mail-ai/backend/tests/) | **Comprehensive automated unit and security integration test suite** (1006 tests) covering add-in endpoints, risk evaluator, analytics, canonical matching, providers, daemon, safety policy, trust boundary, and menubar. |

---

## 🚀 How to Run and Test Locally

### 1. Prerequisites
- macOS (for native AppleScript Outlook integration, Keychain vault, and Menu Bar app) or Linux/Windows (runs in cloud/web mode).
- Python 3.12 (standardized via `.python-version`).

### 2. Environment Setup
```bash
# Clone or navigate to repository
cd /Users/briankinlaw/aura-mail-ai

# Create virtual environment using Python 3.12
python3.12 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install declared dependencies
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

### 3. Run Automated Tests
```bash
# Run complete Python test suite
.venv/bin/python -m pytest

# Run frontend JavaScript test suites
node backend/tests/test_outlook_content_security.js
node backend/tests/test_stage_cloud_draft.js
node backend/tests/test_frontend_risk_validator.js
```
*Expected Output: All tests pass (collection succeeds, 0 failures)*

### 4. Start the Application
```bash
./run.sh
```
Open **`https://localhost:8000`** (Web Cockpit) or **`https://localhost:8000/add-in/taskpane.html`** (Outlook Add-in Preview).

---

## 🔍 Peer Review Checklist & Evaluation Criteria

### 1. Office.js & Outlook Add-in Security
- [ ] Are `manifest.xml` permissions scoped appropriately (`ReadWriteItem` for item reading and reply composition)?
- [ ] Does CORS middleware in `backend/main.py` properly allow Outlook Web domains without opening insecure wildcards?
- [ ] Is untrusted model/user reply text HTML-escaped at the rendering boundary (`formatReplyAsSafeHtml`) before Outlook insertion?
- [ ] Does cloud draft staging require provider-confirmed `remote_object_id` before reporting success?

### 2. Draft-First Safety Policy & Risk Sentinel
- [ ] Do both `DRAFT_ONLY` and `MANUAL_SEND_ONLY` forbid direct Aura-controlled mail transmission?
- [ ] Is final mail transmission executed exclusively by the user in their native mail client?
- [ ] Does the Gemini Risk Sentinel enforce `FINAL_RISK >= DETERMINISTIC_RISK` without allowing LLM downgrades of deterministic findings?
- [ ] Does upward normalization preserve higher-risk postures without fabricating evidence?
- [ ] Is `SAFE` / `PROCEED` strictly a risk evaluation decision for the exact evaluated draft, rather than mail transmission authorization?

### 3. Secret Management & Keychain Hygiene
- [ ] Are sensitive API keys properly externalized via macOS Keychain and excluded from Git?
- [ ] Does the boot-time secret scanner pass cleanly without reporting any hardcoded keys?
- [ ] Is the localhost session token documented accurately as a browser-binding control rather than an OS-level boundary against same-user local processes?

### 4. LLM Grounding & Information-Integrity Controls
- [ ] Are draft responses strictly constrained to the verified metrics of Brian Kinlaw's Accomplishment Ledger (influencing $8M Google Cloud revenue, $100M+ enterprise revenue)?
- [ ] Is grounding accurately described as an information-integrity control reducing unsupported generation risk?

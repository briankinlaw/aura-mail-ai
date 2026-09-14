# Peer Review & Evaluation Guide (v1.1)

## Aura Mail AI: Executive Outlook Assistant & Canonical Career Co-Pilot

Welcome! This guide provides peer reviewers with a structured walkthrough of the codebase, key design patterns, security controls, risk evaluation mechanisms, and verification instructions.

---

## 🧭 Key Files to Review

| Component | Primary File(s) | Key Review Points |
| :--- | :--- | :--- |
| **Native Outlook Web Add-in** | [`manifest.xml`](file:///Users/briankinlaw/aura-mail-ai/manifest.xml)<br>[`frontend/add-in/`](file:///Users/briankinlaw/aura-mail-ai/frontend/add-in/) | Office.js `MessageReadCommandSurface` & `MessageComposeCommandSurface`, `ReadWriteItem` permission scoping, 1-click reply staging, glassmorphic sidebar UI. |
| **Gemini Risk Sentinel (Second Opinion)** | [`backend/radar/risk_evaluator.py`](file:///Users/briankinlaw/aura-mail-ai/backend/radar/risk_evaluator.py) | Independent AI second-opinion auditor detecting compensation commitments, unverified career claims, phishing links, and enforcing Draft-First policy. |
| **Autonomous Background Daemon** | [`backend/daemon.py`](file:///Users/briankinlaw/aura-mail-ai/backend/daemon.py)<br>[`aura-daemon`](file:///Users/briankinlaw/aura-mail-ai/aura-daemon) | macOS `launchd` background service, headless opportunity triage, local notification alerts, idempotent single-cycle (`--once`) & continuous loop (`--loop`). |
| **macOS Menu Bar Companion** | [`backend/menubar_app.py`](file:///Users/briankinlaw/aura-mail-ai/backend/menubar_app.py)<br>[`aura-menubar`](file:///Users/briankinlaw/aura-mail-ai/aura-menubar) | Native macOS status bar tray app (`rumps`), 1-click clipboard booking slot copying, pending lead inspection, web cockpit launcher. |
| **Opportunity Radar & Scribe** | [`backend/radar/triage_service.py`](file:///Users/briankinlaw/aura-mail-ai/backend/radar/triage_service.py)<br>[`backend/radar/scribe_service.py`](file:///Users/briankinlaw/aura-mail-ai/backend/radar/scribe_service.py) | Deterministic 0–100% fit scoring, recruiter detail extraction, strictly grounded reply generator tied to Canonical Career System. |
| **Calendar Availability Broker** | [`backend/calendar_broker/`](file:///Users/briankinlaw/aura-mail-ai/backend/calendar_broker/) | Working-hour buffer calculation, Free-Busy time slot extraction, timezone localization, and email bullet formatting. |
| **Cloud Provider Dispatcher** | [`backend/provider_manager.py`](file:///Users/briankinlaw/aura-mail-ai/backend/provider_manager.py)<br>[`backend/providers/`](file:///Users/briankinlaw/aura-mail-ai/backend/providers/) | Multi-account cloud routing across Microsoft Graph (MSAL), Google Cloud OAuth (Gmail API), and RFC 3501 IMAP (`mail.twc.com`). |
| **macOS Keychain Security** | [`backend/security.py`](file:///Users/briankinlaw/aura-mail-ai/backend/security.py) | Zero plaintext secrets on disk. Keyring-backed macOS Keychain vault, boot-time repository secret scanner, and automated test guards. |
| **Canonical Career Engine** | [`backend/canonical_engine.py`](file:///Users/briankinlaw/aura-mail-ai/backend/canonical_engine.py) | 36-document local indexer, pure-Python OpenXML parser, 3-level role taxonomy matrix, token affinity scoring, locked facts grounding. |
| **Telemetry & Observability** | [`backend/analytics.py`](file:///Users/briankinlaw/aura-mail-ai/backend/analytics.py) | SQLite database layer, compensation range parser, conversion funnel metrics, resume ROI tracking, append-only audit stream. |
| **Automated Test Suite** | [`backend/tests/`](file:///Users/briankinlaw/aura-mail-ai/backend/tests/) | **152 comprehensive unit and integration tests** covering add-in endpoints, risk evaluator, analytics, canonical matching, providers, daemon, safety policy, trust boundary, and menubar. |

---

## 🚀 How to Run and Test Locally

### 1. Prerequisites
- macOS (for native AppleScript Outlook integration, Keychain vault, and Menu Bar app) or Linux/Windows (runs in cloud/web mode).
- Python 3.9+.

### 2. Environment Setup
```bash
# Clone or navigate to repository
cd /Users/briankinlaw/aura-mail-ai

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Automated Tests
```bash
.venv/bin/pytest backend/tests/ -v
```
*Expected Output: `152 passed in < 15s`*

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

### 2. Draft-First Safety Policy & Risk Sentinel
- [ ] Are email responses staged exclusively in Drafts or clipboard for human executive sign-off? (Zero autonomous send risk).
- [ ] Does the Gemini Risk Sentinel (`risk_evaluator.py`) reliably flag unverified career claims, compensation commitments, and external phishing risks?

### 3. Secret Management & Keychain Hygiene
- [ ] Are sensitive API keys properly externalized via macOS Keychain and excluded from `.gitignore`?
- [ ] Does the boot-time secret scanner pass cleanly without reporting any hardcoded keys?

### 4. LLM Grounding & Hallucination Prevention
- [ ] Are draft responses strictly grounded in the verified metrics of Brian Kinlaw's Accomplishment Ledger (influencing $8M Google Cloud revenue, $100M+ enterprise revenue)?

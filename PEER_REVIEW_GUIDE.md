# Peer Review & Evaluation Guide

## Aura Mail AI: Executive Outlook Assistant & Canonical Career Co-Pilot

Welcome! This guide provides peer reviewers with a structured walkthrough of the codebase, key design patterns, security controls, and verification instructions.

---

## 🧭 Key Files to Review

| Component | Primary File | Key Review Points |
| :--- | :--- | :--- |
| **Cloud Provider Dispatcher** | [`backend/provider_manager.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/provider_manager.py)<br>[`backend/providers/`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/providers/) | Multi-account cloud routing across Microsoft Graph (MSAL), Google Cloud OAuth (Gmail API & Google Workspace), and RFC 3501 IMAP/SMTP (`mail.twc.com`). Composite ID codec (`PROVIDER::ACCOUNT::NATIVE_ID`). |
| **Microsoft Graph Provider** | [`backend/providers/graph.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/providers/graph.py) | MSAL Device Code Flow (`microsoft.com/link`) and Direct OAuth flow with `login_hint` + `prompt=login` account targeting. Independent token caches in macOS Keychain. |
| **Gmail & Google Workspace** | [`backend/providers/gmail.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/providers/gmail.py) | Google OAuth2 token exchange, MIME multipart in-reply-to draft generation, POSIX attachment staging, label-based noise quarantine. |
| **Standard IMAP / SMTP** | [`backend/providers/imap.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/providers/imap.py) | RFC 6154 Special-Use folder discovery, SSL/TLS (`993`) & STARTTLS (`587`), host/port sanitization, and username prefix fallbacks. |
| **macOS Keychain Security** | [`backend/security.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/security.py) | Zero plaintext secrets on disk. Keyring-backed Keychain vault, boot-time repository secret scanner, and automated test guards. |
| **Canonical Career Engine** | [`backend/canonical_engine.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/canonical_engine.py) | 36-document local indexer, pure-Python OpenXML parser, 3-level role taxonomy matrix, token affinity scoring, locked facts grounding. |
| **AI Triage & Agentic Logic** | [`backend/ai_agent.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/ai_agent.py) | Two-tier classification (sub-millisecond heuristic pre-filter + Gemini 3.6 Flash), prompt grounding, 429 rate limit circuit breaker with automatic fallback. |
| **Telemetry & Observability** | [`backend/analytics.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/analytics.py) | SQLite database layer, compensation range parser, conversion funnel metrics, resume ROI tracking, append-only audit stream. |
| **FastAPI Service & Endpoints** | [`backend/main.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/main.py) | REST API structure, CORS middleware, caching synchronization, request validation. |
| **Glassmorphic UI Dashboard** | [`frontend/index.html`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/frontend/index.html)<br>[`frontend/app.js`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/frontend/app.js)<br>[`frontend/style.css`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/frontend/style.css) | Vanilla ES2022 + CSS variables, zero framework dependencies, interactive multi-provider auth modals, responsive glassmorphic cards. |
| **Automated Test Suite** | [`backend/tests/`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/tests/) | 40 comprehensive unit and integration tests covering analytics, canonical matching, multi-account routing, providers, and security. |

---

## 🚀 How to Run and Test Locally

### 1. Prerequisites
- macOS (for native AppleScript Microsoft Outlook automation & Keychain vault) or Linux/Windows (runs in local heuristic/demo mode).
- Python 3.9+.

### 2. Environment Setup
```bash
# Clone or navigate to the repository
cd outlook-ai-assistant

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Automated Tests
```bash
PYTHONPATH=. .venv/bin/pytest backend/tests/ -v
```
*Expected Output: `40 passed in < 40s`*

### 4. Start the Application
```bash
./run.sh
# Or directly:
PYTHONPATH=. .venv/bin/python -m uvicorn backend.main:app --port 8000 --reload
```
Open **`http://127.0.0.1:8000`** in your browser.

---

## 🔍 Peer Review Checklist & Evaluation Criteria

### 1. Architecture & Design Patterns
- [ ] Is the separation of concerns clean between desktop bridge (`outlook_client.py`), canonical indexing (`canonical_engine.py`), AI generation (`ai_agent.py`), and telemetry (`analytics.py`)?
- [ ] Is the fallback architecture resilient? (Does it function seamlessly even when offline or when LLM API limits are reached?)

### 2. Security & Data Privacy
- [ ] Are sensitive API keys properly externalized via environment variables and excluded from `.gitignore`?
- [ ] Does the system enforce local execution boundaries without persisting raw email data to third-party databases?
- [ ] Are historical corporate mailboxes (`dxc.com`, `cdw.com`, `revealwhy.com`) safely excluded from all inbox scans?

### 3. LLM Grounding & Hallucination Prevention
- [ ] Are draft responses strictly grounded in the verified metrics of the candidate's Accomplishment Ledger?
- [ ] Are role taxonomy definitions and resume variant selections justified by candidate experience lenses?

### 4. Code Quality & Maintainability
- [ ] Are Pydantic data models (`backend/models.py`) used consistently for request/response serialization?
- [ ] Are SQLite schemas properly indexed for high-performance KPI and funnel queries?
- [ ] Is the frontend lightweight, fast, and accessible without unnecessary build step dependencies?

---

## 💬 Feedback & Questions
Please provide your review comments, suggestions, or pull requests directly to Brian K. Kinlaw.

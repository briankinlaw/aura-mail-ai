# Peer Review & Evaluation Guide

## Aura Mail AI: Executive Outlook Assistant & Canonical Career Co-Pilot

Welcome! This guide provides peer reviewers with a structured walkthrough of the codebase, key design patterns, security controls, and verification instructions.

---

## 🧭 Key Files to Review

| Component | Primary File | Key Review Points |
| :--- | :--- | :--- |
| **Native macOS Bridge** | [`backend/outlook_client.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/outlook_client.py) | Universal inbox scanning, AppleScript IPC automation, historical account exclusion filter (`dxc.com`, `cdw.com`, `revealwhy.com`), draft creation with POSIX file attachments. |
| **Canonical Career Engine** | [`backend/canonical_engine.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/canonical_engine.py) | 36-document local indexer, pure-Python OpenXML parser, 3-level role taxonomy matrix, token affinity scoring, locked facts grounding. |
| **AI Triage & Agentic Logic** | [`backend/ai_agent.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/ai_agent.py) | Two-tier classification (sub-millisecond heuristic pre-filter + Gemini 3.6 Flash), prompt grounding, 429 rate limit circuit breaker with automatic fallback. |
| **Telemetry & Observability** | [`backend/analytics.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/analytics.py) | SQLite database layer, compensation range parser, conversion funnel metrics, resume ROI tracking, append-only audit stream. |
| **FastAPI Service & Endpoints** | [`backend/main.py`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/main.py) | REST API structure, CORS middleware, caching synchronization, request validation. |
| **Glassmorphic UI Dashboard** | [`frontend/index.html`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/frontend/index.html)<br>[`frontend/app.js`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/frontend/app.js)<br>[`frontend/style.css`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/frontend/style.css) | Vanilla ES2022 + CSS variables, zero framework dependencies, interactive modals, responsive glassmorphic cards. |
| **Automated Test Suite** | [`backend/tests/`](file:///Users/briankinlaw/.gemini/antigravity-ide/scratch/outlook-ai-assistant/backend/tests/) | 22 comprehensive unit tests covering analytics, canonical matching, classification, and API endpoints. |

---

## 🚀 How to Run and Test Locally

### 1. Prerequisites
- macOS (for native AppleScript Microsoft Outlook automation) or Linux/Windows (runs in local heuristic/demo mode).
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
*Expected Output: `22 passed in < 3s`*

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

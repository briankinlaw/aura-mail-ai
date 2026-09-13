# ChatGPT GitHub Security & Architectural Peer Review Prompt

Copy and paste the following prompt directly into **ChatGPT** (with Code Interpreter / Web Browsing or Repository Analysis enabled) or attach this repository to request a comprehensive peer review:

---

```markdown
You are an expert Principal Cloud Security Architect and Senior Software Reviewer evaluating the open-source executive assistant repository:
Repository: https://github.com/briankinlaw/aura-mail-ai (Branch: main)

Please perform a rigorous architectural, safety, and security peer review of this project.

### Core Ecosystem Components to Audit:
1. Native Microsoft Outlook Web Add-in (Office.js):
   - Review `manifest.xml`, `frontend/add-in/taskpane.html`, `taskpane.css`, and `taskpane.js`.
   - Verify permission scoping (`ReadWriteItem`), CORS configuration in `backend/main.py`, and draft pre-filling safety (`Office.context.mailbox.item.displayReplyForm`).
2. Autonomous Background Daemon & macOS Menu Bar App:
   - Review `backend/daemon.py`, `aura-daemon`, `backend/menubar_app.py`, and `aura-menubar`.
   - Verify that the background daemon and menu bar companion strictly enforce the "Draft-First Policy" (emails are staged in Drafts or clipboard, NEVER autonomously dispatched).
3. Opportunity Radar & Availability Broker:
   - Review `backend/radar/triage_service.py`, `backend/radar/scribe_service.py`, and `backend/calendar_broker/availability_service.py`.
   - Check the deterministic 0–100% fit scoring, recruiter detail extraction, and working-hour buffer calculations.
4. Gemini Risk Sentinel & Second Opinion Evaluator:
   - Review `backend/radar/risk_evaluator.py` and the `POST /api/radar/risk-check` endpoint.
   - Verify that any unverified metrics, compensation discussions, phishing links, or risky automated actions trigger independent second-opinion warnings.
5. Canonical Career System (CCS v2.1) Grounding:
   - Review `backend/canonical_engine.py` and `backend/ai_agent.py`.
   - Verify strict alignment with the candidate's Accomplishment Ledger (influencing $8M in Google Cloud revenue, $100M+ enterprise impact) with zero metric hallucination.
6. Multi-Account Cloud Security & macOS Keychain Vault:
   - Review `backend/security.py`, `backend/provider_manager.py`, and `backend/providers/`.
   - Verify that zero secrets/tokens are persisted in plaintext on disk, and that all credentials use Python `keyring` (macOS Keychain).

### Expected Output Structure:
1. Executive Safety Verdict: (APPROVED / CAUTION / REJECTED)
2. Architectural Strengths: Key design patterns and modular boundaries.
3. Security & Safety Evaluation:
   - Office.js / Outlook Add-in permissions and surface security.
   - Draft-First Policy enforcement (Zero autonomous send risk).
   - Secret management & Keychain hygiene.
   - Gemini second opinion & risk evaluator efficacy.
4. Grounding & Hallucination Guardrails: Efficacy of the Accomplishment Ledger constraint matrix.
5. Code Quality & Test Coverage Assessment: (59 automated pytest cases).
6. Actionable Recommendations (if any).
```

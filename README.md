# Aura Mail AI: Executive Outlook Assistant & Canonical Career Co-Pilot

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-22%20passed-brightgreen.svg)](backend/tests/)
[![Architecture](https://img.shields.io/badge/architecture-local%20macOS%20bridge-purple.svg)](ARCHITECTURE.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An intelligent, privacy-first AI desktop assistant and executive dashboard that connects directly to **Microsoft Outlook for Mac**, sweeps away marketing clutter, detects recruiter reachouts across multiple Universal inboxes, matches each opportunity to specialized canonical resumes, and drafts fact-locked responses grounded in verified accomplishments.

---

## 🚀 Key Highlights

1. **Direct macOS Desktop Bridge (Zero-Cloud)**:
   - Connects directly to your running **Microsoft Outlook** client on macOS via AppleScript IPC.
   - Eliminates the need for Azure App Registrations, consumer device login codes, or cloud app passwords.
   - Monitors **6 Universal inboxes** simultaneously while strictly isolating and skipping historical corporate archive accounts (`dxc.com`, `cdw.com`, `revealwhy.com`).

2. **Canonical Career System & Role Taxonomy Matrix**:
   - Indexes **36 local resume variants** and source-of-truth documents across standard canonicals, targeted applications, and master versions.
   - Built-in pure-Python OpenXML parser for `.docx` and `.pdf` files.
   - Matches opportunities against a 3-level executive taxonomy:
     - **Level 3A**: *Advisor / Principal Solutions Architect* (Pre-sales, discovery, enterprise architecture, GTM strategy)
     - **Level 3B**: *Principal Technical Program Manager* (Cross-functional delivery governance, cloud roadmaps)
     - **Level 3C**: *AI Governance & Enterprise Data Leader* (NIST AI RMF, Collibra lineage, compliance)
     - **Field CTO / Technology Strategist**: (Executive transformation, C-suite advisory)
     - **Principal Data Platform & AI Architect**: (Modern Lakehouse, Databricks, GCP BigQuery, Agentic AI)

3. **Strict Fact-Locked Grounding (Zero Hallucination)**:
   - All AI draft responses are strictly bounded by verified metrics from the candidate's **Accomplishment Ledger** ($8M Google Cloud influenced, $100M+ enterprise platform revenue delivered, $2.1M CDW closed services, Promevo $2M+ pipeline).
   - Powered by **Google Gemini 3.6 Flash** with a two-tier sub-millisecond local heuristic pre-filter and 429 rate limit circuit breaker.

4. **Career Intelligence & Telemetry Studio**:
   - SQLite-backed database (`data/analytics.db`) tracking recruiter reachout opportunities.
   - Pipeline velocity conversion funnel (`INBOUND` ➔ `MATCHED` ➔ `DRAFTED` ➔ `REPLIED` ➔ `SCHEDULED`).
   - Stated market compensation distributions (salary & hourly bands by role lens).
   - Resume Variant ROI leaderboard & immutable grounding audit trail.

5. **1-Click Outlook Draft Staging & Direct Sending**:
   - Review AI drafts and click **"Save to Outlook Drafts"** to inject the response directly into Outlook with the matched `.docx`/`.pdf` resume already attached.
   - Batch noise cleanup moves marketing clutter directly to Outlook Trash/Deleted Items.

---

## 📂 Project Structure

```text
outlook-ai-assistant/
├── backend/
│   ├── ai_agent.py             # Gemini 3.6 Flash + Heuristic Classifier & Response Generator
│   ├── analytics.py            # SQLite Telemetry Engine (KPIs, Funnels, Comp, ROI, Audit Log)
│   ├── canonical_engine.py     # 36-Resume Vault Indexer, OpenXML Parser & Lens Matcher
│   ├── config.py               # Settings & User Profile Management
│   ├── main.py                 # FastAPI Application Core & REST Endpoints
│   ├── models.py               # Pydantic Schemas & Enumerations
│   ├── outlook_client.py       # Direct macOS Outlook Client Bridge (AppleScript IPC)
│   └── tests/                  # Automated Test Suite (22 Unit Tests)
│       ├── test_analytics.py
│       ├── test_assistant.py
│       └── test_canonical_engine.py
├── data/
│   ├── analytics.db            # SQLite Telemetry & Audit Database
│   ├── emails_cache.json       # In-Memory Cache Persistence
│   ├── settings.json           # Runtime Configuration & Active Accounts
│   ├── settings.json.example   # Sanitized Configuration Template
│   └── resumes/                # Vault Folder for Local Resume Variants
├── frontend/
│   ├── app.js                  # Frontend Application Controller (Vanilla JS)
│   ├── index.html              # Glassmorphic 5-Tab Dashboard
│   └── style.css               # Design System (Tokens, Animations, Glassmorphism)
├── ARCHITECTURE.md             # In-Depth System Design & Topology Document
├── PEER_REVIEW_GUIDE.md        # Step-by-Step Reviewer Guide & Checklist
├── requirements.txt            # Python Dependencies
├── run.sh                      # 1-Click Startup Script
└── README.md                   # Project Overview
```

---

## ⚡ Quick Start

### 1. Installation
```bash
# Clone the repository
git clone <repository-url>
cd outlook-ai-assistant

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration (Optional)
Copy the example settings file:
```bash
cp data/settings.json.example data/settings.json
```
*(Optional: add your `GEMINI_API_KEY` to `data/settings.json` or export `export GEMINI_API_KEY="..."` for live LLM inference; offline heuristics are enabled by default).*

### 3. Run Automated Tests
```bash
PYTHONPATH=. .venv/bin/pytest backend/tests/ -v
```

### 4. Launch Dashboard
```bash
./run.sh
```
Open your browser to: **`http://127.0.0.1:8000`**

---

## 📖 Documentation Links
- 📐 [**System Architecture & Technical Design (ARCHITECTURE.md)**](ARCHITECTURE.md)
- 🔍 [**Peer Reviewer Walkthrough & Evaluation Guide (PEER_REVIEW_GUIDE.md)**](PEER_REVIEW_GUIDE.md)

---

## 📄 License
MIT License. Developed for executive email triage, career telemetry, and canonical resume orchestration.

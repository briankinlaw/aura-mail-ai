# Aura Mail AI (v1.1): Universal Cloud Multi-Account Assistant & Canonical Career Co-Pilot

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](backend/tests/)
[![Architecture](https://img.shields.io/badge/architecture-cloud%20first%20multi--account-purple.svg)](ARCHITECTURE.md)
[![Security](https://img.shields.io/badge/security-macOS%20Keychain-success.svg)](SECURITY_REPORT.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An intelligent, cloud-first AI assistant and executive dashboard compatible with **New Outlook for Mac**, web email, and mobile clients. Connects across Microsoft Graph, Gmail, and IMAP, sweeps away marketing noise, detects recruiter inquiries across multiple inboxes, matches each opportunity to specialized canonical resumes, and drafts fact-locked responses grounded in verified accomplishments.

---

## 🚀 Key Highlights (v1.1)

1. **Cloud-First Multi-Account Architecture**:
   - Synchronizes directly with **Microsoft Graph API (MSAL)**, **Gmail API**, and **RFC 3501 IMAP**.
   - Created messages and drafts automatically appear in **New Outlook for Mac**, Outlook Web, Gmail, and mobile apps.
   - Monitors active mailboxes simultaneously with alias de-duplication while strictly isolating and skipping historical corporate archive accounts (`dxc.com`, `cdw.com`, `revealwhy.com`).
   - Outbound mail is drafted and staged safely in your cloud `Drafts` folder; final mail transmission is executed exclusively by the user in their native mail client.

2. **macOS Keychain Vault & Security Remediation**:
   - Credentials (API keys, OAuth tokens, and mailbox passwords) are stored exclusively in **macOS Keychain** via Python `keyring`.
   - `data/settings.json` is strictly sanitized and untracked in Git.
   - Automatic boot-time security audit flags any unmasked secrets in repository files.

3. **Canonical Career System & Role Taxonomy Matrix**:
   - Indexes **36 local resume variants** and source-of-truth documents across standard canonicals, targeted applications, and master versions.
   - Built-in pure-Python OpenXML parser for `.docx` and `.pdf` files.
   - Matches opportunities against a 3-level executive taxonomy:
     - **Level 3A**: *Advisor / Principal Solutions Architect* (Pre-sales, discovery, enterprise architecture, GTM strategy)
     - **Level 3B**: *Principal Technical Program Manager* (Cross-functional delivery governance, cloud roadmaps)
     - **Level 3C**: *AI Governance & Enterprise Data Leader* (NIST AI RMF, Collibra lineage, compliance)
     - **Field CTO / Technology Strategist**: (Executive transformation, C-suite advisory)
     - **Principal Data Platform & AI Architect**: (Modern Lakehouse, Databricks, GCP BigQuery, Agentic AI)

4. **Strict Fact-Locked Grounding (Information-Integrity Control)**:
   - All AI draft responses are strictly constrained to verified metrics from the candidate's **Accomplishment Ledger** ($8M Google Cloud influenced, $100M+ enterprise platform revenue delivered, $2.1M CDW closed services, Promevo $2M+ pipeline).
   - Serves as an information-integrity control, binding model generation to canonical evidence and reducing unsupported generation risk.
   - Powered by **Google Gemini 3.6 Flash** with a two-tier sub-millisecond local heuristic pre-filter and 429 rate limit circuit breaker.

5. **Native-Send Safety Invariant & Truthful Staging**:
   - Invariant: `ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN`.
   - **`DRAFT_ONLY`**: Direct mail transmission by Aura is forbidden. Aura generates, triages, and stages drafts locally or in cloud drafts.
   - **`MANUAL_SEND_ONLY`**: Direct mail transmission by Aura is also forbidden. Aura prepares and stages drafts; final outbound transmission is executed exclusively by the human operator through their native mail client (Outlook / Gmail / Webmail).
   - Aura's application routes contain zero outbound mail transmission endpoints (`send_reply` fails closed with `SEND_FORBIDDEN`).

6. **Provider Capability vs Application Capability vs Authorization**:
   - **Provider Technical Capability**: What a cloud credential may technically permit on the provider's API.
   - **Aura Application Capability**: What code paths exist in the application (read, triage, draft compose/stage, folder management; zero transmission routes).
   - **Aura Authorization**: What Aura policy permits (drafting and staging only; direct transmission forbidden).
   - Microsoft Graph configuration omits direct send (`Mail.Send` is omitted).
   - Gmail configuration declares `gmail.modify`; while Google OAuth tokens may technically permit broader provider API actions, Aura's application code intentionally exposes no direct-send execution, and Aura policy strictly forbids direct transmission.

7. **Gemini Risk Sentinel (Second-Opinion Safety Guard)**:
   - Implements a monotonic risk floor: `FINAL_RISK >= DETERMINISTIC_RISK`.
   - Gemini/LLM output cannot downgrade deterministic security findings.
   - Normalization resolves contradictory risk posture upward without fabricating evidence.
   - A `SAFE` / `PROCEED` audit verdict confirms content passed evaluation for the exact evaluated draft, but never serves as mail transmission authorization.
   - Audit state is exact-draft scoped; any subsequent draft modification renders prior audits stale and requires re-evaluation.

8. **Calendar Availability Broker (Proposed vs Verified Availability)**:
   - Distinguishes proposed booking windows from trusted provider-verified availability.
   - Verified availability requires trusted server-side calendar provider execution (`CALENDAR_VERIFIED_CLEAR`, `CALENDAR_VERIFIED_WITH_CONFLICTS`).
   - Caller-supplied assertions or unverified requests strictly remain `CALENDAR_NOT_CHECKED`.

9. **Career Intelligence & Telemetry Studio**:
   - SQLite-backed database (`data/analytics.db`) tracking recruiter reachout opportunities.
   - Pipeline velocity conversion funnel (`INBOUND` ➔ `MATCHED` ➔ `DRAFTED` ➔ `REPLIED` ➔ `SCHEDULED`).
   - Stated market compensation distributions (salary & hourly bands by role lens).
   - Resume Variant ROI leaderboard & immutable grounding audit trail.

---

## 📂 Project Structure

```text
outlook-ai-assistant/
├── backend/
│   ├── ai_agent.py             # Gemini 3.6 Flash + Heuristic Classifier & Response Generator
│   ├── analytics.py            # SQLite Telemetry Engine (KPIs, Funnels, Comp, ROI, Audit Log)
│   ├── auth.py                 # Loopback Peer & Session Token Authentication
│   ├── canonical_engine.py     # 36-Resume Vault Indexer, OpenXML Parser & Lens Matcher
│   ├── config.py               # Settings & Configuration Management
│   ├── daemon.py               # Background Triage Daemon Cycle & Notifications
│   ├── daemon_cli.py           # Background Daemon CLI & launchd Plist Generator
│   ├── desktop_helper.py       # Optional macOS Desktop Status Helper
│   ├── main.py                 # FastAPI Application Core & REST Endpoints
│   ├── menubar_app.py          # Native macOS Menu Bar Companion App (rumps)
│   ├── migration.py            # Settings & Database Migration (v1.0 to v1.1)
│   ├── models.py               # Pydantic Schemas & Enumerations
│   ├── provider_manager.py     # Multi-Account Cloud Dispatcher & Router
│   ├── safety_policy.py        # Mail Safety Policy Engine & Native-Send Invariant
│   ├── security.py             # macOS Keychain Vault & Security Scanner
│   ├── calendar_broker/        # Calendar Availability & Provenance Service
│   │   ├── availability_service.py # Working-Hour Free/Busy Calculation
│   │   └── models.py           # Slot & Trusted Evidence Models
│   ├── providers/              # Cloud Email Providers
│   │   ├── base.py             # Abstract BaseEmailProvider & Composite ID Codec
│   │   ├── demo.py             # Explicit Demo Sandbox Provider
│   │   ├── gmail.py            # Gmail API OAuth Provider (gmail.modify)
│   │   ├── graph.py            # Microsoft Graph API Provider (MSAL)
│   │   └── imap.py             # RFC 3501 IMAP Cloud Provider
│   ├── radar/                  # Opportunity Radar & Scribe Subsystem
│   │   ├── risk_evaluator.py   # Gemini Risk Sentinel & Dual-Model Auditor
│   │   ├── scribe_service.py   # Grounded Recruiter Reply Synthesis
│   │   └── triage_service.py   # Fit Scoring & Recruiter Extraction
│   └── tests/                  # Automated Unit & Security Integration Test Suite
├── data/
│   ├── settings.json.example   # Sanitized Configuration Template
│   └── resumes/                # Vault Folder for Local Resume Variants
├── frontend/
│   ├── app.js                  # Frontend Controller (Vanilla JS)
│   ├── index.html              # Glassmorphic Multi-Tab Dashboard
│   ├── style.css               # Design System (Tokens, Animations, Glassmorphism)
│   └── add-in/                 # Native Outlook Office.js Web Add-in
│       ├── taskpane.html       # Add-in Sidebar Interface
│       ├── taskpane.css        # Add-in Stylesheet
│       └── taskpane.js         # Add-in Controller & Cloud Staging Workflow
├── scripts/
│   ├── aura-recover-provenance # Offline CLI Provenance Recovery Tool
│   └── smoke_test_live.py      # Read-Only Live Diagnostics & Smoke Test
├── manifest.xml                # Native Outlook Web Add-in Manifest
├── ARCHITECTURE.md             # In-Depth System Design & Topology Document
├── MAC_SMOKE_TEST_CHECKLIST.md # macOS & New Outlook Step-by-Step Validation Checklist
├── MIGRATION_v1.0_to_v1.1.md   # Upgrade & Configuration Migration Guide
├── PEER_REVIEW_GUIDE.md        # Codebase Walkthrough & Peer Review Guide
├── SECURITY_REPORT.md          # Security Remediation & Secrets Audit Report
├── THREAT_MODEL.md             # Local Desktop Threat Model & Boundary Specification
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
cd aura-mail-ai

# Create virtual environment (Python 3.12 standardized via .python-version)
python3.12 -m venv .venv

# Upgrade pip and install declared dependencies
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

### 2. Cloud Account Setup & Permissions

#### A. Microsoft Graph Setup (Outlook.com / M365)
1. Go to [Microsoft Entra Admin Center](https://entra.microsoft.com) ➔ **App registrations** ➔ **New registration**.
2. Name: `Aura Mail AI`.
3. Supported account types: `Accounts in any organizational directory and personal Microsoft accounts`.
4. Redirect URI: `Public client/native (mobile & desktop)` ➔ `https://localhost:8000/api/auth/callback`.
5. Under **API permissions**, add delegated permissions:
   - `Mail.ReadWrite` (Read inboxes and stage drafts in Drafts folder)
   - `User.Read` (Profile resolution)
   - `offline_access` (Token refresh)
   *(Note: `Mail.Send` is strictly omitted from Graph scopes)*
6. Copy the **Application (client) ID** and paste it into Aura Mail AI **Engine Settings**.

#### B. Google Cloud / Gmail API Setup
1. In Google Cloud Console, configure OAuth 2.0 Client ID (Desktop application).
2. Required OAuth scope: `https://www.googleapis.com/auth/gmail.modify` (consolidated scope for inbox fetch, MIME draft composition, and quarantine labels).
3. While Google's permission model grants broad API capabilities under `gmail.modify`, Aura's application code contains zero transmission execution paths, and Aura policy strictly forbids direct mail transmission.

#### C. Spectrum / Custom IMAP Setup
- In the **Cloud Accounts** tab, select **Connect New Account** ➔ **IMAP**.
- Passwords are saved directly to your **macOS Keychain**.
- Outbound responses are appended directly to your cloud **Drafts** folder for native client review and dispatch.

### 3. Run Automated Tests
```bash
# Run full Python test suite
.venv/bin/python -m pytest

# Run frontend JavaScript test suites (Node 24 standardized via .nvmrc)
node backend/tests/test_outlook_content_security.js
node backend/tests/test_stage_cloud_draft.js
node backend/tests/test_frontend_risk_validator.js
```

### 4. Run Live Read-Only Smoke Test
```bash
.venv/bin/python scripts/smoke_test_live.py
```

### 5. Launch Dashboard
```bash
./run.sh
```
Open your browser to: **`https://localhost:8000`**

---

## 📖 Documentation Links
- 📐 [**System Architecture & Technical Design (ARCHITECTURE.md)**](ARCHITECTURE.md)
- 🔒 [**Security & Architecture Audit Report (SECURITY_REPORT.md)**](SECURITY_REPORT.md)
- 🛡️ [**Local Desktop Threat Model (THREAT_MODEL.md)**](THREAT_MODEL.md)
- 🧭 [**Peer Review & Evaluation Guide (PEER_REVIEW_GUIDE.md)**](PEER_REVIEW_GUIDE.md)
- 🔄 [**Migration Guide v1.0 ➔ v1.1 (MIGRATION_v1.0_to_v1.1.md)**](MIGRATION_v1.0_to_v1.1.md)
- 📋 [**macOS Smoke Test Checklist (MAC_SMOKE_TEST_CHECKLIST.md)**](MAC_SMOKE_TEST_CHECKLIST.md)
- 🧩 [**Outlook Add-in Setup Guide (OUTLOOK_ADDIN_SETUP.md)**](OUTLOOK_ADDIN_SETUP.md)

---

## 📄 License
MIT License. Developed for executive email triage, career telemetry, and canonical resume orchestration.

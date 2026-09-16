# Aura Mail AI (v1.1): Universal Cloud Multi-Account Assistant & Canonical Career Co-Pilot

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-40%20passed-brightgreen.svg)](backend/tests/)
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

4. **Strict Fact-Locked Grounding (Zero Hallucination)**:
   - All AI draft responses are strictly bounded by verified metrics from the candidate's **Accomplishment Ledger** ($8M Google Cloud influenced, $100M+ enterprise platform revenue delivered, $2.1M CDW closed services, Promevo $2M+ pipeline).
   - Powered by **Google Gemini 3.6 Flash** with a two-tier sub-millisecond local heuristic pre-filter and 429 rate limit circuit breaker.

5. **Native-Send Safety Invariant & Truthful Staging**:
   - Invariant: `ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN`.
   - Aura drafts and stages responses; the user retains final transmission authority.
   - Granular operation results confirm draft creation and attachment upload separately.
   - Never falls back to sample emails on live sync errors; sample data is strictly isolated to explicit **Demo Mode**.

6. **Career Intelligence & Telemetry Studio**:
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
│   ├── canonical_engine.py     # 36-Resume Vault Indexer, OpenXML Parser & Lens Matcher
│   ├── config.py               # Settings & Configuration Management
│   ├── desktop_helper.py       # Optional macOS Desktop Status Helper
│   ├── main.py                 # FastAPI Application Core & REST Endpoints
│   ├── migration.py            # Settings & Database Migration (v1.0 to v1.1)
│   ├── models.py               # Pydantic Schemas & Enumerations
│   ├── outlook_client.py       # Backward-Compatibility Adapter
│   ├── provider_manager.py     # Multi-Account Cloud Dispatcher & Router
│   ├── safety_policy.py        # Mail Safety Policy Engine & Native-Send Invariant
│   ├── security.py             # macOS Keychain Vault & Security Scanner
│   ├── providers/              # Cloud Email Providers
│   │   ├── base.py             # Abstract BaseEmailProvider & Composite ID Codec
│   │   ├── demo.py             # Explicit Demo Sandbox Provider
│   │   ├── gmail.py            # Gmail API OAuth Provider
│   │   ├── graph.py            # Microsoft Graph API Provider (MSAL)
│   │   └── imap.py             # RFC 3501 IMAP Cloud Provider
│   └── tests/                  # Automated Unit & Security Integration Test Suite
│       ├── test_analytics.py
│       ├── test_assistant.py
│       ├── test_canonical_engine.py
│       ├── test_multi_account.py
│       └── test_providers.py
├── data/
│   ├── settings.json.example   # Sanitized Configuration Template
│   └── resumes/                # Vault Folder for Local Resume Variants
├── frontend/
│   ├── app.js                  # Frontend Controller (Vanilla JS)
│   ├── index.html              # Glassmorphic Multi-Tab Dashboard
│   └── style.css               # Design System (Tokens, Animations, Glassmorphism)
├── scripts/
│   └── smoke_test_live.py      # Read-Only Live Diagnostics & Smoke Test
├── ARCHITECTURE.md             # In-Depth System Design & Topology Document
├── MAC_SMOKE_TEST_CHECKLIST.md # macOS & New Outlook Step-by-Step Validation Checklist
├── MIGRATION_v1.0_to_v1.1.md   # Upgrade & Configuration Migration Guide
├── SECURITY_REPORT.md          # Security Remediation & Secrets Audit Report
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

# Upgrade pip and install dependencies
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

### 2. Microsoft Entra & Cloud Account Setup

#### A. Microsoft Graph Setup (Outlook.com / M365)
1. Go to [Microsoft Entra Admin Center](https://entra.microsoft.com) ➔ **App registrations** ➔ **New registration**.
2. Name: `Aura Mail AI`.
3. Supported account types: `Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant) and personal Microsoft accounts (e.g. Skype, Xbox)`.
4. Redirect URI: `Public client/native (mobile & desktop)` ➔ `https://localhost:8000/api/auth/callback`.
5. Under **API permissions**, add delegated permissions:
   - `Mail.ReadWrite`
   - `User.Read`
   - `offline_access`
6. Copy the **Application (client) ID** and paste it into Aura Mail AI **Engine Settings**.

#### B. Spectrum / Custom IMAP Setup
- In the **Cloud Accounts** tab, select **Connect New Account** ➔ **IMAP**.
- Passwords are saved directly to your **macOS Keychain**.
- Outbound responses are staged directly in your cloud **Drafts** folder for native client review and sending.

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
- 🔒 [**Security Remediation & Secrets Audit Report (SECURITY_REPORT.md)**](SECURITY_REPORT.md)
- 🔄 [**Migration Guide v1.0 ➔ v1.1 (MIGRATION_v1.0_to_v1.1.md)**](MIGRATION_v1.0_to_v1.1.md)
- 📋 [**macOS Smoke Test Checklist (MAC_SMOKE_TEST_CHECKLIST.md)**](MAC_SMOKE_TEST_CHECKLIST.md)

---

## 📄 License
MIT License. Developed for executive email triage, career telemetry, and canonical resume orchestration.

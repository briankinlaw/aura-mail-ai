# System Architecture & Technical Design (v1.1)

## Aura Mail AI: Universal Cloud Multi-Account Assistant & Canonical Career Co-Pilot

This document outlines the architectural blueprint, security posture, component topology, and technical design decisions for Aura Mail AI v1.1.

---

## 1. Executive Summary & Problem Statement

Senior technology executives and strategic advisors manage multiple inboxes across personal, professional, and advisory email accounts. In v1.0, the application relied on local AppleScript automation against Legacy Microsoft Outlook for Mac. 

In **v1.1**, Aura Mail AI transitions to a **cloud-first, multi-account architecture** compatible with **New Outlook for Mac**, web email, and mobile clients:
1. **Cloud Synchronization**: Messages and drafts created in the cloud synchronize automatically into New Outlook for Mac.
2. **Provider-Neutral Interface**: Abstract `BaseEmailProvider` implemented by `MicrosoftGraphProvider` (MSAL), `GmailProvider`, `ImapProvider`, and `DemoProvider`.
3. **Structured Composite Message Identity**: Every message ID carries its positive provider and account identity (`provider:account_id:native_id`), eliminating prefix guessing.
4. **macOS Keychain Vault**: Secrets (Gemini keys, OAuth refresh tokens, IMAP passwords) are stored exclusively in macOS Keychain via Python `keyring`.
5. **Zero Direct Transmission Authority & Native Send Safety**: Strict `DRAFT_ONLY` and `MANUAL_SEND_ONLY` modes. Aura prepares and stages drafts; final mail transmission is performed exclusively by the human in the native mail client (Outlook / Gmail / Webmail). Aura's local API has zero transmission authority.

---

## 2. Component Architecture & Topology

```mermaid
graph TD
    subgraph "Client Layer"
        NOM["New Outlook for Mac<br/>(Cloud Sync Mailboxes)"]
        UI["Glassmorphic Web Dashboard<br/>(HTML5 / CSS / ES2022)"]
    end

    subgraph "FastAPI Backend Tier (:8000)"
        MAIN["FastAPI Application Core<br/>(main.py)"]
        PM["Provider Manager<br/>(provider_manager.py)"]
        SEC["Security & Keychain Vault<br/>(security.py / macOS Keychain)"]
        AI["AI Triage & Agentic Engine<br/>(ai_agent.py - Gemini + Heuristics)"]
        CCE["Canonical Career Engine<br/>(canonical_engine.py - 36 Resumes)"]
        ANL["Analytics & Telemetry Engine<br/>(analytics.py - SQLite DB)"]
    end

    subgraph "Cloud Email Providers"
        GRAPH["Microsoft Graph API (MSAL)<br/>(Outlook.com & M365)"]
        GMAIL["Gmail API (OAuth2)<br/>(Google Accounts)"]
        IMAP["Standard RFC 3501 IMAP<br/>(Spectrum / Custom Domains)"]
        DEMO["Demo Sandbox Provider<br/>(Offline Mock Data)"]
    end

    subgraph "Persistence & Secret Storage"
        KC[("macOS Keychain<br/>keyring.backends.macOS")]
        DB[("SQLite Telemetry Database<br/>data/analytics.db")]
        VAULT[("Canonical Resume Vault<br/>36 Authoritative Resumes")]
    end

    UI <-->|REST API JSON| MAIN
    MAIN --> PM
    MAIN --> AI
    MAIN --> CCE
    MAIN --> ANL
    PM --> GRAPH
    PM --> GMAIL
    PM --> IMAP
    PM --> DEMO
    PM --> SEC
    SEC <--> KC
    GRAPH <-->|Cloud Sync| NOM
    GMAIL <-->|Cloud Sync| NOM
    IMAP <-->|Cloud Sync| NOM
    ANL --> DB
    CCE --> VAULT
```

---

## 3. Subsystem Deep-Dive

### 3.1 Cloud Provider Architecture (`backend/providers/`)
- **Abstract Base Contract** (`base.py`):
  - `authenticate()`, `validate_connection()`, `list_accounts()`, `fetch_inbox_messages()`, `create_reply_draft()`, `attach_file()`, `move_message()`, `delete_message()`.
  - Zero direct transmission: Aura prepares and stages drafts; human sends via native mail client. Legacy `send_reply` fails closed with `SEND_FORBIDDEN`.
  - Every operation returns a structured `ProviderOperationResult` with `success`, `provider`, `account_id`, `operation`, `remote_object_id`, `error_code`, `safe_message`, `retryable`.
- **Microsoft Graph Provider** (`graph.py`):
  - Integrates `msal.PublicClientApplication` with serialized token cache in macOS Keychain.
  - Supports multi-mailbox accounts and automatic alias resolution.
  - Creates threaded drafts via `POST /me/messages/{id}/createReply` and uploads attachments. Zero Graph transmission endpoints (`/send`) are invoked by Aura.
- **Gmail Provider** (`gmail.py`):
  - Dedicated Google OAuth2 integration with Keychain token storage.
  - Composes MIME multipart in-reply-to drafts and saves them to Gmail Drafts folder. Zero Gmail transmission endpoints (`/drafts/send`) are invoked by Aura.
- **Standard RFC 3501 IMAP Provider** (`imap.py`):
  - Implements RFC 6154 Special-Use folder discovery (`\Drafts`, `\Sent`, `\Trash`, `\Junk`).
  - Appends prepared MIME drafts directly to IMAP Drafts folder. Outbound mail transmission is performed by the user via their native mail client.
- **Explicit Demo Mode Provider** (`demo.py`):
  - Isolated offline mock sandbox activated only when `demo_mode=True`.

### 3.2 Security & macOS Keychain Vault (`backend/security.py`)
- **Zero Plaintext Secrets on Disk**:
  - `data/settings.json` contains only non-secret user preferences.
  - API keys, OAuth tokens, and mailbox passwords are stored in **macOS Keychain** (`keyring.backends.macOS.Keyring`).
- **Startup Security Audit**: Automatically scans code and configuration files on startup and flags unmasked keys.

### 3.3 Provider Manager & Dispatcher (`backend/provider_manager.py`)
- Dispatches operations according to composite message IDs (`provider:account_id:native_id`).
- Merges multi-account inboxes into a unified view.
- Excludes historical reference accounts (`bkinlaw@dxc.com`, `brian.kinlaw@cdw.com`, `briankinlaw@revealwhy.com`).
- Updates cache and telemetry ONLY on confirmed provider success.

### 3.4 Canonical Career Engine (`backend/canonical_engine.py`)
- Indexes 36 canonical and custom resume files on disk using pure OpenXML.
- Matches job reachouts against the 3-level role taxonomy (Level 3A Advisor, Level 3B TPM, Level 3C AI Governance, Field CTO).
- Enforces strict factual grounding from `Accomplishment_Ledger_CURRENT.docx` ($8M Google Cloud revenue influenced, $100M+ enterprise platform revenue delivered, Promevo pipeline $2M+).

---

## 4. Automated Verification & Quality Assurance

- **Unit & Security Integration Tests**: 149 tests in `backend/tests/` covering safety policy, origin defense, trust boundaries, multi-account routing, providers, and factual grounding.
- **Test Command**: `PYTHONPATH=. .venv/bin/pytest backend/tests/ -v`
- **Result**: `149 passed` with 100% success.

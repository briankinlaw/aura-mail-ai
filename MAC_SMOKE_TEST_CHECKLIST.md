# macOS & New Outlook Smoke Test Checklist (v1.1)

Follow this checklist to validate Aura Mail AI v1.1 on your MacBook with **New Outlook for Mac**.

---

## 📋 Pre-Flight Verification

- [ ] **Python 3.12 Virtual Environment**:
  ```bash
  # Standardized via .python-version
  python3.12 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  ```
- [ ] **Run Automated Test Suite**:
  ```bash
  # Run complete Python test suite
  .venv/bin/python -m pytest

  # Run frontend JavaScript test suites (Node 24 standardized via .nvmrc)
  node backend/tests/test_outlook_content_security.js
  node backend/tests/test_stage_cloud_draft.js
  node backend/tests/test_frontend_risk_validator.js
  ```
  *Expected*: Collection succeeds with zero errors and all test cases pass (Phase 10 clean-install validation observed 1006 Python test cases and 117 JavaScript assertions passing).
- [ ] **Execute Automated Secret Audit**:
  ```bash
  .venv/bin/python -c "from backend.security import scan_repository_for_secrets; from backend.config import BASE_DIR; print('Findings:', scan_repository_for_secrets(BASE_DIR))"
  ```
  *Expected*: `Findings: []` (zero secrets detected).

---

## 🖥️ Live Cloud Smoke Test Execution

1. **Run Diagnostics Script (Read-Only)**:
   ```bash
   .venv/bin/python scripts/smoke_test_live.py
   ```
   *Verify*:
   - Safety mode is reported as `SAFE_REVIEW`.
   - Accounts report truthful connection statuses (no fake `Connected` just because Outlook is running).
   - Sync errors or empty counts do NOT inject sample/demo emails.

2. **Launch Application Server**:
   ```bash
   ./run.sh
   ```
   Open browser at `https://localhost:8000`.

---

## 📬 Step-by-Step UI Verification in New Outlook for Mac

### Step 1: Cloud Accounts Management
- [ ] Navigate to the **Cloud Accounts** tab (`data-tab="connected-accounts"`).
- [ ] Verify separate account cards are displayed for:
  - `kinlawb@outlook.com` (Primary Microsoft Graph)
  - `brian.kinlaw@outlook.com` (Secondary Microsoft Graph)
  - `briankkinlaw@gmail.com` (Google Cloud / Gmail)
  - `brian@mavencode.com` (MavenCode Google Workspace)
  - `cbkinlaw@satx.rr.com` (Spectrum IMAP)
  - `briankinlaw@satx.rr.com` (Spectrum IMAP)
- [ ] Verify capabilities chips (`DRAFTS`, `ATTACHMENTS`, `MOVE`, `DELETE`, `QUARANTINE`) are listed on each card.
- [ ] Click **Test** on an account to verify on-demand health checking.

### Step 2: Cloud Draft Creation & Attachment Staging
- [ ] Select an inbound recruiter reachout in the **Recruiter & Resume Studio**.
- [ ] Review the auto-selected canonical resume variant (e.g. `Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx`).
- [ ] Click **Save to Cloud Drafts**.
- [ ] Open **New Outlook for Mac** (or Outlook Web):
  - Check the **Drafts** folder for `kinlawb@outlook.com`.
  - Verify the reply draft appears as a threaded reply with the original email history preserved.
  - Verify the canonical resume `.docx` or `.pdf` file is attached to the draft.

### Step 3: Noise Cleaner & Quarantine
- [ ] Switch to the **Noise Cleaner & Triage** tab.
- [ ] Click **Clean All Noise Emails Now**.
- [ ] Verify messages are moved to the `AI Cleaned - Noise` folder in the cloud mailbox.
- [ ] Verify New Outlook updates its folder list to reflect the moved messages.

### Step 4: Demo Mode Verification
- [ ] Open **Engine Settings** and enable **Explicit Demo Mode**.
- [ ] Verify the yellow **DEMO MODE ACTIVE** banner appears across the dashboard.
- [ ] Verify all sample reachouts are prefixed with `[DEMO]`.
- [ ] Click **Exit Demo Mode** to return to live multi-account mode.

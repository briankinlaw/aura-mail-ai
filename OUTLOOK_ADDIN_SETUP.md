# Aura Mail AI — Native Microsoft Outlook Web Add-in Setup Guide (Office.js)

This guide walks you through sideloading and using the **Aura Mail AI** native Office.js Add-in inside Microsoft Outlook on the Web, Outlook for Mac, and Outlook Desktop.

---

## 🚀 Overview

The Aura Mail AI Outlook Add-in embeds the **Opportunity Radar**, **Canonical Career System (CCS v2.1)** grounded reply generator, and **Availability Broker** directly inside your Microsoft Outlook sidebar.

### Core Capabilities Inside Outlook
1. **Opportunity Radar Analysis**: 0–100% deterministic fit scoring against your verified executive career pillars, company detection, and role compensation tiering.
2. **Canonical Career System (CCS v2.1) Grounding**: Information-integrity control binding generated drafts directly to verified metrics in your Accomplishment Ledger ($8M Google Cloud revenue influenced, $100M+ enterprise impact).
3. **Availability Broker Integration**: Calculates and embeds 3 proposed booking windows or trusted provider-verified availability directly into your draft.
4. **1-Click Outlook Reply Pre-Fill**: Pre-fills Outlook's native compose reply window with your staged draft after HTML-escaping untrusted content at the rendering boundary (`formatReplyAsSafeHtml`).
5. **Draft-First Safety Policy**: Direct mail transmission by Aura is permanently forbidden (`ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN`). Responses are staged for executive review; final outbound transmission is executed exclusively by the user via Outlook's native Send button.

---

## 🛠️ Step 1: Set Up Local Development TLS Certificate (Phase 2.1)

Office.js add-ins embedded in New Outlook for Mac and Outlook on the Web require a trusted HTTPS origin (`https://localhost:8000`).

To generate a locally trusted development TLS certificate using `mkcert`:

```bash
# 1. Install mkcert (if not already installed)
brew install mkcert

# 2. Install local CA in system trust stores
mkcert -install

# 3. Create local certificate directory and generate certificate
mkdir -p ~/.aura_certs
mkcert -key-file ~/.aura_certs/localhost-key.pem -cert-file ~/.aura_certs/localhost.pem localhost 127.0.0.1
```

> **Security Note**: Never commit TLS private keys (`.pem` or `.key`) to the repository. The `.aura_certs` directory is stored in your user home directory.

---

## 🚀 Step 2: Start the Aura Mail AI Backend Server

From your terminal in the `aura-mail-ai` repository:

```bash
cd /Users/briankinlaw/aura-mail-ai
./run.sh
```

Or start with `uvicorn`:
```bash
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --ssl-certfile ~/.aura_certs/localhost.pem --ssl-keyfile ~/.aura_certs/localhost-key.pem --reload
```

The taskpane UI is accessible at `https://localhost:8000/add-in/taskpane.html`.

---

## 🌐 Step 3: Sideload in Outlook on the Web (Recommended)

Outlook on the Web provides the fastest and most seamless way to sideload custom add-in manifests across all your devices.

1. Open your browser and navigate to **[Outlook on the Web](https://outlook.office.com)** (or `https://outlook.live.com`).
2. Log in with your Microsoft account (e.g. `kinlawb@outlook.com`).
3. Select any email in your Inbox to open the message reading pane.
4. Click the **Apps** icon (or the `...` More Actions menu in the top-right corner of the email message header).
5. Select **Get Add-ins** (or **Add apps**).
6. In the modal dialog that appears, select **My add-ins** in the left sidebar.
7. Scroll down to the **Custom Add-ins** section.
8. Click **+ Add a custom add-in** &rarr; **Add from file...**.
9. Browse to `/Users/briankinlaw/aura-mail-ai/manifest.xml` and click **Open**.
10. Click **Install** on the warning prompt (this approves your custom local manifest).

Once installed, the **Aura Radar** button will appear on the ribbon of every message in Outlook Web!

---

## 🍎 Step 4: Sideload in Microsoft Outlook for Mac

### Method A: Cloud Sync (Easiest)
If you sideload the manifest in Outlook on the Web (Step 3), it will automatically synchronize to your **Microsoft Outlook for Mac** client under the same account.

### Method B: Manual Sideloading in Outlook for Mac
1. Open **Microsoft Outlook for Mac**.
2. Select any email in your inbox.
3. Click the `...` (More Actions) button on the message toolbar or top ribbon.
4. Click **Get Add-ins** &rarr; **My add-ins**.
5. Under **Custom add-ins**, choose **+ Add a custom add-in** &rarr; **Add from file...**.
6. Select `/Users/briankinlaw/aura-mail-ai/manifest.xml`.

---

## 📋 Step 5: Using the Add-in & Workflow Boundary

1. **Open an Inbound Email**: Click on any recruiter outreach or email inquiry in your Inbox.
2. **Launch Aura Radar**: Click the **Aura Radar** button on the message toolbar.
3. **Review Analysis**:
   - The Opportunity Radar displays the candidate alignment score ($0–100\%$).
   - Extracted recruiter name, company, and role are verified.
   - Recommended Canonical Resume variant is selected.
4. **Choose Tone & Options**:
   - Toggle **Include 3 Non-Conflicting Booking Windows** to embed real-time calendar availability.
   - Select your preferred executive tone (*Warm & Exec*, *Direct*, or *Calendar Focus*).
5. **Stage or Insert**:
   - Click **Insert into Outlook Reply** to pre-fill Outlook's native compose window. All text is HTML-escaped at the rendering boundary before insertion.
   - Click **Stage in Cloud Drafts** to save the draft to your cloud mailbox (`POST /api/emails/{id}/save-draft`). Aura requires a confirmed provider `remote_object_id` before reporting success.
   - Click **Copy** to grab the response text to your clipboard anytime.
6. **Final User Transmission**:
   - Final review and outbound transmission are performed exclusively by the human executive using Outlook's native **Send** button. Aura provides zero direct mail transmission capabilities.

---

## 🧪 Testing & Verification

You can test the add-in and all API endpoints using the automated test suite:

```bash
.venv/bin/python -m pytest backend/tests/test_addin.py -v
```

All test cases validate:
- `manifest.xml` schema structure and `ReadWriteItem` permission declarations.
- Taskpane HTML, CSS, JavaScript, and high-res icon asset delivery over HTTPS.
- `/api/radar/triage` recruiter scoring logic.
- `/api/radar/draft` grounded reply synthesis and untrusted text handling.
- `/api/calendar/availability` booking window calculations and provenance enforcement.
- Cloud draft staging response validation and transmission exclusion.

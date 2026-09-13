# Aura Mail AI — Native Microsoft Outlook Web Add-in Setup Guide (Office.js)

This guide walks you through sideloading and using the **Aura Mail AI** native Office.js Add-in inside Microsoft Outlook on the Web, Outlook for Mac, and Outlook Desktop.

---

## 🚀 Overview

The Aura Mail AI Outlook Add-in embeds the **Opportunity Radar**, **Canonical Career System (CCS v2.1)** grounded reply generator, and **Availability Broker** directly inside your Microsoft Outlook sidebar.

### Core Capabilities Inside Outlook
1. **Opportunity Radar Analysis**: 0–100% deterministic fit scoring against your verified executive career pillars, company detection, and role compensation tiering.
2. **Canonical Career System (CCS v2.1) Grounding**: Strict 100% factual accuracy tied directly to your Accomplishment Ledger (influencing $8M in Google Cloud revenue, $100M+ enterprise impact).
3. **Availability Broker Integration**: Automatically calculates and embeds 3 non-conflicting booking windows directly into your draft.
4. **1-Click Outlook Reply Pre-Fill**: Opens or populates Outlook's native compose reply window with your staged draft.
5. **Draft-First Safety Policy**: Responses are never automatically sent; they are staged for executive review.

---

## 🛠️ Step 1: Start the Aura Mail AI Backend Server

The Outlook Add-in communicates securely with the local Aura Mail AI backend server.

From your terminal in the `aura-mail-ai` repository:

```bash
cd /Users/briankinlaw/aura-mail-ai
./run.sh
```

Or start with `uvicorn`:
```bash
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

> **Note**: The taskpane UI is accessible at `http://127.0.0.1:8000/add-in/taskpane.html` (or `https://localhost:8000/add-in/taskpane.html`).

---

## 🌐 Step 2: Sideload in Outlook on the Web (Recommended)

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

## 🍎 Step 3: Sideload in Microsoft Outlook for Mac

### Method A: Cloud Sync (Easiest)
If you sideload the manifest in Outlook on the Web (Step 2), it will automatically synchronize to your **Microsoft Outlook for Mac** client under the same account.

### Method B: Manual Sideloading in Outlook for Mac
1. Open **Microsoft Outlook for Mac**.
2. Select any email in your inbox.
3. Click the `...` (More Actions) button on the message toolbar or top ribbon.
4. Click **Get Add-ins** &rarr; **My add-ins**.
5. Under **Custom add-ins**, choose **+ Add a custom add-in** &rarr; **Add from file...**.
6. Select `/Users/briankinlaw/aura-mail-ai/manifest.xml`.

---

## 📋 Step 4: Using the Add-in

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
   - Click **Insert into Outlook Reply** to pre-fill Outlook's native compose window.
   - Click **Stage in Cloud Drafts** to save the draft in your mailbox with your canonical `.docx` resume attached.
   - Click **Copy** to grab the response text to your clipboard anytime.

---

## 🧪 Testing & Verification

You can test the add-in and all API endpoints using the automated test suite:

```bash
.venv/bin/pytest backend/tests/test_addin.py -v
```

All 5 test cases will validate:
- `manifest.xml` schema structure and permission declarations.
- Taskpane HTML, CSS, JavaScript, and high-res icon asset delivery.
- `/api/radar/triage` recruiter scoring logic.
- `/api/radar/draft` grounded reply synthesis.
- `/api/calendar/availability` booking window calculations.

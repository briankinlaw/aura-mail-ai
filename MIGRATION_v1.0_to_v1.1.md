# Migration Guide: Aura Mail AI v1.0 ➔ v1.1

This guide documents the technical differences between **v1.0** and **v1.1**, the rationale for architectural changes, and instructions for migrating user configuration and credentials.

---

## 1. Summary of Architectural Upgrades

| Dimension | v1.0 (Legacy Outlook Bridge) | v1.1 (Cloud-First Multi-Account) |
| :--- | :--- | :--- |
| **Primary Integration** | Monolithic macOS AppleScript (`osascript`) targeting Legacy Outlook process | Cloud REST APIs (**Microsoft Graph MSAL**, **Gmail API**, **RFC 3501 IMAP**) |
| **New Outlook for Mac** | Incompatible / Fragile (New Outlook lacks AppleScript object model) | **100% Compatible** (Cloud drafts and messages sync automatically) |
| **Multi-Account Support** | Monolithic inbox scrape; no account-level routing | **Composite message IDs** (`provider:account_id:native_id`) with alias de-duplication |
| **Credential Storage** | Plaintext keys and passwords in `data/settings.json` | **macOS Keychain** via Python `keyring` integration |
| **Error Handling** | Silent fallback to sample reachouts on failure; fake success | **Structured Operation Results**; truthful diagnostic errors; no fake success |
| **Safety Defaults** | `SAFE_REVIEW` (drafts only) | **`DRAFT_ONLY` & `MANUAL_SEND_ONLY`**: Direct mail transmission by Aura is permanently forbidden (`ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN`). Final send executed exclusively by human in native client. |
| **Draft Creation** | AppleScript GUI manipulation | Threaded cloud API drafts with separate attachment upload validation and provider confirmation (`remote_object_id`) |

---

## 2. Automatic Configuration Migration

Aura Mail AI v1.1 includes automatic migration logic in `backend/migration.py`:

1. **Non-Secret Preferences**:
   - Brian's profile (`full_name`, `summary_bio`, `core_skills`, `target_roles`, `work_preferences`, `custom_reply_instructions`) is preserved automatically.
   - Active canonical resume selection (`active_resume_file`) is preserved.
   - Historical reference accounts (`bkinlaw@dxc.com`, `brian.kinlaw@cdw.com`, `briankinlaw@revealwhy.com`) remain strictly isolated from inbox scanning.
2. **Credential Migration to macOS Keychain**:
   - Any existing `gemini_api_key` in `data/settings.json` is migrated into macOS Keychain under service `aura_mail_ai` and purged from disk.
   - Any IMAP passwords are saved directly into macOS Keychain and removed from configuration files.
3. **Sanitized `.gitignore` Enforcement**:
   - `data/settings.json`, SQLite databases, email caches, token caches, and `.env*` files are excluded from Git tracking.

---

## 3. Account Configuration & Setup

### A. Microsoft 365 & Outlook.com (Microsoft Graph via MSAL)
1. Register a multi-tenant or personal **Public Client Application** in [Microsoft Entra Admin Center](https://entra.microsoft.com).
2. Configure Mobile & Desktop Redirect URIs:
   - `https://localhost:8000/api/auth/callback`
   - `https://login.microsoftonline.com/common/oauth2/nativeclient`
3. Request the following delegated permissions:
   - `Mail.ReadWrite` (Read inboxes and stage cloud drafts in Drafts folder)
   - `User.Read` (Resolve primary email and aliases)
   - `offline_access` (Token refresh)
   *(Note: `Mail.Send` is strictly omitted as Aura contains zero direct transmission authority)*
4. Enter your **Application (client) ID** in the **Engine Settings** tab in Aura Mail AI.
5. In the **Cloud Accounts** tab, click **Start Microsoft Device Sign-In Flow** or sign in via browser.

### B. Google Cloud / Gmail API (OAuth 2.0)
1. Configure OAuth 2.0 Client Credentials in Google Cloud Console.
2. Requested scope: `https://www.googleapis.com/auth/gmail.modify` (consolidated scope for inbox sync, MIME draft composition, and label quarantine).
3. *(Note: While Google's permission model grants broad API capabilities under `gmail.modify`, Aura's application code exposes zero transmission routes, and Aura policy strictly forbids direct transmission)*

### C. Spectrum / Roadrunner & Custom IMAP Accounts
1. In the **Cloud Accounts** tab, select **Connect New Account** ➔ **IMAP**.
2. Enter your email (e.g. `cbkinlaw@satx.rr.com` or `brian@mavencode.com`) and password.
3. The password is automatically verified and stored in your **macOS Keychain**.
4. Draft responses are staged directly in the IMAP `Drafts` folder for native review and dispatch.

### D. Explicit Demo Mode
- If you wish to demonstrate the application offline or in a sandbox, enable **Demo Mode** in Settings.
- When enabled, a yellow **DEMO MODE ACTIVE** banner is displayed and mock data is labeled with `[DEMO]`.

# Aura Mail AI — Local Desktop Threat Model (Phase 6)

## 1. System Architecture & Context

Aura Mail AI is an executive email assistant and resume co-pilot designed and deployed as a **personal local-desktop application** for single-user macOS environments.

Aura runs locally bound to the loopback interface (`127.0.0.1` / `::1`) over local TLS at `https://localhost:8000`. It interfaces with user-configured email providers (Microsoft Graph via MSAL, Gmail API, and IMAP) and provides a same-origin web dashboard and an Office.js taskpane add-in for Outlook.

---

## 2. Security Boundaries & Assumptions

### In-Scope Threats (What Phase 6 Protects Against)

Phase 6 formalizes and enforces defense against external, remote, and browser-driven threats:

1. **Malicious Websites & Cross-Origin JavaScript**:
   - Malicious websites visited in the user's browser attempting to issue cross-origin requests to `https://localhost:8000`.
   - Cross-Site Request Forgery (CSRF) and browser-driven API invocation.
2. **Opaque and Sandboxed Browser Contexts**:
   - Requests presenting `Origin: null`, opaque iframe origins, or sandboxed web contexts.
3. **Cross-Site Browser Contexts**:
   - Requests arriving with browser Fetch Metadata indicating `Sec-Fetch-Site: cross-site`.
4. **Unexpected Remote & Network Exposure**:
   - Remote network hosts attempting to access the local server if the daemon is misconfigured or accidentally bound to external interfaces (enforced via ASGI socket-peer address validation).
5. **DNS Rebinding & Host Header Abuse**:
   - Attacker-controlled domains resolving to `127.0.0.1` attempting to bypass Origin/Host protections (enforced via strict Host header allowlisting).
6. **OAuth Authorization-Response Injection & Login CSRF**:
   - Replay, pre-generation, or cross-provider injection of OAuth authorization codes (enforced via cryptographically secure, provider-bound, single-use, expiring server-side state transactions).
7. **Accidental Unauthenticated Invocation**:
   - Unauthenticated access to privileged endpoints manipulating emails, drafts, settings, accounts, or analytics.
8. **Credential Ambiguity & Header Conflicts**:
   - Conflicting, duplicate, comma-joined, malformed, or missing authentication credentials.

### Out-of-Scope Threats (What Phase 6 Does Not Protect Against)

Aura Mail AI is a personal desktop application executing under the privileges of the local logged-in macOS user (`$UID`). The following threat scenarios are **explicitly out of scope** for this architecture:

1. **Same-User Process Compromise**:
   - Malicious software or processes already executing as the same macOS user account. Any process running as the same user can inspect process memory, read user configuration files, access `~/.aura_session_token`, or communicate via local loopback sockets.
2. **Same-User Debugging and Process Injection**:
   - Processes utilizing `lldb`, `dtrace`, `ptrace`, macOS mach-task ports, or runtime code injection against the same user.
3. **Local Endpoint & Root/Administrator Compromise**:
   - Operating system compromise, root access, kernel-level compromise, or physical workstation theft.
4. **Successful Same-Origin Cross-Site Scripting (XSS)**:
   - If an attacker achieves arbitrary code execution within the legitimate `https://localhost:8000` origin context, browser security boundaries (CORS, Origin, local tokens) are bypassed.

---

## 3. Explicit Threat Model Clarifications

To prevent misleading claims:

* **Session Token is Not an OS Boundary**: The local session token (`~/.aura_session_token`) provides browser-request authorization to distinguish authorized local UI actions from cross-origin browser requests. It is **not** an operating-system administrative credential or an inter-process security barrier against other same-user processes.
* **CORS is Not Authentication**: Cross-Origin Resource Sharing (CORS) is a browser mechanism for controlling cross-origin response reading (`allow_origins = ["https://localhost:8000"]`). CORS headers alone do not authenticate callers or prevent non-browser HTTP requests.
* **Host Header Validation Addresses DNS Rebinding**: Host validation prevents a browser navigating an attacker domain from reusing ambient cookies or tokens against a rebinding server, but does not authenticate the socket caller.
* **Loopback Binding Limits Network Reachability**: Binding to `127.0.0.1` prevents remote network access under normal socket routing. Application-level loopback peer validation provides defense in depth against accidental interface misbinding.
* **Permanent Outbound Transmission Prohibition**: Under all safety modes (`DRAFT_ONLY` and `MANUAL_SEND_ONLY`), Aura-controlled direct mail transmission is forbidden (`ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN`). Aura generates and stages drafts; final transmission is executed exclusively by the user in their native mail client.
* **Provider Technical Capability != Aura Authorization**: Broad provider OAuth scopes (e.g. `gmail.modify`) may technically permit provider-side operations beyond Aura's exposed routes. Aura's application contains zero transmission endpoints, and Aura policy strictly forbids direct transmission.
* **Risk Sentinel Monotonic Floor**: Risk Sentinel enforces `FINAL_RISK >= DETERMINISTIC_RISK`. Gemini/LLM output cannot downgrade deterministic security findings. Normalization resolves upward without fabricating evidence. `SAFE`/`PROCEED` verdicts are exact-draft scoped and never grant mail transmission authorization.
* **Calendar Provenance Enforcement**: Verified calendar states require trusted server-side provider evidence (`CALENDAR_VERIFIED_CLEAR`, `CALENDAR_VERIFIED_WITH_CONFLICTS`). Caller-supplied assertions cannot mint verified availability and strictly default to `CALENDAR_NOT_CHECKED`.
* **Offline Recovery is a Separate Boundary**: Administrative provenance store recovery (`run_offline_recovery()`) is strictly offline and executed via CLI tools with terminal/TTY requirements and runtime lock validation; it is separate from the in-process HTTP API trust boundary.

---

## 4. Multi-Layered Browser-Facing Trust Boundary

The effective browser boundary is the combination of:

```text
loopback binding (127.0.0.1)
+
application-level loopback peer enforcement (is_loopback check on client socket)
+
canonical HTTPS origin (https://localhost:8000)
+
strict CORS (allow_origins = ["https://localhost:8000"], allow_credentials = False)
+
server-side Origin and browser-context validation (Sec-Fetch-Site != cross-site)
+
strict Host validation (localhost, 127.0.0.1 only)
+
authenticated privileged requests (constant-time token verification)
+
validated one-time OAuth authorization state (256-bit entropy, provider/redirect-bound)
+
fail-closed route behavior
```

---

## 5. Route Classification & Inventory

| Route | Method | Access | State Mutation | Auth Dependency | Security Controls |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/` | `GET`, `HEAD` | Public | None | None | Injects session token into same-origin HTML; `no-store`, `frame-ancestors 'none'`. |
| `/add-in/taskpane.html` | `GET` | Public | None | None | Injects session token into Office.js HTML; `no-store`, CSP `frame-ancestors` for approved Office domains. |
| `/api/safety-policy` | `GET` | Public | None | None | Read-only static safety policy metadata; contains zero secrets or tokens. |
| `/api/auth/callback` | `GET` | Public | Yes (OAuth exchange) | One-time OAuth State | Requires valid, unexpired, single-use, provider-bound OAuth state token before token exchange. |
| `/api/auth/google/callback` | `GET` | Public | Yes (OAuth exchange) | One-time OAuth State | Requires valid, unexpired, single-use, provider-bound OAuth state token before token exchange. |
| `/api/auth/msal/url` | `GET` | Privileged | Yes (creates state) | `require_local_auth` | Generates MSAL auth URL with server-created 256-bit state bound to canonical redirect. |
| `/api/auth/google/url` | `GET` | Privileged | Yes (creates state) | `require_local_auth` | Generates Google auth URL with server-created 256-bit state bound to canonical redirect. |
| `/api/auth/msal/device-code` | `POST` | Privileged | Yes | `require_local_auth` | Initiates MSAL device code flow. |
| `/api/auth/msal/device-code/poll` | `POST` | Privileged | Yes | `require_local_auth` | Polls MSAL device flow status. |
| `/api/auth/submit-code` | `POST` | Privileged | Yes | `require_local_auth` | Manual MSAL code submission; forces canonical redirect URI. |
| `/api/auth/google/submit-code` | `POST` | Privileged | Yes | `require_local_auth` | Manual Google code submission; forces canonical redirect URI. |
| `/api/auth/imap` | `POST` | Privileged | Yes | `require_local_auth` | Connects and verifies IMAP credentials. |
| `/api/status` | `GET` | Privileged | None | `require_local_auth` | Returns connected accounts and system status. |
| `/api/accounts` | `GET` | Privileged | None | `require_local_auth` | Lists configured accounts. |
| `/api/accounts/{id}/test` | `POST` | Privileged | Yes | `require_local_auth` | Tests account connection. |
| `/api/accounts/{id}/disconnect` | `POST` | Privileged | Yes | `require_local_auth` | Disconnects provider account. |
| `/api/settings` | `GET`, `POST` | Privileged | Yes (POST) | `require_local_auth` | Reads/updates settings (secrets masked). |
| `/api/profile` | `GET`, `POST` | Privileged | Yes (POST) | `require_local_auth` | Reads/updates user profile. |
| `/api/canonical/*` | `GET`, `POST` | Privileged | Yes (generate) | `require_local_auth` | Canonical resume scanning, matching, ledger, and claims. |
| `/api/emails` | `GET` | Privileged | None | `require_local_auth` | Reads cached emails. |
| `/api/emails/sync` | `POST` | Privileged | Yes | `require_local_auth` | Triggers inbox synchronization. |
| `/api/emails/resolve-item` | `POST` | Privileged | None | `require_local_auth` | Resolves Office.js item ID to cached message. |
| `/api/emails/{id}/*` | `POST` | Privileged | Yes | `require_local_auth` | Reply draft generation, draft saving, risk check, draft invalidation, noise triage. |
| `/api/daemon/*` | `GET`, `POST` | Privileged | Yes (run) | `require_local_auth` | Daemon heartbeat status and manual cycle execution. |
| `/api/radar/*` | `POST` | Privileged | Yes | `require_local_auth` | Opportunity radar triage, drafting, and risk evaluation. |
| `/api/calendar/*` | `POST` | Privileged | None | `require_local_auth` | Availability computation and optimal booking windows. |
| `/api/analytics/*` | `GET` | Privileged | None | `require_local_auth` | Telemetry KPIs, funnels, compensation benchmarks, event logs. |
| `/static/*` | `GET` | Public | None | None | Static CSS, JS, image assets. Contains zero session tokens or secrets. |
| `/add-in/*` | `GET` | Public | None | None | Static Office.js manifest and assets. |

---

## 6. OAuth State Management Specification

1. **Entropy**: Minimum 256 bits of cryptographic entropy (`secrets.token_urlsafe(32)`).
2. **Purpose Binding**: State is strictly tagged with provider identity (`MICROSOFT_GRAPH` vs `GMAIL`). Cross-provider exchange is rejected.
3. **Redirect URI Binding**: The exact canonical redirect URI is recorded at creation and enforced during exchange. Caller-supplied redirect overrides are rejected.
4. **Account Binding**: Optional account identifier or login hint is stored server-side with the state.
5. **Expiration**: 300 seconds (5 minutes) maximum lifetime. Expired states are purged and rejected.
6. **Single-Use Atomicity**: State validation and consumption occur atomically under a synchronization lock. Once consumed, state is deleted immediately. Replay attempts fail closed.
7. **Storage Bounds**: In-memory registry is bounded (maximum 200 concurrent active states) with automatic eviction of expired entries.
8. **Logging Protection**: Raw state tokens and authorization codes are never written to disk logs or exposed in API error payloads.

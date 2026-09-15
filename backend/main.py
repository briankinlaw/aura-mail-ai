"""Aura Mail AI - Executive Email Assistant & Resume Co-Pilot (v1.1).

FastAPI backend with cloud-first multi-account architecture, MSAL Graph,
Gmail API, IMAP, Keychain secret security, and SQLite analytics telemetry.
"""

import os
import json
import shutil
import uuid
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field
from backend.models import (
    EmailMessage,
    EmailCategory,
    ClassificationResult,
    UserProfile,
    ReplyDraftRequest,
    SaveDraftRequest,
    SendReplyRequest,
)
from backend.config import (
    load_settings,
    save_settings,
    get_user_profile,
    update_user_profile,
    RESUMES_DIR,
    EMAILS_CACHE_FILE,
    CANONICAL_ORIGIN,
    get_ssl_context_paths,
    require_ssl_context_paths
)
from backend.providers.base import decode_composite_id

from backend.security import get_secret, set_secret, mask_secret
from backend import safety_policy
from backend.safety_policy import (
    evaluate_mail_action,
    MailAction,
    ExecutionContext,
    MailSafetyMode,
)
from backend.ai_agent import classify_email, generate_personalized_reply
from backend.provider_manager import provider_manager
from backend.desktop_helper import get_desktop_app_status
from backend.analytics import (
    record_opportunity,
    update_opportunity_stage,
    log_event,
    log_grounding_audit,
    get_kpis_summary,
    get_funnel_metrics,
    get_compensation_benchmarks,
    get_resume_roi_leaderboard,
    get_recent_audit_events,
    export_analytics_data
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aura_main")

app = FastAPI(
    title="Aura Mail AI - Cloud Email Assistant & Resume Co-Pilot",
    description="Multi-account Cloud Email Assistant for New Outlook for Mac, Gmail, and IMAP",
    version="1.1.0"
)

from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.auth import require_local_auth, get_local_session_token, ALLOWED_ORIGINS

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "*.localhost", "testserver"]

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "X-Aura-Session-Token", "X-Aura-Token", "X-Requested-With"],
)

# In-Memory Email Cache & State
CACHED_EMAILS: Dict[str, EmailMessage] = {}
_PENDING_DEVICE_FLOW: Optional[Dict[str, Any]] = None

def sync_cache_to_analytics():
    """Seeds cached reachouts into SQLite opportunities on startup."""
    try:
        for eid, email_msg in CACHED_EMAILS.items():
            if email_msg.classification and email_msg.classification.is_resume_request:
                record_opportunity(
                    email_id=email_msg.id,
                    subject=email_msg.subject,
                    sender_name=email_msg.sender_name,
                    sender_email=email_msg.sender_email,
                    recruiter_details=email_msg.classification.recruiter_details,
                    resume_match=email_msg.classification.resume_match,
                    status=email_msg.status if email_msg.status in ["DRAFTED", "REPLIED", "SCHEDULED"] else "INBOUND",
                    received_at=email_msg.received_at
                )
    except Exception as e:
        logger.warning(f"Failed to sync cache to analytics: {e}")

def load_cached_emails():
    global CACHED_EMAILS
    if EMAILS_CACHE_FILE.exists():
        try:
            with open(EMAILS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                CACHED_EMAILS = {k: EmailMessage(**v) for k, v in data.items()}
                sync_cache_to_analytics()
                return
        except Exception as e:
            logger.warning(f"Failed to load cached emails: {e}")
    
    # If explicit Demo Mode is enabled and no cache exists, load demo provider samples
    if provider_manager.is_demo_mode():
        msgs, _ = provider_manager.demo_provider.fetch_inbox_messages("demo@auramail.local")
        for email_msg in msgs:
            email_msg.classification = classify_email(email_msg)
            if email_msg.classification.is_resume_request:
                user_profile = get_user_profile()
                email_msg.draft_reply = generate_personalized_reply(email_msg, user_profile)
            CACHED_EMAILS[email_msg.id] = email_msg
        save_cached_emails()
        sync_cache_to_analytics()

def save_cached_emails():
    try:
        data = {k: v.model_dump() for k, v in CACHED_EMAILS.items()}
        with open(EMAILS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save cached emails: {e}")

load_cached_emails()

# --- System & Multi-Account Endpoints ---

@app.get("/api/status")
def get_system_status():
    settings = load_settings()
    accounts = provider_manager.list_all_accounts()
    connected_count = sum(1 for a in accounts if a.is_connected)
    desktop_status = get_desktop_app_status()
    has_gemini = bool(get_secret("gemini_api_key", "GEMINI_API_KEY"))
    resumes = [f.name for f in RESUMES_DIR.glob("*") if f.is_file()]

    # Authoritative Microsoft Graph Connection State (Phase 2.1)
    if settings.get("demo_mode", False):
        graph_status = "DEMO"
        graph_display = "Demo Mode (Offline Sandbox)"
        primary_graph_acc = "demo@auramail.local"
    else:
        azure_client_id = settings.get("azure_client_id", "")
        graph_accounts = [a for a in settings.get("configured_accounts", []) if a.get("provider") == "MICROSOFT_GRAPH"]
        if not azure_client_id:
            graph_status = "NOT_CONFIGURED"
            graph_display = "Microsoft Graph: Azure Client ID Required"
            primary_graph_acc = None
        elif not graph_accounts:
            graph_status = "READY_TO_CONNECT"
            graph_display = "Microsoft Graph: Ready to Connect"
            primary_graph_acc = None
        else:
            primary_graph_acc = next((a.get("account_id") for a in graph_accounts if a.get("is_primary")), graph_accounts[0].get("account_id"))
            # Authoritative token cache check via MSAL
            token = provider_manager.graph_provider.get_access_token(primary_graph_acc)
            if token:
                graph_status = "CONNECTED"
                graph_display = f"Microsoft Graph: Connected ({primary_graph_acc})"
            else:
                graph_status = "AUTH_REQUIRED"
                graph_display = f"Microsoft Graph: Authentication Required ({primary_graph_acc})"

    return {
        "status": "ONLINE",
        "version": "1.1.0",
        "demo_mode": settings.get("demo_mode", False),
        "total_accounts": len(accounts),
        "connected_accounts": connected_count,
        "desktop_outlook_app": desktop_status,
        "graph_connection": {
            "status": graph_status,
            "display_text": graph_display,
            "account_id": primary_graph_acc
        },
        "gemini_configured": has_gemini,
        "active_resume": settings.get("user_profile", {}).get("active_resume_file", "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"),
        "available_resumes": resumes,
        "cached_emails_count": len(CACHED_EMAILS),
        "auto_pilot_enabled": settings.get("auto_pilot_enabled", False),
        "safety_mode": safety_policy.get_active_safety_mode().value
    }


@app.get("/api/safety-policy")
def get_safety_policy_endpoint():
    """Read-only reporting of active Mail Safety Policy and foundational security invariants."""
    mode = safety_policy.get_active_safety_mode()
    return {
        "status": "SUCCESS",
        "active_mode": mode.value,
        "is_draft_only": mode == MailSafetyMode.DRAFT_ONLY,
        "is_manual_send_only": mode == MailSafetyMode.MANUAL_SEND_ONLY,
        "permanent_invariants": [
            "BACKGROUND EXECUTION -> SEND FORBIDDEN (Daemon, Background Radar, Scheduled Jobs are strictly forbidden from transmitting email)",
            "FAIL-CLOSED -> DRAFT_ONLY (Missing, malformed, or corrupt configuration resolves to DRAFT_ONLY)"
        ]
    }

@app.get("/api/accounts")
def list_accounts_endpoint():
    """Returns all configured accounts with validated connection statuses and capabilities."""
    accounts = provider_manager.list_all_accounts()
    return [a.model_dump() for a in accounts]

@app.post("/api/accounts/{account_id}/test", dependencies=[Depends(require_local_auth)])
def test_account_connection(account_id: str):
    provider, _ = provider_manager.get_provider_for_account(account_id)
    res = provider.validate_connection(account_id)
    return res.model_dump()

@app.post("/api/accounts/{account_id}/disconnect", dependencies=[Depends(require_local_auth)])
def disconnect_account(account_id: str):
    provider, _ = provider_manager.get_provider_for_account(account_id)
    res = provider.logout(account_id)
    return res.model_dump()

@app.get("/api/settings")
def get_settings():
    settings = load_settings()
    raw_key = get_secret("gemini_api_key", "GEMINI_API_KEY") or ""
    masked_key = mask_secret(raw_key)
    google_secret = get_secret("google_client_secret", "GOOGLE_CLIENT_SECRET") or settings.get("google_client_secret", "")

    return {
        "gemini_api_key_masked": masked_key,
        "has_gemini_api_key": bool(raw_key),
        "azure_client_id": settings.get("azure_client_id", ""),
        "azure_tenant_id": settings.get("azure_tenant_id", "common"),
        "google_client_id": settings.get("google_client_id", "") or os.getenv("GOOGLE_CLIENT_ID", ""),
        "has_google_client_secret": bool(google_secret),
        "google_client_secret_masked": mask_secret(google_secret) if google_secret else "",
        "auto_pilot_enabled": settings.get("auto_pilot_enabled", False),
        "safe_folder_name": settings.get("safe_folder_name", "AI Cleaned - Noise"),
        "demo_mode": settings.get("demo_mode", False),
        "configured_accounts": settings.get("configured_accounts", [])
    }

@app.post("/api/settings", dependencies=[Depends(require_local_auth)])
def update_settings_endpoint(payload: Dict[str, Any]):
    settings = load_settings()
    
    if "gemini_api_key" in payload and payload["gemini_api_key"]:
        key_val = payload["gemini_api_key"].strip()
        if not key_val.startswith("YOUR_") and len(key_val) > 10:
            set_secret("gemini_api_key", key_val)
            os.environ["GEMINI_API_KEY"] = key_val

    if "azure_client_id" in payload:
        settings["azure_client_id"] = payload["azure_client_id"].strip()
    if "azure_tenant_id" in payload:
        settings["azure_tenant_id"] = payload["azure_tenant_id"].strip()
    if "google_client_id" in payload:
        settings["google_client_id"] = payload["google_client_id"].strip()
    if "google_client_secret" in payload and payload["google_client_secret"]:
        gsec = payload["google_client_secret"].strip()
        if len(gsec) > 3:
            set_secret("google_client_secret", gsec)
            os.environ["GOOGLE_CLIENT_SECRET"] = gsec
    if "auto_pilot_enabled" in payload:
        settings["auto_pilot_enabled"] = bool(payload["auto_pilot_enabled"])
    if "safe_folder_name" in payload:
        settings["safe_folder_name"] = payload["safe_folder_name"].strip()
    if "demo_mode" in payload:
        settings["demo_mode"] = bool(payload["demo_mode"])

    save_settings(settings)
    provider_manager.reload_config()
    return {"status": "SUCCESS", "message": "Settings updated successfully."}

# --- Cloud OAuth Authentication Endpoints ---

# Microsoft Graph (MSAL) Endpoints
@app.get("/api/auth/msal/url")
def get_msal_auth_url(redirect_uri: Optional[str] = None, account_id: Optional[str] = None, login_hint: Optional[str] = None):
    hint = login_hint or account_id or None
    url = provider_manager.graph_provider.get_auth_url(
        redirect_uri=redirect_uri or f"{CANONICAL_ORIGIN}/api/auth/callback",
        login_hint=hint,
        state=hint
    )
    if not url:
        raise HTTPException(
            status_code=400, 
            detail="Microsoft Azure Client ID is required. Please set it in Settings."
        )
    return {"status": "SUCCESS", "auth_url": url}

@app.post("/api/auth/msal/device-code", dependencies=[Depends(require_local_auth)])
def initiate_msal_device_code():
    global _PENDING_DEVICE_FLOW
    try:
        flow = provider_manager.graph_provider.initiate_device_code_flow()
        _PENDING_DEVICE_FLOW = flow
        return {
            "status": "SUCCESS",
            "user_code": flow.get("user_code"),
            "verification_uri": flow.get("verification_uri", "https://microsoft.com/devicelogin"),
            "message": flow.get("message", "Enter code at https://microsoft.com/devicelogin"),
            "expires_in": flow.get("expires_in", 900)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/msal/device-code/poll", dependencies=[Depends(require_local_auth)])
def poll_msal_device_code(payload: Optional[Dict[str, Any]] = None):
    global _PENDING_DEVICE_FLOW
    if not _PENDING_DEVICE_FLOW:
        raise HTTPException(status_code=400, detail="No active device flow in progress.")
    
    account_id = payload.get("account_id") if payload else None
    res = provider_manager.graph_provider.acquire_token_by_device_flow(_PENDING_DEVICE_FLOW, account_id=account_id)
    if res.success:
        _PENDING_DEVICE_FLOW = None
        CACHED_EMAILS.clear()
        sync_and_triage_inbox()
    return res.model_dump()

@app.get("/api/auth/callback")
def auth_callback(code: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None, state: Optional[str] = None):
    if error:
        logger.error(f"OAuth callback error: {error} - {error_description}")
        return RedirectResponse(f"/?auth_error={error}")
    if not code:
        return RedirectResponse("/?auth_error=no_code")
    try:
        account_id = state if state and "@" in state else None
        res = provider_manager.graph_provider.exchange_code_for_token(code, account_id=account_id)
        if res.success:
            CACHED_EMAILS.clear()
            sync_and_triage_inbox()
            return RedirectResponse("/?auth=success&provider=microsoft")
        else:
            return RedirectResponse(f"/?auth_error={res.error_code}")
    except Exception as ex:
        logger.error(f"Auth token exchange failed: {ex}")
        return RedirectResponse(f"/?auth_error={str(ex)}")

@app.post("/api/auth/submit-code", dependencies=[Depends(require_local_auth)])
def submit_auth_code(payload: Dict[str, str]):
    code_raw = payload.get("code", "").strip()
    account_id = payload.get("account_id", "").strip() or None
    if not code_raw:
        raise HTTPException(status_code=400, detail="Authorization code or URL required.")
    
    # Extract code if full URL was pasted
    code = code_raw
    if "code=" in code_raw:
        import urllib.parse
        parsed = urllib.parse.urlparse(code_raw)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            code = qs["code"][0]

    res = provider_manager.graph_provider.exchange_code_for_token(code, account_id=account_id)
    if res.success:
        CACHED_EMAILS.clear()
        sync_and_triage_inbox()
        return res.model_dump()
    raise HTTPException(status_code=400, detail=res.safe_message)

# Google OAuth (Gmail API) Endpoints
@app.get("/api/auth/google/url")
def get_google_auth_url(redirect_uri: Optional[str] = None):
    url = provider_manager.gmail_provider.get_auth_url(
        redirect_uri=redirect_uri or f"{CANONICAL_ORIGIN}/api/auth/google/callback"
    )
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth Client ID is required. Please set it in Settings, or use Gmail App Password via the IMAP tab."
        )
    return {"status": "SUCCESS", "auth_url": url}

@app.get("/api/auth/google/callback")
def google_auth_callback(code: Optional[str] = None, error: Optional[str] = None, error_description: Optional[str] = None, state: Optional[str] = None):
    if error:
        logger.error(f"Google OAuth callback error: {error} - {error_description}")
        return RedirectResponse(f"/?auth_error={error}")
    if not code:
        return RedirectResponse("/?auth_error=no_code")
    try:
        res = provider_manager.gmail_provider.exchange_code_for_token(code)
        if res.success:
            CACHED_EMAILS.clear()
            sync_and_triage_inbox()
            return RedirectResponse("/?auth=success&provider=google")
        else:
            return RedirectResponse(f"/?auth_error={res.safe_message or res.error_code}")
    except Exception as ex:
        logger.error(f"Google Auth token exchange failed: {ex}")
        return RedirectResponse(f"/?auth_error={str(ex)}")

@app.post("/api/auth/google/submit-code", dependencies=[Depends(require_local_auth)])
def submit_google_auth_code(payload: Dict[str, str]):
    code_raw = payload.get("code", "").strip()
    account_id = payload.get("account_id", "").strip() or None
    redirect_uri = payload.get("redirect_uri", f"{CANONICAL_ORIGIN}/api/auth/google/callback")

    if not code_raw:
        raise HTTPException(status_code=400, detail="Authorization code or URL required.")
    
    code = code_raw
    if "code=" in code_raw:
        import urllib.parse
        parsed = urllib.parse.urlparse(code_raw)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            code = qs["code"][0]

    res = provider_manager.gmail_provider.exchange_code_for_token(code, redirect_uri=redirect_uri, account_id=account_id)
    if res.success:
        CACHED_EMAILS.clear()
        sync_and_triage_inbox()
        return res.model_dump()
    raise HTTPException(status_code=400, detail=res.safe_message)

@app.post("/api/auth/imap", dependencies=[Depends(require_local_auth)])
def auth_imap(payload: Dict[str, str]):
    email_addr = payload.get("email", "").strip().lower()
    password = payload.get("password", "").strip()
    imap_server_raw = payload.get("imap_server", "").strip()
    
    imap_host, imap_port = provider_manager.imap_provider._parse_host_port(imap_server_raw, 993)
    
    if not email_addr or not password:
        raise HTTPException(status_code=400, detail="Email and password are required.")
    
    settings = load_settings()
    configured = settings.get("configured_accounts", [])
    
    # Update or add IMAP account configuration
    found = False
    for acc in configured:
        if acc.get("account_id", "").lower() == email_addr:
            acc["provider"] = "IMAP"
            acc["imap_server"] = imap_host or acc.get("imap_server", "mail.twc.com")
            acc["imap_port"] = imap_port
            acc.pop("smtp_server", None)
            acc.pop("smtp_port", None)
            found = True
            break
    if not found:
        configured.append({
            "account_id": email_addr,
            "email": email_addr,
            "provider": "IMAP",
            "display_name": email_addr,
            "imap_server": imap_host or "mail.twc.com",
            "imap_port": imap_port,
            "enabled": True
        })
    settings["configured_accounts"] = configured
    save_settings(settings)

    res = provider_manager.imap_provider.authenticate({"account_id": email_addr, "email": email_addr}, {"password": password})
    if res.success:
        CACHED_EMAILS.clear()
        sync_and_triage_inbox()
        return res.model_dump()
    raise HTTPException(status_code=400, detail=res.safe_message)

# --- Profile & Resume Catalog Endpoints ---

from backend.canonical_engine import (
    scan_canonical_system,
    find_best_resume_match,
    get_canonical_ledger_summary,
    resolve_resume_file,
    LENS_DEFINITIONS,
    LOCKED_FACTS
)

@app.get("/api/profile")
def get_profile():
    return get_user_profile()

@app.post("/api/profile", dependencies=[Depends(require_local_auth)])
def update_profile(profile: UserProfile):
    update_user_profile(profile)
    return {"status": "SUCCESS", "profile": profile}

@app.get("/api/canonical/resumes")
@app.get("/api/canonical/catalog")
def get_canonical_resumes(refresh: bool = False):
    return scan_canonical_system(force_refresh=refresh)

@app.post("/api/canonical/match", dependencies=[Depends(require_local_auth)])
def match_canonical_resume(payload: Dict[str, Any]):
    job_title = payload.get("job_title", "")
    job_description = payload.get("job_description", "")
    sender = payload.get("sender", "")
    return find_best_resume_match(job_title=job_title, job_description=job_description, sender=sender)

@app.get("/api/canonical/ledger")
def get_canonical_ledger():
    return {"status": "SUCCESS", "ledger": get_canonical_ledger_summary()}

from backend.canonical_grounding import (
    validate_canonical_grounding,
    generate_canonical_claim,
    verify_provenance_claim,
    verify_provenance_claim_binding,
    ClaimBlockBinding,
    canonicalize_binding_manifest,
    compute_manifest_digest,
    capture_risk_evaluation_snapshot,
    verify_risk_evaluation_snapshot,
    get_available_templates,
    GroundingStatus,
    ClaimStatus,
    compute_sha256,
    PROVENANCE_STORE,
    InvalidationPersistenceError,
)

import threading
_EMAIL_STATE_LOCK = threading.RLock()


def safely_invalidate_draft_authority(
    draft_id: Optional[str],
    email_msg: Optional[EmailMessage] = None,
    reason: str = "Draft invalidation requested"
) -> Tuple[str, Optional[str]]:
    """
    Unified fail-closed invalidation helper across all route handlers.
    Returns (status, detail_message):
    - ("DURABLY_INVALIDATED", None): invalidation successfully persisted or draft already invalidated
    - ("INVALIDATION_PERSISTENCE_FAILURE", error_msg): persistence failed and draft identity was quarantined
    - ("PROVENANCE_STORE_UNAVAILABLE", error_msg): persistence/quarantine failed and store was disabled
    - ("NO_OP", None): no draft_id provided
    """
    if not draft_id:
        if email_msg:
            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = GroundingStatus.UNVERIFIED.value
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.invalidation_issued = True
            email_msg.draft_version += 1
        return "NO_OP", None

    did_clean = draft_id.strip() if isinstance(draft_id, str) else str(draft_id)

    if not PROVENANCE_STORE.is_available():
        if email_msg:
            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = GroundingStatus.VALIDATION_FAILED.value
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.invalidation_issued = True
            email_msg.draft_version += 1
        return "PROVENANCE_STORE_UNAVAILABLE", "Provenance store is unavailable."

    try:
        PROVENANCE_STORE.invalidate_draft_claims(did_clean, reason=reason)
        if email_msg:
            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = GroundingStatus.UNVERIFIED.value
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.invalidation_issued = True
            email_msg.draft_version += 1
        return "DURABLY_INVALIDATED", None
    except InvalidationPersistenceError as ipe:
        logger.error(f"Persistence error invalidating draft {did_clean}: {ipe}")
        quarantine_ok = False
        try:
            PROVENANCE_STORE.quarantine_draft(did_clean)
            quarantine_ok = PROVENANCE_STORE.is_draft_quarantined(did_clean)
        except Exception as q_err:
            logger.critical(f"Draft quarantine failed for {did_clean}: {q_err}")
            quarantine_ok = False

        if email_msg:
            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = GroundingStatus.VALIDATION_FAILED.value
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.invalidation_issued = True
            email_msg.draft_version += 1

        if quarantine_ok:
            return "INVALIDATION_PERSISTENCE_FAILURE", str(ipe)
        else:
            PROVENANCE_STORE.disable_store(f"Quarantine verification failed for draft '{did_clean}': {ipe}")
            return "PROVENANCE_STORE_UNAVAILABLE", f"Quarantine failed; store disabled: {ipe}"
    except Exception as e:
        logger.critical(f"Unexpected exception during draft invalidation for {did_clean}: {e}")
        quarantine_ok = False
        try:
            PROVENANCE_STORE.quarantine_draft(did_clean)
            quarantine_ok = PROVENANCE_STORE.is_draft_quarantined(did_clean)
        except Exception as q_err:
            logger.critical(f"Quarantine after unexpected exception failed for {did_clean}: {q_err}")
            quarantine_ok = False

        if email_msg:
            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = GroundingStatus.VALIDATION_FAILED.value
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.invalidation_issued = True
            email_msg.draft_version += 1

        if quarantine_ok:
            return "INVALIDATION_PERSISTENCE_FAILURE", f"Unexpected invalidation error; quarantined: {e}"
        else:
            PROVENANCE_STORE.disable_store(f"Unexpected invalidation error and quarantine failure for draft '{did_clean}': {e}")
            return "PROVENANCE_STORE_UNAVAILABLE", f"Store disabled due to unexpected invalidation failure: {e}"


@app.get("/api/canonical/templates", dependencies=[Depends(require_local_auth)])
def list_canonical_templates(fact_id: Optional[str] = None):
    return {
        "status": "SUCCESS",
        "templates": get_available_templates(fact_id=fact_id)
    }

@app.post("/api/canonical/claims/generate", dependencies=[Depends(require_local_auth)])
def generate_claim_endpoint(payload: Dict[str, Any]):
    fact_id = payload.get("fact_id") or payload.get("canonical_fact_id")
    if not fact_id:
        raise HTTPException(status_code=400, detail="canonical_fact_id is required")
    draft_id = payload.get("draft_id")
    if not draft_id or not str(draft_id).strip():
        raise HTTPException(status_code=400, detail="draft_id is mandatory and cannot be empty")
    template_id = payload.get("template_id")
    style_variant = payload.get("style_variant")
    try:
        claim_meta = generate_canonical_claim(
            fact_id=fact_id,
            template_id=template_id,
            style_variant=style_variant,
            draft_id=str(draft_id).strip()
        )
        return {"status": "SUCCESS", "claim": claim_meta}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/canonical/claims/verify", dependencies=[Depends(require_local_auth)])
def verify_claim_endpoint(payload: Dict[str, Any]):
    claim_id = payload.get("claim_instance_id")
    submitted_text = payload.get("submitted_block_text") or payload.get("submitted_text")
    draft_id = payload.get("draft_id")
    start_offset = payload.get("start_offset")
    end_offset = payload.get("end_offset")
    block_id = payload.get("block_id")
    draft_text = payload.get("draft_text")

    is_valid, c_status, c_reason, supp = verify_provenance_claim(
        claim_instance_id=claim_id,
        submitted_text=submitted_text,
        draft_id=draft_id,
        draft_text=draft_text,
        start_offset=start_offset,
        end_offset=end_offset,
        block_id=block_id
    )

    return {
        "status": "SUCCESS" if is_valid else "VALIDATION_FAILED",
        "is_valid": is_valid,
        "claim_status": c_status.value if hasattr(c_status, "value") else str(c_status),
        "reason": c_reason,
        "claim": supp.model_dump() if supp else None
    }

@app.post("/api/canonical/validate", dependencies=[Depends(require_local_auth)])
def validate_canonical_endpoint(payload: Dict[str, Any]):
    draft_text = payload.get("draft_text") or payload.get("text") or ""
    claim_bindings = payload.get("claim_bindings")
    provenance_claims = payload.get("provenance_claims")
    recipient_company = payload.get("recipient_company")
    draft_id = payload.get("draft_id")
    res = validate_canonical_grounding(
        draft_text=draft_text,
        claim_bindings=claim_bindings,
        provenance_claims=provenance_claims,
        recipient_company=recipient_company,
        draft_id=draft_id
    )
    return res.model_dump()

@app.get("/api/resumes")
def list_resumes():
    catalog = scan_canonical_system()
    return {
        "status": "SUCCESS",
        "total": catalog.get("total_resumes", 0),
        "all_resumes": catalog.get("all_resumes", []),
        "standard_canonicals": catalog.get("standard_canonicals", []),
        "targeted_customs": catalog.get("targeted_customs", []),
        "master_variants": catalog.get("master_variants", []),
        "source_of_truth_docs": catalog.get("source_of_truth_docs", []),
        "lenses": LENS_DEFINITIONS
    }

@app.post("/api/profile/upload-resume", dependencies=[Depends(require_local_auth)])
async def upload_resume(file: UploadFile = File(...)):
    dest_path = RESUMES_DIR / file.filename
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    profile = get_user_profile()
    profile.active_resume_file = file.filename
    update_user_profile(profile)
    
    return {
        "status": "SUCCESS", 
        "filename": file.filename, 
        "message": f"Resume '{file.filename}' uploaded and set as active."
    }

# --- Email Sync & Triage Endpoints ---

class ResolveItemRequest(BaseModel):
    provider: str = Field(default="MICROSOFT_GRAPH")
    account_id: Optional[str] = None
    item_id: str

@app.get("/api/emails")
def list_emails(category: Optional[str] = None):
    results = list(CACHED_EMAILS.values())
    if category:
        cat_upper = category.upper()
        if cat_upper == "NOISE":
            results = [e for e in results if e.classification and e.classification.is_noise]
        elif cat_upper == "RESUME_REQUEST":
            results = [e for e in results if e.classification and e.classification.is_resume_request]
        elif cat_upper == "OTHER":
            results = [e for e in results if e.classification and not e.classification.is_noise and not e.classification.is_resume_request]
    
    return results

@app.post("/api/emails/resolve-item", dependencies=[Depends(require_local_auth)])
def resolve_email_item(payload: ResolveItemRequest):
    """
    Unified Outlook Item Resolver (Phase 2.1).
    Maps normalized Microsoft Graph REST item IDs to Aura cached/composite message IDs.
    Fails closed on missing auth (401), invalid origin/token (403), empty ID (400),
    unknown item (404), or ambiguous matches across accounts (409).
    """
    raw_item_id = payload.item_id.strip()
    if not raw_item_id:
        raise HTTPException(status_code=400, detail="Item ID is required for resolution.")

    target_provider = payload.provider.strip().upper()
    target_account = payload.account_id.strip().lower() if payload.account_id else None

    matched_emails = []
    for email_id, email_msg in CACHED_EMAILS.items():
        msg_prov, msg_acc, msg_native = decode_composite_id(email_id)
        if msg_prov == target_provider or (target_provider == "MICROSOFT_GRAPH" and msg_prov in ["MICROSOFT_GRAPH", "GRAPH"]):
            if target_account and msg_acc and msg_acc.lower() != target_account:
                continue
            if msg_native == raw_item_id or email_id == raw_item_id:
                matched_emails.append(email_msg)

    if len(matched_emails) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Ambiguous item resolution: multiple items match '{raw_item_id}' across accounts."
        )

    if not matched_emails:
        raise HTTPException(
            status_code=404,
            detail=f"Item '{raw_item_id}' not found in local cache."
        )

    resolved_msg = matched_emails[0]
    return {
        "status": "SUCCESS",
        "found": True,
        "composite_id": resolved_msg.id,
        "email": resolved_msg.model_dump()
    }


@app.post("/api/emails/sync", dependencies=[Depends(require_local_auth)])
def sync_and_triage_inbox(force_refresh: bool = False):
    emails, sync_stats = provider_manager.sync_unified_inbox(limit_per_account=50)
    user_profile = get_user_profile()
    settings = load_settings()
    auto_pilot = settings.get("auto_pilot_enabled", False)
    
    triaged_count = 0
    noise_count = 0
    recruiter_count = 0
    
    for email_msg in emails:
        if email_msg.id not in CACHED_EMAILS or not CACHED_EMAILS[email_msg.id].classification or force_refresh:
            classification = classify_email(email_msg)
            email_msg.classification = classification
            
            if classification.is_resume_request:
                recruiter_count += 1
                if classification.resume_match and classification.resume_match.selected_resume:
                    email_msg.selected_resume_file = classification.resume_match.selected_resume
                else:
                    email_msg.selected_resume_file = user_profile.active_resume_file
                
                email_msg.draft_reply = generate_personalized_reply(email_msg, user_profile)
                
                # Record in Analytics SQLite
                record_opportunity(
                    email_id=email_msg.id,
                    subject=email_msg.subject,
                    sender_name=email_msg.sender_name,
                    sender_email=email_msg.sender_email,
                    recruiter_details=classification.recruiter_details,
                    resume_match=classification.resume_match,
                    status="INBOUND",
                    received_at=email_msg.received_at
                )
                log_event(
                    event_type="EMAIL_TRIAGED",
                    opportunity_id=email_msg.id,
                    lens=classification.resume_match.matching_lens if classification.resume_match else None,
                    resume_file=email_msg.selected_resume_file,
                    details=f"Inbound reachout from {email_msg.sender_name} ({classification.recruiter_details.company_name if classification.recruiter_details else ''})",
                    confidence=classification.confidence
                )
            elif classification.is_noise:
                noise_count += 1
                log_event(
                    event_type="NOISE_CLEANED",
                    details=f"Filtered {classification.category.value}: {email_msg.subject[:50]}"
                )
            
            CACHED_EMAILS[email_msg.id] = email_msg
            triaged_count += 1
    
    save_cached_emails()
    
    return {
        "status": "SUCCESS",
        "total_emails": len(CACHED_EMAILS),
        "newly_triaged": triaged_count,
        "noise_detected": noise_count,
        "resume_requests_found": recruiter_count,
        "sync_stats": sync_stats
    }

@app.post("/api/emails/{email_id}/generate-reply", dependencies=[Depends(require_local_auth)])
def generate_reply_for_email(email_id: str, request_params: ReplyDraftRequest):
    if email_id not in CACHED_EMAILS:
        raise HTTPException(status_code=404, detail="Email not found")
    
    with _EMAIL_STATE_LOCK:
        email_msg = CACHED_EMAILS[email_id]
        user_profile = get_user_profile()
        draft_id = f"draft_email_{email_id}_{uuid.uuid4().hex[:8]}"

    from backend.radar.scribe_service import generate_executive_reply_structured
    scribe_res = generate_executive_reply_structured(
        email=email_msg,
        user_profile=user_profile,
        request_params=request_params,
        draft_id=draft_id
    )

    with _EMAIL_STATE_LOCK:
        email_msg.draft_reply = scribe_res.draft_text
        email_msg.draft_id = scribe_res.draft_id
        email_msg.draft_version += 1
        email_msg.claim_bindings = scribe_res.claim_bindings
        email_msg.grounding_status = scribe_res.grounding_status
        email_msg.is_grounded = scribe_res.is_grounded
        email_msg.draft_text_hash = compute_sha256(scribe_res.draft_text)
        email_msg.risk_result = None
        email_msg.risk_draft_id = None
        email_msg.risk_draft_text_hash = None
        email_msg.risk_is_current = False
        email_msg.invalidation_issued = False
        save_cached_emails()

        log_event(
            event_type="DRAFT_GENERATED",
            opportunity_id=email_id,
            resume_file=request_params.selected_resume or email_msg.selected_resume_file,
            details=f"Draft regenerated with {request_params.tone} tone (draft_id={scribe_res.draft_id}, grounded={scribe_res.is_grounded})."
        )

        return {
            "status": "SUCCESS",
            "email_id": email_id,
            "draft_id": scribe_res.draft_id,
            "draft_reply": scribe_res.draft_text,
            "draft_text_hash": email_msg.draft_text_hash,
            "claim_bindings": scribe_res.claim_bindings,
            "grounding_status": scribe_res.grounding_status,
            "is_grounded": scribe_res.is_grounded,
            "validation_summary": scribe_res.validation_summary
        }

@app.post("/api/emails/{email_id}/save-draft", dependencies=[Depends(require_local_auth)])
def save_draft_to_cloud(email_id: str, payload: Dict[str, Any]):
    if email_id not in CACHED_EMAILS:
        raise HTTPException(status_code=404, detail="Email not found")
    
    with _EMAIL_STATE_LOCK:
        email_msg = CACHED_EMAILS[email_id]
        reply_body = payload.get("reply_body", email_msg.draft_reply or "")
        user_profile = get_user_profile()
        resume_file = payload.get("resume_filename", user_profile.active_resume_file)
        req_draft_id = payload.get("draft_id")
        req_claim_bindings = payload.get("claim_bindings")
        req_text_hash = compute_sha256(reply_body) if reply_body else None

        is_still_grounded = False
        grounding_status_val = GroundingStatus.UNVERIFIED.value
        validation_summary = "Grounding unverified for staged draft."

        submitted_canonical = canonicalize_binding_manifest(req_claim_bindings)
        cached_canonical = canonicalize_binding_manifest(email_msg.claim_bindings)

        # Require exact match: draft_id, exact draft text hash, and exact canonical 6-field manifest
        is_exact_match = (
            bool(req_draft_id) and
            bool(email_msg.draft_id) and
            req_draft_id == email_msg.draft_id and
            bool(req_text_hash) and
            bool(email_msg.draft_text_hash) and
            req_text_hash == email_msg.draft_text_hash and
            submitted_canonical is not None and
            cached_canonical is not None and
            submitted_canonical == cached_canonical
        )

        if is_exact_match:
            val_res = validate_canonical_grounding(
                draft_text=reply_body,
                claim_bindings=submitted_canonical,
                draft_id=req_draft_id
            )
            is_still_grounded = val_res.is_grounded
            grounding_status_val = val_res.status.value if hasattr(val_res.status, "value") else str(val_res.status)
            validation_summary = val_res.validation_summary

            if not is_still_grounded:
                inv_status, inv_err = safely_invalidate_draft_authority(
                    email_msg.draft_id,
                    email_msg=email_msg,
                    reason="Draft claims validation failed during save"
                )
                if inv_status in ("INVALIDATION_PERSISTENCE_FAILURE", "PROVENANCE_STORE_UNAVAILABLE"):
                    save_cached_emails()
                    return {
                        "success": False,
                        "status": inv_status,
                        "error_code": inv_status,
                        "is_grounded": False,
                        "grounding_status": GroundingStatus.VALIDATION_FAILED.value,
                        "risk_is_current": False,
                        "requires_human_review": True,
                        "validation_summary": f"Provenance invalidation persistence failed ({inv_status}). Authority quarantined; manual review required ({inv_err}).",
                        "safe_message": "Draft invalidation persistence failed. Content was not saved to prevent unpersisted state divergence."
                    }
        else:
            # Divergence or manifest substitution detected
            if email_msg.draft_id:
                inv_status, inv_err = safely_invalidate_draft_authority(
                    email_msg.draft_id,
                    email_msg=email_msg,
                    reason="Draft divergence or manifest substitution detected during save"
                )
                if inv_status in ("INVALIDATION_PERSISTENCE_FAILURE", "PROVENANCE_STORE_UNAVAILABLE"):
                    save_cached_emails()
                    return {
                        "success": False,
                        "status": inv_status,
                        "error_code": inv_status,
                        "is_grounded": False,
                        "grounding_status": GroundingStatus.VALIDATION_FAILED.value,
                        "risk_is_current": False,
                        "requires_human_review": True,
                        "validation_summary": f"Draft divergence detected and invalidation persistence failed ({inv_status}). Authority quarantined; manual review required ({inv_err}).",
                        "safe_message": "Draft invalidation persistence failed. Manual review required."
                    }

            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = GroundingStatus.VALIDATION_FAILED.value if req_draft_id else GroundingStatus.UNVERIFIED.value
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.draft_version += 1
            is_still_grounded = False
            grounding_status_val = email_msg.grounding_status
            validation_summary = "Draft divergence, manifest mismatch, or unprovenanced text; prior grounding authority invalidated."

        # Update draft reply in cache
        email_msg.draft_reply = reply_body
        if is_still_grounded:
            email_msg.draft_id = req_draft_id
            email_msg.claim_bindings = submitted_canonical
            email_msg.draft_text_hash = req_text_hash
            email_msg.is_grounded = True
            email_msg.grounding_status = grounding_status_val

    # Execute cloud operation under draft-first policy
    result = provider_manager.save_draft_reply(
        message_id=email_msg.id,
        reply_body=reply_body,
        resume_filename=resume_file
    )
    
    with _EMAIL_STATE_LOCK:
        # Update cache and analytics ONLY on confirmed success
        if result.success:
            email_msg.status = "DRAFTED"
            save_cached_emails()
            update_opportunity_stage(email_id, "DRAFTED")
            log_event(
                event_type="DRAFT_SAVED",
                opportunity_id=email_id,
                resume_file=resume_file,
                details=f"Draft created in {result.provider} with {resume_file} attached (grounded={is_still_grounded})."
            )
        else:
            logger.warning(f"Failed to save draft for {email_id}: {result.safe_message}")

        res_dict = result.model_dump()
        res_dict["is_grounded"] = is_still_grounded
        res_dict["grounding_status"] = grounding_status_val
        res_dict["validation_summary"] = validation_summary
        return res_dict

@app.post("/api/emails/{email_id}/risk-check", dependencies=[Depends(require_local_auth)])
def email_risk_check_endpoint(email_id: str, payload: Dict[str, Any]):
    """
    Email-scoped Risk Sentinel check bound to server-cached draft identity and text hash.
    Enforces atomic snapshot compare-and-set to guarantee that asynchronous model evaluation
    cannot commit against a stale, invalidated, replaced, or quarantined draft.
    """
    if email_id not in CACHED_EMAILS:
        raise HTTPException(status_code=404, detail="Email not found")

    with _EMAIL_STATE_LOCK:
        email_msg = CACHED_EMAILS[email_id]
        req_draft_id = payload.get("draft_id")
        draft_text = payload.get("draft_text", payload.get("draft_reply", email_msg.draft_reply or ""))
        req_bindings = payload.get("claim_bindings")
        proposed_action = payload.get("proposed_action", "DRAFT")
        execution_context = payload.get("execution_context")
        req_text_hash = compute_sha256(draft_text) if draft_text else None

        submitted_canonical = canonicalize_binding_manifest(req_bindings)
        cached_canonical = canonicalize_binding_manifest(email_msg.claim_bindings)

        is_exact_match = (
            bool(req_draft_id) and
            bool(email_msg.draft_id) and
            req_draft_id == email_msg.draft_id and
            bool(req_text_hash) and
            bool(email_msg.draft_text_hash) and
            req_text_hash == email_msg.draft_text_hash and
            submitted_canonical is not None and
            cached_canonical is not None and
            submitted_canonical == cached_canonical
        )

        if not is_exact_match:
            # Invalidate cached draft if divergence or manifest mismatch occurred on a previously grounded draft
            if email_msg.draft_id:
                inv_status, inv_err = safely_invalidate_draft_authority(
                    email_msg.draft_id,
                    email_msg=email_msg,
                    reason="Draft divergence or manifest mismatch detected during risk check"
                )
                if inv_status in ("INVALIDATION_PERSISTENCE_FAILURE", "PROVENANCE_STORE_UNAVAILABLE"):
                    save_cached_emails()
                    return {
                        "status": inv_status,
                        "error_code": inv_status,
                        "risk": None,
                        "is_grounded": False,
                        "grounding_status": GroundingStatus.VALIDATION_FAILED.value,
                        "email_id": email_id,
                        "draft_id": None,
                        "draft_text_hash": req_text_hash,
                        "risk_is_current": False,
                        "requires_human_review": True,
                        "validation_summary": f"Provenance invalidation persistence failed during divergence detection ({inv_status}). Authority quarantined; human review required ({inv_err})."
                    }

            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = GroundingStatus.VALIDATION_FAILED.value if req_draft_id else GroundingStatus.UNVERIFIED.value
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.draft_version += 1
            save_cached_emails()

            # Evaluate risk for ungrounded prose
            res = evaluate_second_opinion_risk(
                email=email_msg,
                draft_reply=draft_text,
                proposed_action=proposed_action,
                execution_context=execution_context,
                user_profile=get_user_profile(),
                draft_id=None,
                claim_bindings=None,
                provenance_claims=None
            )
            return {
                "status": "DIVERGENCE_DETECTED",
                "risk": res.model_dump(),
                "is_grounded": False,
                "grounding_status": email_msg.grounding_status,
                "email_id": email_id,
                "draft_id": None,
                "draft_text_hash": req_text_hash,
                "risk_is_current": False,
                "validation_summary": "Draft divergence, manifest mismatch, or draft_id mismatch: risk evaluated for ungrounded draft text."
            }

        # Authoritative path: validate manifest & bindings
        val_res = validate_canonical_grounding(
            draft_text=draft_text,
            claim_bindings=submitted_canonical,
            draft_id=email_msg.draft_id
        )

        if not val_res.is_grounded:
            inv_status, inv_err = safely_invalidate_draft_authority(
                email_msg.draft_id,
                email_msg=email_msg,
                reason="Draft claims invalid during risk check"
            )
            if inv_status in ("INVALIDATION_PERSISTENCE_FAILURE", "PROVENANCE_STORE_UNAVAILABLE"):
                save_cached_emails()
                return {
                    "status": inv_status,
                    "error_code": inv_status,
                    "risk": None,
                    "is_grounded": False,
                    "grounding_status": GroundingStatus.VALIDATION_FAILED.value,
                    "email_id": email_id,
                    "draft_id": None,
                    "draft_text_hash": req_text_hash,
                    "risk_is_current": False,
                    "requires_human_review": True,
                    "validation_summary": f"Provenance invalidation persistence failed during claim validation ({inv_status}). Authority quarantined; human review required ({inv_err})."
                }

            email_msg.draft_id = None
            email_msg.claim_bindings = []
            email_msg.draft_text_hash = None
            email_msg.is_grounded = False
            email_msg.grounding_status = val_res.status.value if hasattr(val_res.status, "value") else str(val_res.status)
            email_msg.risk_result = None
            email_msg.risk_draft_id = None
            email_msg.risk_draft_text_hash = None
            email_msg.risk_is_current = False
            email_msg.draft_version += 1
            save_cached_emails()

            res = evaluate_second_opinion_risk(
                email=email_msg,
                draft_reply=draft_text,
                proposed_action=proposed_action,
                execution_context=execution_context,
                user_profile=get_user_profile(),
                draft_id=None,
                claim_bindings=None,
                provenance_claims=None
            )
            return {
                "status": "VALIDATION_FAILED",
                "risk": res.model_dump(),
                "is_grounded": False,
                "grounding_status": email_msg.grounding_status,
                "email_id": email_id,
                "draft_id": None,
                "draft_text_hash": req_text_hash,
                "risk_is_current": False,
                "validation_summary": f"Claim validation failed during risk check: {val_res.validation_summary}"
            }

        # Capture immutable snapshot BEFORE releasing lock for slow evaluation
        snapshot = capture_risk_evaluation_snapshot(email_id, email_msg)
        if not snapshot:
            save_cached_emails()
            return {
                "status": "SNAPSHOT_CAPTURE_FAILED",
                "error_code": "SNAPSHOT_CAPTURE_FAILED",
                "risk": None,
                "is_grounded": False,
                "grounding_status": email_msg.grounding_status if email_msg else GroundingStatus.VALIDATION_FAILED.value,
                "email_id": email_id,
                "draft_id": None,
                "draft_text_hash": req_text_hash,
                "risk_is_current": False,
                "requires_human_review": True,
                "validation_summary": "Authoritative risk snapshot capture failed; risk evaluation denied."
            }
        eval_draft_id = email_msg.draft_id
        eval_bindings = submitted_canonical

    # Slow / asynchronous model evaluation happens outside lock
    res = evaluate_second_opinion_risk(
        email=email_msg,
        draft_reply=draft_text,
        proposed_action=proposed_action,
        execution_context=execution_context,
        user_profile=get_user_profile(),
        draft_id=eval_draft_id,
        claim_bindings=eval_bindings,
        provenance_claims=None
    )

    # Reacquire lock for atomic compare-and-set
    with _EMAIL_STATE_LOCK:
        current_email = CACHED_EMAILS.get(email_id)
        is_valid_snapshot, snapshot_reason = verify_risk_evaluation_snapshot(snapshot, current_email)

        if not is_valid_snapshot:
            logger.warning(f"Discarding stale risk evaluation for email '{email_id}': {snapshot_reason}")
            if not PROVENANCE_STORE.is_available():
                fail_status = "PROVENANCE_STORE_UNAVAILABLE"
            elif PROVENANCE_STORE.is_draft_quarantined(snapshot.draft_id):
                fail_status = "QUARANTINED"
            elif current_email and current_email.draft_id != snapshot.draft_id:
                fail_status = "STALE_EVALUATION"
            elif current_email and current_email.draft_text_hash != snapshot.cached_draft_text_hash:
                fail_status = "DIVERGENCE_DETECTED"
            else:
                fail_status = "STALE_EVALUATION"

            return {
                "status": fail_status,
                "risk": res.model_dump(),
                "is_grounded": False,
                "grounding_status": current_email.grounding_status if current_email else GroundingStatus.UNVERIFIED.value,
                "email_id": email_id,
                "draft_id": None,
                "draft_text_hash": None,
                "risk_is_current": False,
                "requires_human_review": True,
                "validation_summary": f"Risk evaluation discarded: {snapshot_reason}"
            }

        # Snapshot verified: install authoritative risk result
        current_email.risk_result = res.model_dump()
        current_email.risk_draft_id = snapshot.draft_id
        current_email.risk_draft_text_hash = snapshot.cached_draft_text_hash
        current_email.risk_is_current = True
        save_cached_emails()

        return {
            "status": "SUCCESS",
            "risk": res.model_dump(),
            "is_grounded": current_email.is_grounded,
            "grounding_status": current_email.grounding_status,
            "email_id": email_id,
            "draft_id": snapshot.draft_id,
            "draft_text_hash": snapshot.cached_draft_text_hash,
            "risk_is_current": True,
            "validation_summary": "Risk assessment completed and bound to active draft."
        }

@app.post("/api/emails/{email_id}/invalidate-draft", dependencies=[Depends(require_local_auth)])
def invalidate_email_draft_endpoint(email_id: str, payload: Optional[Dict[str, Any]] = None):
    """
    Same-origin authenticated endpoint to persistently invalidate draft provenance on manual edit.
    Enforces strict ownership: requires explicit non-empty draft_id matching the active draft
    cached for the addressed email. Fails closed and quarantines authority if persistence fails.
    """
    if email_id not in CACHED_EMAILS:
        raise HTTPException(status_code=404, detail="Email not found")

    with _EMAIL_STATE_LOCK:
        email_msg = CACHED_EMAILS[email_id]
        p = payload or {}
        req_draft_id = p.get("draft_id")

        # Request MUST contain explicit non-empty draft_id
        if not req_draft_id or not isinstance(req_draft_id, str) or not req_draft_id.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "VALIDATION_FAILED",
                    "message": "Explicit non-empty draft_id is required in request payload for invalidation."
                }
            )

        req_draft_id = req_draft_id.strip()

        # Cached email must have an active draft_id and it must match request draft_id
        if not email_msg.draft_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "STALE_DRAFT",
                    "message": "Addressed email has no active cached draft to invalidate."
                }
            )

        if email_msg.draft_id != req_draft_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "DRAFT_ID_MISMATCH",
                    "message": "Submitted draft_id does not match active draft for addressed email."
                }
            )

        # Exact active email/draft association confirmed -> perform persistent invalidation
        inv_status, inv_err = safely_invalidate_draft_authority(
            req_draft_id,
            email_msg=email_msg,
            reason="Manual draft edit in client"
        )
        save_cached_emails()

        if inv_status in ("INVALIDATION_PERSISTENCE_FAILURE", "PROVENANCE_STORE_UNAVAILABLE"):
            raise HTTPException(
                status_code=500,
                detail={
                    "status": inv_status,
                    "error_code": inv_status,
                    "message": f"Provenance invalidation persistence failed. {'Authority quarantined' if inv_status == 'INVALIDATION_PERSISTENCE_FAILURE' else 'Store disabled'}; manual review required ({inv_err}).",
                    "requires_human_review": True,
                    "quarantined": inv_status == "INVALIDATION_PERSISTENCE_FAILURE"
                }
            )

        return {
            "status": "INVALIDATED",
            "email_id": email_id,
            "draft_id": req_draft_id,
            "is_grounded": False,
            "grounding_status": GroundingStatus.UNVERIFIED.value,
            "risk_is_current": False
        }

@app.post("/api/emails/{email_id}/send-reply", dependencies=[Depends(require_local_auth)])
def send_email_reply(email_id: str, payload: Optional[SendReplyRequest] = None):
    """
    Direct Mail Transmission Endpoint (Permanently Disabled).
    Enforces the zero-transmission invariant: Aura cannot transmit mail.
    Drafts must be staged via /api/emails/{id}/save-draft and sent via native client.
    """
    raise HTTPException(
        status_code=403,
        detail={
            "error_code": "SEND_FORBIDDEN",
            "message": "Mail Transmission Blocked: Aura direct mail transmission is permanently disabled. Outbound mail must be staged as a draft and sent exclusively by the user through their native mail client.",
            "safety_mode": safety_policy.get_active_safety_mode().value,
        }
    )

@app.post("/api/emails/clean-noise", dependencies=[Depends(require_local_auth)])
def clean_all_noise_endpoint():
    settings = load_settings()
    folder_name = settings.get("safe_folder_name", "AI Cleaned - Noise")
    
    cleaned_ids = []
    failed_moves = []
    
    for email_id, email_msg in list(CACHED_EMAILS.items()):
        if email_msg.classification and email_msg.classification.is_noise and email_msg.status != "TRASHED":
            res = provider_manager.move_message(email_msg.id, folder_name)
            if res.success:
                email_msg.status = "TRASHED"
                cleaned_ids.append(email_id)
                log_event("NOISE_CLEANED", details=f"Moved '{email_msg.subject[:40]}' to {folder_name}")
            else:
                failed_moves.append({"email_id": email_id, "error": res.safe_message})
    
    save_cached_emails()
    return {
        "status": "SUCCESS" if not failed_moves else "PARTIAL_SUCCESS",
        "cleaned_count": len(cleaned_ids),
        "cleaned_ids": cleaned_ids,
        "failed_count": len(failed_moves),
        "failed_moves": failed_moves,
        "message": f"Cleaned {len(cleaned_ids)} noise emails to '{folder_name}'."
    }

@app.post("/api/emails/{email_id}/trash", dependencies=[Depends(require_local_auth)])
def trash_single_email(email_id: str):
    if email_id not in CACHED_EMAILS:
        raise HTTPException(status_code=404, detail="Email not found")
    
    email_msg = CACHED_EMAILS[email_id]
    res = provider_manager.delete_message(email_msg.id)
    if res.success:
        email_msg.status = "TRASHED"
        save_cached_emails()
        return {"status": "SUCCESS", "message": "Email moved to trash."}
    raise HTTPException(status_code=500, detail=res.safe_message)

# --- Analytics & Observability Endpoints ---

@app.get("/api/analytics/kpis")
def get_analytics_kpis():
    return get_kpis_summary()

@app.get("/api/analytics/funnel")
def get_analytics_funnel():
    return get_funnel_metrics()

@app.get("/api/analytics/compensation")
def get_analytics_compensation():
    return get_compensation_benchmarks()

@app.get("/api/analytics/resumes-roi")
def get_analytics_resumes_roi():
    return get_resume_roi_leaderboard()

@app.get("/api/analytics/events")
def get_analytics_events(limit: int = 50):
    return get_recent_audit_events(limit=limit)

@app.get("/api/analytics/export")
def get_analytics_export():
    return export_analytics_data()

@app.get("/api/stats")
def get_dashboard_stats():
    total = len(CACHED_EMAILS)
    noise_count = sum(1 for e in CACHED_EMAILS.values() if e.classification and e.classification.is_noise)
    cleaned_count = sum(1 for e in CACHED_EMAILS.values() if e.status == "TRASHED")
    resume_req_count = sum(1 for e in CACHED_EMAILS.values() if e.classification and e.classification.is_resume_request)
    replied_count = sum(1 for e in CACHED_EMAILS.values() if e.status == "REPLIED")
    
    time_saved_minutes = (noise_count * 2.5) + (resume_req_count * 10)
    
    return {
        "total_emails_analyzed": total,
        "noise_detected": noise_count,
        "noise_cleaned": cleaned_count,
        "resume_requests": resume_req_count,
        "replies_sent": replied_count,
        "time_saved_minutes": round(time_saved_minutes),
        "inbox_cleanliness_score": round((1.0 - (noise_count - cleaned_count) / max(total, 1)) * 100)
    }

# --- Daemon Endpoints ---
@app.get("/api/daemon/status")
def get_daemon_status():
    from backend.daemon import STATE_FILE, PROCESSED_LOG_FILE
    state = {}
    if STATE_FILE.is_file():
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception:
            pass
    return {
        "status": state.get("status", "IDLE"),
        "last_heartbeat": state.get("last_heartbeat"),
        "last_summary": state.get("last_summary", {})
    }

@app.post("/api/daemon/run-now", dependencies=[Depends(require_local_auth)])
def trigger_daemon_run(dry_run: bool = False):
    from backend.daemon import run_daemon_cycle
    summary = run_daemon_cycle(dry_run=dry_run)
    return {
        "status": "SUCCESS",
        "summary": summary
    }

# --- Opportunity Radar & Outlook Add-in Endpoints ---

from backend.radar.triage_service import classify_email_radar, calculate_opportunity_fit_score, extract_recruiter_details
from backend.radar.scribe_service import generate_executive_reply, generate_executive_reply_structured
from backend.calendar_broker.availability_service import calculate_optimal_booking_windows
from backend.calendar_broker.models import FreeBusyRequest

@app.post("/api/radar/triage", dependencies=[Depends(require_local_auth)])
def radar_triage_endpoint(payload: Dict[str, Any]):
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    sender_name = payload.get("sender_name", "")
    sender_email = payload.get("sender_email", "")

    msg = EmailMessage(
        id="addin-temp",
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        body_text=body
    )
    
    classification = classify_email_radar(msg)
    recruiter = classification.recruiter_details or extract_recruiter_details(msg)
    fit_analysis = calculate_opportunity_fit_score(
        role_title=recruiter.role_title or subject,
        body_text=body,
        required_skills=recruiter.required_skills
    )
    
    suggested_resume = "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
    suggested_lens = "Advisor"
    if classification.resume_match:
        if classification.resume_match.selected_resume:
            suggested_resume = classification.resume_match.selected_resume
        if classification.resume_match.matching_lens:
            suggested_lens = classification.resume_match.matching_lens

    return {
        "status": "SUCCESS",
        "category": classification.category.value,
        "fit_score": fit_analysis["fit_score"],
        "verdict": fit_analysis["fit_tier"] + " FIT",
        "is_recruiter": classification.is_resume_request,
        "role": recruiter.role_title,
        "company": recruiter.company_name,
        "salary": recruiter.salary_range or "Senior / Executive Target",
        "key_points": fit_analysis["alignment_reasons"] or recruiter.required_skills[:3],
        "suggested_lens": suggested_lens,
        "suggested_resume": suggested_resume,
        "confidence": classification.confidence
    }

@app.post("/api/radar/draft", dependencies=[Depends(require_local_auth)])
def radar_draft_endpoint(payload: Dict[str, Any]):
    from datetime import date, timedelta
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    sender_name = payload.get("sender_name", "")
    sender_email = payload.get("sender_email", "")
    lens = payload.get("lens", "Advisor")
    tone = payload.get("tone", "Professional & Warm")
    include_availability = payload.get("include_availability", True)
    selected_resume = payload.get("selected_resume", "")

    user_profile = get_user_profile()
    if selected_resume:
        user_profile.active_resume_file = selected_resume

    msg = EmailMessage(
        id="addin-draft-temp",
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        body_text=body
    )
    msg.classification = classify_email_radar(msg)

    req_params = ReplyDraftRequest(
        tone=tone,
        selected_resume=selected_resume or user_profile.active_resume_file,
        custom_instructions=payload.get("custom_instructions", "")
    )

    scribe_res = generate_executive_reply_structured(msg, user_profile, req_params)
    draft = scribe_res.draft_reply
    claim_bindings = scribe_res.claim_bindings
    draft_id = scribe_res.draft_id
    grounding_status = scribe_res.grounding_status
    is_grounded = scribe_res.is_grounded

    if include_availability:
        start_d = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        end_d = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        avail_req = FreeBusyRequest(
            start_date=start_d,
            end_date=end_d,
            timezone=payload.get("timezone", "America/Chicago")
        )
        avail_res = calculate_optimal_booking_windows([], avail_req)
        
        if "available for a brief" not in draft and "• " not in draft:
            slot_bullets = "\n".join([f"• {opt.formatted_display}" for opt in avail_res.available_windows[:3]])
            insertion = f"\n\nHere are a few times I am available for a brief introductory conversation next week:\n{slot_bullets}\n"
            
            if "Best regards," in draft:
                parts = draft.split("Best regards,")
                draft = parts[0].rstrip() + insertion + "\nBest regards," + parts[1]
            elif "Sincerely," in draft:
                parts = draft.split("Sincerely,")
                draft = parts[0].rstrip() + insertion + "\nSincerely," + parts[1]
            else:
                draft = draft + insertion

    return {
        "status": "SUCCESS",
        "draft_id": draft_id,
        "draft_reply": draft,
        "claim_bindings": claim_bindings,
        "grounding_status": grounding_status,
        "is_grounded": is_grounded,
        "selected_resume": selected_resume or user_profile.active_resume_file,
        "lens": lens,
        "tone": tone
    }

@app.post("/api/calendar/availability", dependencies=[Depends(require_local_auth)])
def calendar_availability_endpoint(payload: Optional[Dict[str, Any]] = None):
    from datetime import date, timedelta
    p = payload or {}
    days = p.get("days_ahead", 7)
    tz_str = p.get("timezone", "America/Chicago")
    duration = p.get("duration_minutes", 30)

    start_d = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    end_d = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")

    req = FreeBusyRequest(
        start_date=start_d,
        end_date=end_d,
        meeting_duration_minutes=duration,
        timezone=tz_str
    )

    busy_slots = []
    res = calculate_optimal_booking_windows(busy_slots, req)

    return {
        "status": "SUCCESS",
        "timezone": res.timezone,
        "formatted_summary": res.formatted_summary,
        "slots": [opt.model_dump() for opt in res.available_windows]
    }

from backend.radar.risk_evaluator import evaluate_second_opinion_risk

@app.post("/api/radar/risk-check", dependencies=[Depends(require_local_auth)])
def radar_risk_check_endpoint(payload: Dict[str, Any]):
    """
    Evaluates risk and second-opinion posture for proposed draft replies and operations.
    Radar Add-in Second-Opinion Risk Check with strict provenance verification.
    If cached draft has diverged or claim bindings are missing/invalid, prior
    authority is safely invalidated. If invalidation persistence fails, the
    endpoint stops immediately and fails closed without invoking risk evaluation.

    SECURITY CONTRACT:
    - execution-context type: backend.safety_policy.ExecutionContext (or string)
    - API source: caller-supplied (untrusted descriptive metadata)
    - authority to permit SEND: none (direct mail transmission is forbidden across all contexts)
    - SEND risk result regardless of supplied context: HIGH_RISK / BLOCKED
    """
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    sender_name = payload.get("sender_name", "")
    sender_email = payload.get("sender_email", "")
    draft_reply = payload.get("draft_reply", "")
    proposed_action = payload.get("proposed_action", "DRAFT")
    execution_context = payload.get("execution_context")
    draft_id = payload.get("draft_id")
    claim_bindings = payload.get("claim_bindings")
    provenance_claims = payload.get("provenance_claims")

    email_id = payload.get("email_id")
    if email_id and email_id in CACHED_EMAILS:
        with _EMAIL_STATE_LOCK:
            cached_msg = CACHED_EMAILS[email_id]
            req_text_hash = compute_sha256(draft_reply) if draft_reply else None
            submitted_canonical = canonicalize_binding_manifest(claim_bindings)
            cached_canonical = canonicalize_binding_manifest(cached_msg.claim_bindings)
            if (
                not draft_id or
                not cached_msg.draft_id or
                draft_id != cached_msg.draft_id or
                not req_text_hash or
                not cached_msg.draft_text_hash or
                req_text_hash != cached_msg.draft_text_hash or
                submitted_canonical != cached_canonical
            ):
                if cached_msg.draft_id:
                    inv_status, inv_err = safely_invalidate_draft_authority(
                        cached_msg.draft_id,
                        email_msg=cached_msg,
                        reason="Draft divergence during radar risk check"
                    )
                    if inv_status in ("INVALIDATION_PERSISTENCE_FAILURE", "PROVENANCE_STORE_UNAVAILABLE"):
                        save_cached_emails()
                        return JSONResponse(
                            status_code=500,
                            content={
                                "status": inv_status,
                                "error_code": inv_status,
                                "is_grounded": False,
                                "risk_is_current": False,
                                "requires_human_review": True,
                                "email_id": email_id,
                                "detail": (
                                    "Durable invalidation failed during radar risk check; "
                                    f"{'affected draft authority was quarantined' if inv_status == 'INVALIDATION_PERSISTENCE_FAILURE' else 'provenance store was disabled'}. "
                                    "No authoritative risk result was produced; human review is required."
                                ),
                                "error": inv_err
                            }
                        )
                cached_msg.draft_id = None
                cached_msg.claim_bindings = []
                cached_msg.draft_text_hash = None
                cached_msg.is_grounded = False
                cached_msg.grounding_status = GroundingStatus.VALIDATION_FAILED.value if draft_id else GroundingStatus.UNVERIFIED.value
                cached_msg.risk_result = None
                cached_msg.risk_draft_id = None
                cached_msg.risk_draft_text_hash = None
                cached_msg.risk_is_current = False
                cached_msg.draft_version += 1
                save_cached_emails()
                draft_id = None
                claim_bindings = None

    msg = EmailMessage(
        id=email_id or "addin-risk-temp",
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        body_text=body,
        draft_reply=draft_reply
    )
    user_profile = get_user_profile()
    res = evaluate_second_opinion_risk(
        email=msg,
        draft_reply=draft_reply,
        proposed_action=proposed_action,
        execution_context=execution_context,
        user_profile=user_profile,
        draft_id=draft_id,
        claim_bindings=claim_bindings,
        provenance_claims=provenance_claims
    )
    return res.model_dump()

# --- Static UI Mount & Secure Same-Origin Template Delivery ---

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
ADDIN_DIR = FRONTEND_DIR / "add-in"

@app.api_route("/", methods=["GET", "HEAD"])
def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        token = get_local_session_token()
        injection = f'<script>window.__AURA_SESSION_TOKEN__ = "{token}";</script>'
        content = content.replace("<head>", f"<head>\n    {injection}", 1)
        return HTMLResponse(content)
    return JSONResponse({"message": "Aura Mail AI v1.1 API Running."})

@app.get("/add-in/taskpane.html")
def serve_addin_taskpane():
    taskpane_file = ADDIN_DIR / "taskpane.html"
    if taskpane_file.exists():
        content = taskpane_file.read_text(encoding="utf-8")
        token = get_local_session_token()
        injection = f'<script>window.__AURA_SESSION_TOKEN__ = "{token}";</script>'
        content = content.replace("<head>", f"<head>\n    {injection}", 1)
        headers = {
            "Content-Security-Policy": "frame-ancestors 'self' https://outlook.office.com https://outlook.office365.com https://*.office.com https://*.office365.com https://*.live.com;"
        }
        return HTMLResponse(content, headers=headers)
    return JSONResponse({"error": "Taskpane file not found"}, status_code=404)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

if ADDIN_DIR.exists():
    app.mount("/add-in", StaticFiles(directory=str(ADDIN_DIR), html=True), name="addin")

if __name__ == "__main__":
    import uvicorn
    cert_file, key_file = require_ssl_context_paths()
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        ssl_certfile=str(cert_file),
        ssl_keyfile=str(key_file)
    )

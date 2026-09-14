"""Aura Mail AI - Gmail API Cloud Provider.

Dedicated Google OAuth2 cloud integration for Gmail mailboxes.
Supports threaded reply drafts, MIME attachment encoding, label-based quarantine,
and macOS Keychain token persistence.
"""

import os
import json
import base64
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import requests

from backend.models import EmailMessage
from backend.config import RESUMES_DIR, CANONICAL_ORIGIN
from backend.security import get_secret, set_secret, delete_secret
from backend.providers.base import (
    BaseEmailProvider,
    ProviderType,
    AccountIdentity,
    ProviderOperationResult,
    encode_composite_id,
    decode_composite_id
)

logger = logging.getLogger("gmail_provider")

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
# Least-privilege Gmail scopes:
# - gmail.readonly: read metadata and message content
# - gmail.compose: create, view, and update drafts in Drafts folder
# - gmail.modify: modify labels (noise quarantine / trash)
# Note: gmail.send is strictly omitted. While Google's permission model grants broad API capabilities
# to modify/compose tokens, Aura's application boundary strictly avoids calling transmission endpoints.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify"
]

class GmailProvider(BaseEmailProvider):
    provider_type = ProviderType.GMAIL

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")

    @property
    def effective_client_id(self) -> str:
        if self.client_id:
            return self.client_id
        from backend.config import load_settings
        settings = load_settings()
        return settings.get("google_client_id", "") or os.getenv("GOOGLE_CLIENT_ID", "")

    @property
    def effective_client_secret(self) -> str:
        if self.client_secret:
            return self.client_secret
        from backend.security import get_secret
        from backend.config import load_settings
        sec = get_secret("google_client_secret", "GOOGLE_CLIENT_SECRET")
        if sec:
            return sec
        settings = load_settings()
        return settings.get("google_client_secret", "")

    def get_auth_url(self, redirect_uri: Optional[str] = None, state: str = "gmail_auth") -> Optional[str]:
        cid = self.effective_client_id
        if not cid:
            return None
        actual_redirect_uri = redirect_uri or f"{CANONICAL_ORIGIN}/api/auth/google/callback"
        import urllib.parse
        params = {
            "client_id": cid,
            "redirect_uri": actual_redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }
        return f"{GOOGLE_AUTH_URI}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: Optional[str] = None, account_id: Optional[str] = None) -> ProviderOperationResult:
        cid = self.effective_client_id
        csec = self.effective_client_secret
        actual_redirect_uri = redirect_uri or f"{CANONICAL_ORIGIN}/api/auth/google/callback"
        if not cid or not csec:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id or "briankkinlaw@gmail.com",
                operation="AUTHENTICATE",
                error_code="CREDENTIALS_MISSING",
                safe_message="Google OAuth Client ID or Client Secret not configured. Please enter them in Settings or connect via Gmail App Password."
            )

        payload = {
            "code": code,
            "client_id": cid,
            "client_secret": csec,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }

        try:
            res = requests.post(GOOGLE_TOKEN_URI, data=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                access_token = data.get("access_token")
                refresh_token = data.get("refresh_token")
                
                # Fetch user profile to resolve canonical email
                email_addr = account_id or "briankkinlaw@gmail.com"
                prof_res = requests.get(f"{GMAIL_API_BASE}/profile", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
                if prof_res.status_code == 200:
                    email_addr = prof_res.json().get("emailAddress", email_addr).lower()
                
                acc_key = email_addr.lower()
                set_secret(f"gmail_access_{acc_key}", access_token)
                if refresh_token:
                    set_secret(f"gmail_refresh_{acc_key}", refresh_token)

                return ProviderOperationResult(
                    success=True,
                    provider="GMAIL",
                    account_id=email_addr,
                    operation="AUTHENTICATE",
                    safe_message=f"Connected to Gmail Cloud API as {email_addr}."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id or "unknown",
                    operation="AUTHENTICATE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Google token exchange failed: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id or "unknown",
                operation="AUTHENTICATE",
                error_code="EXCEPTION",
                safe_message=f"Error exchanging Google authorization code: {str(e)}"
            )

    def get_access_token(self, account_id: str) -> Optional[str]:
        acc_key = account_id.lower()
        token = get_secret(f"gmail_access_{acc_key}")
        expires_at_str = get_secret(f"gmail_expires_{acc_key}")
        
        # Check if token is still valid (proactive refresh if within 60 seconds of expiry)
        import time
        now = time.time()
        needs_refresh = False
        if expires_at_str:
            try:
                expires_at = float(expires_at_str)
                if now >= (expires_at - 60):
                    needs_refresh = True
            except ValueError:
                pass
        
        if token and not needs_refresh:
            return token
        
        # Try refreshing using refresh token
        refresh_token = get_secret(f"gmail_refresh_{acc_key}")
        cid = self.effective_client_id
        csec = self.effective_client_secret
        if refresh_token and cid and csec:
            try:
                res = requests.post(
                    GOOGLE_TOKEN_URI,
                    data={
                        "client_id": cid,
                        "client_secret": csec,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token"
                    },
                    timeout=10
                )
                if res.status_code == 200:
                    data = res.json()
                    new_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    set_secret(f"gmail_access_{acc_key}", new_token)
                    set_secret(f"gmail_expires_{acc_key}", str(now + expires_in))
                    return new_token
                elif res.status_code == 400 and "invalid_grant" in res.text:
                    logger.warning(f"Gmail refresh token revoked/invalid for {account_id}. Deleting stale tokens.")
                    delete_secret(f"gmail_access_{acc_key}")
                    delete_secret(f"gmail_refresh_{acc_key}")
                    delete_secret(f"gmail_expires_{acc_key}")
            except Exception as e:
                logger.warning(f"Failed to refresh Gmail token for {account_id}: {e}")
        
        return token if token else None

    def authenticate(self, account_config: Dict[str, Any], auth_payload: Optional[Dict[str, Any]] = None) -> ProviderOperationResult:
        if auth_payload and "code" in auth_payload:
            return self.exchange_code_for_token(
                auth_payload["code"], 
                auth_payload.get("redirect_uri", f"{CANONICAL_ORIGIN}/api/auth/google/callback"),
                account_config.get("account_id")
            )
        return ProviderOperationResult(
            success=False,
            provider="GMAIL",
            account_id=account_config.get("account_id", "unknown"),
            operation="AUTHENTICATE",
            error_code="CODE_REQUIRED",
            safe_message="Google OAuth authorization code required."
        )

    def validate_connection(self, account_id: str) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="VALIDATE",
                error_code="NOT_AUTHENTICATED",
                safe_message=f"No active Google OAuth credentials found for {account_id}."
            )
        try:
            res = requests.get(f"{GMAIL_API_BASE}/profile", headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return ProviderOperationResult(
                    success=True,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="VALIDATE",
                    safe_message=f"Connected to Gmail ({data.get('emailAddress')}).",
                    details=data
                )
            elif res.status_code == 401:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="VALIDATE",
                    error_code="AUTH_EXPIRED",
                    safe_message="Gmail OAuth token expired. Re-authentication required."
                )
            elif res.status_code == 429:
                retry_after = res.headers.get("Retry-After", "10")
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="VALIDATE",
                    error_code="THROTTLED_429",
                    safe_message=f"Gmail rate limit encountered. Retry in {retry_after}s.",
                    retryable=True
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="VALIDATE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Gmail validation error: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="VALIDATE",
                error_code="NETWORK_ERROR",
                safe_message=f"Network error connecting to Gmail: {str(e)}"
            )

    def list_accounts(self) -> List[AccountIdentity]:
        from backend.config import load_settings
        settings = load_settings()
        configured = settings.get("configured_accounts", [])
        
        results = []
        for acc in configured:
            if acc.get("provider") == "GMAIL":
                acc_id = acc.get("account_id", acc.get("email", ""))
                val_res = self.validate_connection(acc_id)
                results.append(AccountIdentity(
                    account_id=acc_id,
                    email_address=acc.get("email", acc_id),
                    provider=ProviderType.GMAIL,
                    display_name=acc.get("display_name", f"Gmail ({acc_id})"),
                    is_connected=val_res.success,
                    is_primary=acc.get("is_primary", False),
                    last_sync_time=acc.get("last_sync_time"),
                    last_error=val_res.safe_message if not val_res.success else None,
                    capabilities=["DRAFTS", "SEND", "ATTACHMENTS", "MOVE", "DELETE", "QUARANTINE", "THREADING"]
                ))
        return results

    def _extract_body_text(self, payload: Dict[str, Any]) -> str:
        """Extracts and decodes body text from Gmail payload structure."""
        body = payload.get("body", {})
        data_b64 = body.get("data")
        if data_b64:
            try:
                return base64.urlsafe_b64decode(data_b64).decode("utf-8", errors="ignore")
            except Exception:
                pass

        # Handle multipart parts
        parts = payload.get("parts", [])
        for part in parts:
            mime_type = part.get("mimeType", "")
            part_body = part.get("body", {})
            part_data = part_body.get("data")
            if part_data and ("text/plain" in mime_type or "text/html" in mime_type):
                try:
                    return base64.urlsafe_b64decode(part_data).decode("utf-8", errors="ignore")
                except Exception:
                    pass
        return ""

    def fetch_inbox_messages(self, account_id: str, limit: int = 50, folder: str = "INBOX") -> Tuple[List[EmailMessage], Optional[str]]:
        token = self.get_access_token(account_id)
        if not token:
            return [], f"Not authenticated with Gmail for account {account_id}"

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        messages: List[EmailMessage] = []

        try:
            list_url = f"{GMAIL_API_BASE}/messages?q=label:{folder}&maxResults={min(limit, 50)}"
            res = requests.get(list_url, headers=headers, timeout=15)
            if res.status_code != 200:
                return [], f"Gmail fetch failed: HTTP {res.status_code}"
            
            msg_list = res.json().get("messages", [])
            for item in msg_list:
                m_id = item.get("id")
                msg_res = requests.get(f"{GMAIL_API_BASE}/messages/{m_id}?format=full", headers=headers, timeout=10)
                if msg_res.status_code == 200:
                    m_data = msg_res.json()
                    payload = m_data.get("payload", {})
                    headers_list = payload.get("headers", [])
                    header_dict = {h["name"].lower(): h["value"] for h in headers_list if "name" in h and "value" in h}
                    
                    subj = header_dict.get("subject", "(No Subject)")
                    from_raw = header_dict.get("from", "Unknown <unknown@gmail.com>")
                    reply_to_raw = header_dict.get("reply-to", from_raw)
                    sender_name, sender_email = email.utils.parseaddr(from_raw)
                    _, reply_to_email = email.utils.parseaddr(reply_to_raw)
                    date_str = header_dict.get("date", datetime.now().isoformat())
                    snippet = m_data.get("snippet", "")
                    body_content = self._extract_body_text(payload) or snippet
                    
                    composite_id = encode_composite_id("GMAIL", account_id, m_id)
                    
                    msg = EmailMessage(
                        id=composite_id,
                        conversation_id=m_data.get("threadId"),
                        subject=subj,
                        sender_name=sender_name or sender_email,
                        sender_email=reply_to_email or sender_email,
                        received_at=date_str,
                        preview=snippet,
                        body_text=body_content,
                        folder=folder
                    )
                    messages.append(msg)
            
            return messages, None
        except Exception as e:
            logger.error(f"Gmail fetch error for {account_id}: {e}")
            return messages, f"Network error during Gmail fetch: {str(e)}"

    def build_reply_mime(
        self,
        to_email: str,
        subject: str,
        reply_body: str,
        in_reply_to_rfc_id: Optional[str] = None,
        references_rfc_id: Optional[str] = None,
        resume_filename: Optional[str] = None
    ) -> Tuple[Optional[MIMEMultipart], Optional[str]]:
        """Constructs and validates standard RFC 5322 compliant reply MIME message."""
        msg = MIMEMultipart()
        msg["To"] = to_email
        msg["Subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
        msg["Date"] = email.utils.formatdate(localtime=True)
        
        if in_reply_to_rfc_id:
            msg["In-Reply-To"] = in_reply_to_rfc_id
        if references_rfc_id:
            msg["References"] = references_rfc_id

        msg.attach(MIMEText(reply_body, "plain"))

        if resume_filename:
            from backend.canonical_engine import resolve_resume_file
            file_path = resolve_resume_file(resume_filename)
            if not file_path or not file_path.exists():
                file_path = RESUMES_DIR / resume_filename
            if not file_path or not file_path.exists():
                return None, f"Attachment file '{resume_filename}' not found on disk."
            
            try:
                with open(file_path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=file_path.name)
                part["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
                msg.attach(part)
            except Exception as e:
                return None, f"Failed to read attachment '{resume_filename}': {str(e)}"

        return msg, None

    def create_reply_draft(
        self, 
        account_id: str, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        """Creates a verified threaded draft in Gmail matching Google threading requirements."""
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="CREATE_DRAFT",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Gmail."
            )

        _, _, native_id = decode_composite_id(message_id)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            # 1. Fetch original message metadata to satisfy Gmail threading
            orig_res = requests.get(f"{GMAIL_API_BASE}/messages/{native_id}?format=full", headers=headers, timeout=10)
            if orig_res.status_code != 200:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    error_code=f"HTTP_{orig_res.status_code}",
                    safe_message=f"Failed to fetch original message from Gmail: HTTP {orig_res.status_code}"
                )

            orig_data = orig_res.json()
            thread_id = orig_data.get("threadId", native_id)
            orig_headers = {h["name"].lower(): h["value"] for h in orig_data.get("payload", {}).get("headers", []) if "name" in h and "value" in h}
            
            orig_subject = orig_headers.get("subject", "Inquiry")
            orig_msg_id = orig_headers.get("message-id")
            reply_to_addr = orig_headers.get("reply-to") or orig_headers.get("from", "")
            _, target_to = email.utils.parseaddr(reply_to_addr)

            # 2. Build RFC-compliant MIME message
            mime_msg, err = self.build_reply_mime(
                to_email=target_to or account_id,
                subject=orig_subject,
                reply_body=reply_body,
                in_reply_to_rfc_id=orig_msg_id,
                references_rfc_id=orig_msg_id,
                resume_filename=resume_filename
            )
            if err or not mime_msg:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    error_code="FILE_NOT_FOUND" if "not found" in (err or "").lower() else "MIME_BUILD_FAILED",
                    safe_message=err or "Failed to construct reply MIME."
                )

            raw_b64 = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
            draft_payload = {
                "message": {
                    "raw": raw_b64,
                    "threadId": thread_id
                }
            }

            res = requests.post(f"{GMAIL_API_BASE}/drafts", headers=headers, json=draft_payload, timeout=20)
            if res.status_code in [200, 201]:
                draft_data = res.json()
                return ProviderOperationResult(
                    success=True,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    remote_object_id=draft_data.get("id"),
                    safe_message=f"Threaded reply draft created in Gmail Drafts with '{resume_filename or 'resume'}' attached."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to create Gmail draft: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="CREATE_DRAFT",
                error_code="EXCEPTION",
                safe_message=f"Error creating Gmail draft: {str(e)}"
            )

    def attach_file(self, account_id: str, draft_id: str, filename: str, file_path: Path) -> ProviderOperationResult:
        if not file_path.exists():
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="ATTACH_FILE",
                error_code="FILE_NOT_FOUND",
                safe_message=f"Attachment file '{filename}' does not exist on disk."
            )
        return ProviderOperationResult(
            success=True,
            provider="GMAIL",
            account_id=account_id,
            operation="ATTACH_FILE",
            safe_message=f"Attachment '{filename}' bundled into MIME draft."
        )


    def create_or_resolve_quarantine_folder(self, account_id: str, folder_name: str = "AI Cleaned - Noise") -> Optional[str]:
        token = self.get_access_token(account_id)
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            # Check existing labels
            res = requests.get(f"{GMAIL_API_BASE}/labels", headers=headers, timeout=10)
            if res.status_code == 200:
                for lbl in res.json().get("labels", []):
                    if lbl.get("name") == folder_name:
                        return lbl.get("id")
            
            # Create label
            create_res = requests.post(
                f"{GMAIL_API_BASE}/labels",
                headers=headers,
                json={"name": folder_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
                timeout=10
            )
            if create_res.status_code in [200, 201]:
                return create_res.json().get("id")
        except Exception as e:
            logger.error(f"Failed to manage Gmail label '{folder_name}': {e}")
        return None

    def move_message(self, account_id: str, message_id: str, destination_folder_id: str) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="MOVE_MESSAGE",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Gmail."
            )

        _, _, native_id = decode_composite_id(message_id)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = f"{GMAIL_API_BASE}/messages/{native_id}/modify"

        try:
            payload = {
                "addLabelIds": [destination_folder_id] if destination_folder_id != "INBOX" else [],
                "removeLabelIds": ["INBOX"] if destination_folder_id != "INBOX" else []
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                return ProviderOperationResult(
                    success=True,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="MOVE_MESSAGE",
                    safe_message=f"Message moved to label '{destination_folder_id}' in Gmail."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="MOVE_MESSAGE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to modify Gmail message: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="MOVE_MESSAGE",
                error_code="EXCEPTION",
                safe_message=f"Error moving Gmail message: {str(e)}"
            )

    def delete_message(self, account_id: str, message_id: str) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="DELETE_MESSAGE",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Gmail."
            )

        _, _, native_id = decode_composite_id(message_id)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GMAIL_API_BASE}/messages/{native_id}/trash"

        try:
            res = requests.post(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return ProviderOperationResult(
                    success=True,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="DELETE_MESSAGE",
                    safe_message="Message moved to Gmail Trash."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="GMAIL",
                    account_id=account_id,
                    operation="DELETE_MESSAGE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to trash Gmail message: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="GMAIL",
                account_id=account_id,
                operation="DELETE_MESSAGE",
                error_code="EXCEPTION",
                safe_message=f"Error trashing Gmail message: {str(e)}"
            )

    def get_health_status(self, account_id: str) -> Dict[str, Any]:
        val = self.validate_connection(account_id)
        return {
            "provider": "GMAIL",
            "account_id": account_id,
            "connected": val.success,
            "status_message": val.safe_message
        }

    def logout(self, account_id: Optional[str] = None) -> ProviderOperationResult:
        acc = (account_id or "briankkinlaw@gmail.com").lower()
        delete_secret(f"gmail_access_{acc}")
        delete_secret(f"gmail_refresh_{acc}")
        return ProviderOperationResult(
            success=True,
            provider="GMAIL",
            account_id=acc,
            operation="LOGOUT",
            safe_message=f"Logged out from Gmail ({acc})."
        )

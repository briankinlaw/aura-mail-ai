"""Aura Mail AI - Microsoft Graph Multi-Account Cloud Provider (MSAL).

Cloud-first integration for Outlook.com, Microsoft 365, and New Outlook for Mac.
Uses MSAL PublicClientApplication, macOS Keychain token storage, alias detection,
threaded reply drafts, separate attachment validation, and pagination.
"""

import os
import json
import base64
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import msal
import requests

from backend.models import EmailMessage
from backend.config import GRAPH_SCOPES, RESUMES_DIR
from backend.security import get_secret, set_secret, delete_secret, mask_secret
from backend.providers.base import (
    BaseEmailProvider,
    ProviderType,
    AccountIdentity,
    ProviderOperationResult,
    encode_composite_id,
    decode_composite_id
)

logger = logging.getLogger("graph_provider")

GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"
AUTHORITY_BASE = "https://login.microsoftonline.com"

class MicrosoftGraphProvider(BaseEmailProvider):
    provider_type = ProviderType.MICROSOFT_GRAPH

    def __init__(self, client_id: Optional[str] = None, tenant_id: str = "common"):
        self.client_id = client_id or os.getenv("AZURE_CLIENT_ID", "")
        self.tenant_id = tenant_id or os.getenv("AZURE_TENANT_ID", "common")
        self.authority = f"{AUTHORITY_BASE}/{self.tenant_id}"
        self.scopes = GRAPH_SCOPES

    def _get_token_cache(self, account_id: str) -> msal.SerializableTokenCache:
        """Loads serialized token cache for the specific account from Keychain."""
        cache = msal.SerializableTokenCache()
        cache_data = get_secret(f"msal_cache_{account_id.lower()}")
        if cache_data:
            try:
                cache.deserialize(cache_data)
            except Exception as e:
                logger.warning(f"Failed to deserialize MSAL cache for {account_id}: {e}")
        return cache

    def _save_token_cache(self, account_id: str, cache: msal.SerializableTokenCache):
        """Saves serialized token cache for the specific account into Keychain."""
        if cache.has_state_changed:
            cache_data = cache.serialize()
            set_secret(f"msal_cache_{account_id.lower()}", cache_data)

    def _build_msal_app(self, account_id: Optional[str] = None) -> Optional[msal.PublicClientApplication]:
        """Creates an MSAL PublicClientApplication for the registered client ID."""
        if not self.client_id:
            logger.warning("Microsoft Graph client_id not configured. Register an Azure Public Client Application.")
            return None
        
        cache = self._get_token_cache(account_id) if account_id else None
        return msal.PublicClientApplication(
            client_id=self.client_id,
            authority=self.authority,
            token_cache=cache
        )

    def get_auth_url(self, redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback", login_hint: Optional[str] = None, state: Optional[str] = None) -> Optional[str]:
        """Generates OAuth2 authorization URL via MSAL with forced account login when login_hint is provided."""
        app = self._build_msal_app(login_hint)
        if not app:
            return None
        kwargs = {
            "scopes": self.scopes,
            "redirect_uri": redirect_uri,
            "prompt": "login" if login_hint else "select_account"
        }
        if login_hint:
            kwargs["login_hint"] = login_hint
        if state:
            kwargs["state"] = state
        elif login_hint:
            kwargs["state"] = login_hint
        return app.get_authorization_request_url(**kwargs)

    def initiate_device_code_flow(self) -> Dict[str, Any]:
        """Initiates MSAL Device Code Flow for headless or cross-platform authentication."""
        app = self._build_msal_app()
        if not app:
            raise Exception("Microsoft Graph Azure Client ID not configured. Please set in Settings.")
        
        flow = app.initiate_device_flow(scopes=self.scopes)
        if "user_code" not in flow:
            err = flow.get("error_description", flow.get("error", "Failed to initiate device flow"))
            
            # If app requires /consumers endpoint, automatically switch and retry
            if "AADSTS9002346" in str(err) or "/consumers" in str(err).lower():
                self.tenant_id = "consumers"
                self.authority = f"{AUTHORITY_BASE}/consumers"
                app = self._build_msal_app()
                flow = app.initiate_device_flow(scopes=self.scopes)
                if "user_code" in flow:
                    return flow
                err = flow.get("error_description", flow.get("error", "Failed to initiate device flow"))
            
            if "AADSTS70002" in str(err) or "marked as 'mobile'" in str(err).lower():
                raise Exception(
                    "Azure Setting Required: In Azure Portal -> App registrations -> Authentication -> "
                    "Advanced settings, toggle 'Allow public client flows' (Enable mobile and desktop flows) to 'Yes' and Save."
                )
            
            raise Exception(f"MSAL Device Flow error: {err}")
        return flow

    def acquire_token_by_device_flow(self, flow: Dict[str, Any], account_id: Optional[str] = None) -> ProviderOperationResult:
        """Polls/completes token acquisition via MSAL Device Flow."""
        target_account = (account_id or "primary").lower()
        app = self._build_msal_app(target_account)
        if not app:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=target_account,
                operation="AUTHENTICATE",
                error_code="CLIENT_ID_MISSING",
                safe_message="Azure Client ID is missing. Configure in settings."
            )
        
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            mailbox = self._fetch_user_profile(result["access_token"], default_email=account_id)
            resolved_account_id = (account_id or mailbox.get("email") or target_account).lower()
            
            # Save cache and token under the requested account ID
            self._save_token_cache(resolved_account_id, app.token_cache)
            set_secret(f"graph_token_{resolved_account_id}", result["access_token"])
            
            # If Microsoft returned a distinct primary alias, also populate it
            profile_email = mailbox.get("email", "").lower()
            if profile_email and profile_email != resolved_account_id:
                self._save_token_cache(profile_email, app.token_cache)
                set_secret(f"graph_token_{profile_email}", result["access_token"])
            
            return ProviderOperationResult(
                success=True,
                provider="MICROSOFT_GRAPH",
                account_id=resolved_account_id,
                operation="AUTHENTICATE",
                safe_message=f"Connected to Microsoft Graph as {mailbox.get('display_name', resolved_account_id)} ({resolved_account_id}).",
                details=mailbox
            )
        
        err = result.get("error_description", result.get("error", "Authentication pending"))
        return ProviderOperationResult(
            success=False,
            provider="MICROSOFT_GRAPH",
            account_id=account_id or "unknown",
            operation="AUTHENTICATE",
            error_code=result.get("error", "AUTH_FAILED"),
            safe_message=f"Authentication failed: {err}",
            retryable=result.get("error") in ["authorization_pending", "slow_down"]
        )

    def exchange_code_for_token(self, code: str, redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback", account_id: Optional[str] = None) -> ProviderOperationResult:
        """Exchanges authorization code for tokens using MSAL."""
        target_account = (account_id or "primary").lower()
        app = self._build_msal_app(target_account)
        if not app:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=target_account,
                operation="AUTHENTICATE",
                error_code="CLIENT_ID_MISSING",
                safe_message="Azure Client ID is missing. Configure in settings."
            )

        result = app.acquire_token_by_authorization_code(
            code=code,
            scopes=self.scopes,
            redirect_uri=redirect_uri
        )

        if "access_token" in result:
            mailbox = self._fetch_user_profile(result["access_token"], default_email=account_id)
            resolved_account_id = (account_id or mailbox.get("email") or target_account).lower()
            
            self._save_token_cache(resolved_account_id, app.token_cache)
            set_secret(f"graph_token_{resolved_account_id}", result["access_token"])

            profile_email = mailbox.get("email", "").lower()
            if profile_email and profile_email != resolved_account_id:
                self._save_token_cache(profile_email, app.token_cache)
                set_secret(f"graph_token_{profile_email}", result["access_token"])

            return ProviderOperationResult(
                success=True,
                provider="MICROSOFT_GRAPH",
                account_id=resolved_account_id,
                operation="AUTHENTICATE",
                safe_message=f"Authenticated with Microsoft Graph as {mailbox.get('display_name', resolved_account_id)} ({resolved_account_id}).",
                details=mailbox
            )
        
        err = result.get("error_description", result.get("error", "Token exchange failed"))
        return ProviderOperationResult(
            success=False,
            provider="MICROSOFT_GRAPH",
            account_id=account_id or "unknown",
            operation="AUTHENTICATE",
            error_code=result.get("error", "TOKEN_EXCHANGE_FAILED"),
            safe_message=f"Failed to authenticate with Microsoft Graph: {err}"
        )

    def get_access_token(self, account_id: str) -> Optional[str]:
        """Acquires a valid access token silently from MSAL cache, refreshing automatically."""
        cache = self._get_token_cache(account_id)
        app = msal.PublicClientApplication(
            client_id=self.client_id or "default",
            authority=self.authority,
            token_cache=cache
        )
        
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(self.scopes, account=accounts[0])
            if result and "access_token" in result:
                self._save_token_cache(account_id, cache)
                return result["access_token"]
        
        # Fallback to direct token if stored
        return get_secret(f"graph_token_{account_id.lower()}")

    def _fetch_user_profile(self, access_token: str, default_email: Optional[str] = None) -> Dict[str, Any]:
        """Queries Microsoft Graph /me to resolve primary address, aliases, and display name."""
        headers = {"Authorization": f"Bearer {access_token}"}
        fallback = (default_email or "").lower()
        profile = {"email": fallback, "display_name": fallback or "Microsoft User", "aliases": []}
        try:
            res = requests.get(f"{GRAPH_API_ENDPOINT}/me", headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                primary_email = data.get("mail") or data.get("userPrincipalName") or ""
                if primary_email and "@" in primary_email:
                    profile["email"] = primary_email.lower()
                profile["display_name"] = data.get("displayName") or profile["email"]
                
                # Check for proxy addresses / aliases if available
                proxy_addresses = data.get("otherMails", [])
                if proxy_addresses:
                    profile["aliases"] = [a.lower() for a in proxy_addresses]
        except Exception as e:
            logger.warning(f"Error fetching Graph /me profile: {e}")
        return profile

    def authenticate(self, account_config: Dict[str, Any], auth_payload: Optional[Dict[str, Any]] = None) -> ProviderOperationResult:
        if auth_payload and "code" in auth_payload:
            return self.exchange_code_for_token(
                auth_payload["code"], 
                auth_payload.get("redirect_uri", "http://127.0.0.1:8000/api/auth/callback"),
                account_id=account_config.get("account_id")
            )
        return ProviderOperationResult(
            success=False,
            provider="MICROSOFT_GRAPH",
            account_id=account_config.get("account_id", "unknown"),
            operation="AUTHENTICATE",
            error_code="CODE_REQUIRED",
            safe_message="Authorization code or device flow completion required."
        )

    def validate_connection(self, account_id: str) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="VALIDATE",
                error_code="NOT_AUTHENTICATED",
                safe_message=f"No active cloud credentials found for {account_id}. Please sign in."
            )
        
        headers = {"Authorization": f"Bearer {token}"}
        try:
            res = requests.get(f"{GRAPH_API_ENDPOINT}/me", headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return ProviderOperationResult(
                    success=True,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="VALIDATE",
                    safe_message=f"Connected to Microsoft Cloud ({data.get('displayName')}).",
                    details=data
                )
            elif res.status_code == 401:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="VALIDATE",
                    error_code="AUTH_EXPIRED",
                    safe_message="Microsoft Cloud session expired. Please re-authenticate."
                )
            elif res.status_code == 429:
                retry_after = res.headers.get("Retry-After", "10")
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="VALIDATE",
                    error_code="THROTTLED_429",
                    safe_message=f"Microsoft Graph rate limit encountered. Retry in {retry_after}s.",
                    retryable=True
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="VALIDATE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Microsoft Graph validation error: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="VALIDATE",
                error_code="NETWORK_ERROR",
                safe_message=f"Network error connecting to Microsoft Graph: {str(e)}",
                retryable=True
            )

    def list_accounts(self) -> List[AccountIdentity]:
        from backend.config import load_settings
        settings = load_settings()
        configured = settings.get("configured_accounts", [])
        
        results = []
        for acc in configured:
            if acc.get("provider") == "MICROSOFT_GRAPH":
                acc_id = acc.get("account_id", acc.get("email", ""))
                val_res = self.validate_connection(acc_id)
                results.append(AccountIdentity(
                    account_id=acc_id,
                    email_address=acc.get("email", acc_id),
                    provider=ProviderType.MICROSOFT_GRAPH,
                    display_name=acc.get("display_name", f"Outlook ({acc_id})"),
                    is_connected=val_res.success,
                    is_primary=acc.get("is_primary", False),
                    is_alias=acc.get("is_alias", False),
                    alias_of=acc.get("alias_of"),
                    last_sync_time=acc.get("last_sync_time"),
                    last_error=val_res.safe_message if not val_res.success else None,
                    capabilities=["DRAFTS", "SEND", "ATTACHMENTS", "MOVE", "DELETE", "QUARANTINE", "THREADING"]
                ))
        return results

    def fetch_inbox_messages(self, account_id: str, limit: int = 50, folder: str = "Inbox") -> Tuple[List[EmailMessage], Optional[str]]:
        """Fetches messages with Graph pagination and precise field selection."""
        token = self.get_access_token(account_id)
        if not token:
            return [], f"Not authenticated with Microsoft Graph for account {account_id}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        params = {
            "$top": min(limit, 50),
            "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,body,isRead,hasAttachments,parentFolderId",
            "$orderby": "receivedDateTime desc"
        }

        url = f"{GRAPH_API_ENDPOINT}/me/mailFolders/{folder}/messages"
        messages: List[EmailMessage] = []

        try:
            while url and len(messages) < limit:
                res = requests.get(url, headers=headers, params=params if "?" not in url else None, timeout=15)
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get("value", []):
                        sender_obj = item.get("from", {}).get("emailAddress", {})
                        native_id = item.get("id")
                        composite_id = encode_composite_id("MICROSOFT_GRAPH", account_id, native_id)
                        
                        msg = EmailMessage(
                            id=composite_id,
                            conversation_id=item.get("conversationId"),
                            subject=item.get("subject") or "(No Subject)",
                            sender_name=sender_obj.get("name") or "Sender",
                            sender_email=sender_obj.get("address") or "unknown@domain.com",
                            received_at=item.get("receivedDateTime") or datetime.now().isoformat(),
                            preview=item.get("bodyPreview", ""),
                            body_text=item.get("body", {}).get("content", item.get("bodyPreview", "")),
                            body_html=item.get("body", {}).get("content") if item.get("body", {}).get("contentType") == "html" else None,
                            is_read=item.get("isRead", False),
                            has_attachments=item.get("hasAttachments", False),
                            folder=folder
                        )
                        messages.append(msg)
                        if len(messages) >= limit:
                            break
                    
                    # Next page link
                    url = data.get("@odata.nextLink")
                    params = {} # Clear params for nextLink URL
                elif res.status_code == 429:
                    retry_after = res.headers.get("Retry-After", "5")
                    return messages, f"Microsoft Graph rate limit reached (HTTP 429). Retry in {retry_after}s."
                else:
                    return messages, f"Graph fetch failed: HTTP {res.status_code} - {res.text[:120]}"
            
            return messages, None
        except Exception as e:
            logger.error(f"Graph fetch error for {account_id}: {e}")
            return messages, f"Network error during Graph fetch: {str(e)}"

    def create_reply_draft(
        self, 
        account_id: str, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        """Creates threaded reply draft in Graph and validates attachment upload separately."""
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="CREATE_DRAFT",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Microsoft Graph."
            )

        _, _, native_id = decode_composite_id(message_id)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        reply_url = f"{GRAPH_API_ENDPOINT}/me/messages/{native_id}/createReply"

        try:
            # 1. Create threaded reply draft
            res = requests.post(reply_url, headers=headers, json={"comment": reply_body}, timeout=15)
            if res.status_code not in [200, 201]:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to create draft in Microsoft Graph: HTTP {res.status_code}"
                )

            draft_data = res.json()
            draft_id = draft_data.get("id")
            if not draft_id:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    error_code="NO_DRAFT_ID",
                    safe_message="Microsoft Graph did not return a valid draft ID."
                )

            # 2. Attach resume file if requested
            if resume_filename:
                from backend.canonical_engine import resolve_resume_file
                file_path = resolve_resume_file(resume_filename)
                if not file_path or not file_path.exists():
                    file_path = RESUMES_DIR / resume_filename

                if file_path and file_path.exists():
                    attach_res = self.attach_file(account_id, draft_id, resume_filename, file_path)
                    if not attach_res.success:
                        # Return partial failure: Draft created, but attachment failed
                        return ProviderOperationResult(
                            success=False,
                            provider="MICROSOFT_GRAPH",
                            account_id=account_id,
                            operation="CREATE_DRAFT",
                            remote_object_id=draft_id,
                            error_code="ATTACHMENT_FAILED",
                            safe_message=f"Draft reply created in New Outlook Drafts, but attaching '{resume_filename}' failed: {attach_res.safe_message}",
                            details={"draft_id": draft_id}
                        )

            return ProviderOperationResult(
                success=True,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="CREATE_DRAFT",
                remote_object_id=draft_id,
                safe_message=f"Threaded draft successfully created in New Outlook Drafts with '{resume_filename or 'canonical resume'}' attached."
            )

        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="CREATE_DRAFT",
                error_code="EXCEPTION",
                safe_message=f"Error creating draft in Microsoft Graph: {str(e)}"
            )

    def attach_file(
        self, 
        account_id: str, 
        draft_id: str, 
        filename: str, 
        file_path: Path
    ) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="ATTACH_FILE",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Microsoft Graph."
            )

        if not file_path.exists():
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="ATTACH_FILE",
                error_code="FILE_NOT_FOUND",
                safe_message=f"Attachment file '{filename}' does not exist on disk."
            )

        try:
            with open(file_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            url = f"{GRAPH_API_ENDPOINT}/me/messages/{draft_id}/attachments"
            content_type = "application/pdf" if filename.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

            payload = {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": file_path.name,
                "contentType": content_type,
                "contentBytes": encoded
            }

            res = requests.post(url, headers=headers, json=payload, timeout=20)
            if res.status_code in [200, 201]:
                return ProviderOperationResult(
                    success=True,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="ATTACH_FILE",
                    remote_object_id=res.json().get("id"),
                    safe_message=f"File '{filename}' successfully attached to Microsoft Graph draft."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="ATTACH_FILE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to attach '{filename}' to draft: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="ATTACH_FILE",
                error_code="EXCEPTION",
                safe_message=f"Error attaching file to Microsoft Graph draft: {str(e)}"
            )

    def send_reply(
        self, 
        account_id: str, 
        message_id: str, 
        to_email: str, 
        subject: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="SEND_REPLY",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Microsoft Graph."
            )

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        message_payload = {
            "message": {
                "subject": subject if subject.startswith("Re:") else f"Re: {subject}",
                "body": {"contentType": "Text", "content": reply_body},
                "toRecipients": [{"emailAddress": {"address": to_email}}],
                "attachments": []
            },
            "saveToSentItems": "true"
        }

        if resume_filename:
            from backend.canonical_engine import resolve_resume_file
            file_path = resolve_resume_file(resume_filename)
            if not file_path or not file_path.exists():
                file_path = RESUMES_DIR / resume_filename
            if file_path and file_path.exists():
                with open(file_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                content_type = "application/pdf" if file_path.name.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                message_payload["message"]["attachments"].append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": file_path.name,
                    "contentType": content_type,
                    "contentBytes": encoded
                })

        try:
            res = requests.post(f"{GRAPH_API_ENDPOINT}/me/sendMail", headers=headers, json=message_payload, timeout=25)
            if res.status_code in [200, 202]:
                return ProviderOperationResult(
                    success=True,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="SEND_REPLY",
                    safe_message=f"Reply sent to {to_email} via Microsoft Graph with resume attached."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="SEND_REPLY",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to send email via Microsoft Graph: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="SEND_REPLY",
                error_code="EXCEPTION",
                safe_message=f"Error sending email via Microsoft Graph: {str(e)}"
            )

    def create_or_resolve_quarantine_folder(self, account_id: str, folder_name: str = "AI Cleaned - Noise") -> Optional[str]:
        token = self.get_access_token(account_id)
        if not token:
            return None

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            # Check existing folders
            res = requests.get(f"{GRAPH_API_ENDPOINT}/me/mailFolders", headers=headers, timeout=10)
            if res.status_code == 200:
                for f in res.json().get("value", []):
                    if f.get("displayName") == folder_name:
                        return f.get("id")

            # Create if not found
            create_res = requests.post(
                f"{GRAPH_API_ENDPOINT}/me/mailFolders",
                headers=headers,
                json={"displayName": folder_name},
                timeout=10
            )
            if create_res.status_code in [200, 201]:
                return create_res.json().get("id")
        except Exception as e:
            logger.error(f"Error managing safe folder in Graph: {e}")
        return None

    def move_message(self, account_id: str, message_id: str, destination_folder_id: str) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="MOVE_MESSAGE",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Microsoft Graph."
            )

        _, _, native_id = decode_composite_id(message_id)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = f"{GRAPH_API_ENDPOINT}/me/messages/{native_id}/move"

        try:
            res = requests.post(url, headers=headers, json={"destinationId": destination_folder_id}, timeout=10)
            if res.status_code in [200, 201]:
                return ProviderOperationResult(
                    success=True,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="MOVE_MESSAGE",
                    safe_message="Message moved to destination folder in Microsoft Cloud."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="MOVE_MESSAGE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to move message: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="MOVE_MESSAGE",
                error_code="EXCEPTION",
                safe_message=f"Error moving message in Microsoft Graph: {str(e)}"
            )

    def delete_message(self, account_id: str, message_id: str) -> ProviderOperationResult:
        token = self.get_access_token(account_id)
        if not token:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="DELETE_MESSAGE",
                error_code="NOT_AUTHENTICATED",
                safe_message="Not authenticated with Microsoft Graph."
            )

        _, _, native_id = decode_composite_id(message_id)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH_API_ENDPOINT}/me/messages/{native_id}"

        try:
            res = requests.delete(url, headers=headers, timeout=10)
            if res.status_code in [200, 204]:
                return ProviderOperationResult(
                    success=True,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="DELETE_MESSAGE",
                    safe_message="Message deleted from Microsoft Cloud."
                )
            else:
                return ProviderOperationResult(
                    success=False,
                    provider="MICROSOFT_GRAPH",
                    account_id=account_id,
                    operation="DELETE_MESSAGE",
                    error_code=f"HTTP_{res.status_code}",
                    safe_message=f"Failed to delete message: HTTP {res.status_code}"
                )
        except Exception as e:
            return ProviderOperationResult(
                success=False,
                provider="MICROSOFT_GRAPH",
                account_id=account_id,
                operation="DELETE_MESSAGE",
                error_code="EXCEPTION",
                safe_message=f"Error deleting message in Microsoft Graph: {str(e)}"
            )

    def get_health_status(self, account_id: str) -> Dict[str, Any]:
        val = self.validate_connection(account_id)
        return {
            "provider": "MICROSOFT_GRAPH",
            "account_id": account_id,
            "connected": val.success,
            "status_message": val.safe_message,
            "client_configured": bool(self.client_id)
        }

    def logout(self, account_id: Optional[str] = None) -> ProviderOperationResult:
        acc = account_id or "primary"
        delete_secret(f"msal_cache_{acc.lower()}")
        delete_secret(f"graph_token_{acc.lower()}")
        return ProviderOperationResult(
            success=True,
            provider="MICROSOFT_GRAPH",
            account_id=acc,
            operation="LOGOUT",
            safe_message=f"Logged out from Microsoft Graph ({acc})."
        )

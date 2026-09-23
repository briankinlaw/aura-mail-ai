"""Aura Mail AI - Unified Cloud Provider Manager.

Dispatches email operations across Microsoft Graph, Gmail, IMAP, and Demo providers.
Handles alias resolution, multi-mailbox aggregation, positive identity routing,
quarantine folder resolution & caching, and strict fail-closed error handling.
"""

import os
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime

from backend.models import (
    EmailMessage,
    QuarantineMessageResult,
    QuarantineBatchResult
)
from backend.config import load_settings, save_settings, get_secret
from backend.providers.base import (
    BaseEmailProvider,
    ProviderType,
    AccountIdentity,
    ProviderOperationResult,
    decode_composite_id
)
from backend.providers.graph import MicrosoftGraphProvider
from backend.providers.gmail import GmailProvider
from backend.providers.imap import ImapProvider
from backend.providers.demo import DemoProvider
from backend import safety_policy
from backend.safety_policy import MailSafetyMode

logger = logging.getLogger("provider_manager")

AURA_DEFAULT_CAPABILITIES = [
    "DRAFTS",
    "ATTACHMENTS",
    "MOVE",
    "DELETE",
    "QUARANTINE"
]

def sanitize_aura_capabilities(capabilities: Optional[List[Any]]) -> List[str]:
    """Sanitizes capability metadata at the Aura application boundary.

    Guarantees that Aura never advertises 'SEND' as an application capability,
    even if stale persisted configuration or legacy settings contain it.
    Preserves all legitimate non-SEND capabilities (DRAFTS, ATTACHMENTS, MOVE, DELETE, QUARANTINE, THREADING).
    """
    if not capabilities:
        return list(AURA_DEFAULT_CAPABILITIES)

    sanitized: List[str] = []
    for item in capabilities:
        if not isinstance(item, str):
            continue
        clean_item = item.strip().upper()
        if clean_item and clean_item != "SEND" and clean_item not in sanitized:
            sanitized.append(clean_item)

    return sanitized if sanitized else list(AURA_DEFAULT_CAPABILITIES)

class ProviderManager:
    def __init__(self):
        self._quarantine_folder_cache: Dict[Tuple[str, str], str] = {}
        self._init_providers()

    def _init_providers(self):
        settings = load_settings()
        azure_client_id = settings.get("azure_client_id", "")
        azure_tenant_id = settings.get("azure_tenant_id", "common")
        google_client_id = settings.get("google_client_id", "") or os.getenv("GOOGLE_CLIENT_ID", "")
        from backend.security import get_secret
        google_client_secret = get_secret("google_client_secret", "GOOGLE_CLIENT_SECRET") or settings.get("google_client_secret", "")

        self.graph_provider = MicrosoftGraphProvider(client_id=azure_client_id, tenant_id=azure_tenant_id)
        self.gmail_provider = GmailProvider(client_id=google_client_id, client_secret=google_client_secret)
        self.imap_provider = ImapProvider()
        self.demo_provider = DemoProvider()

    def reload_config(self):
        self._init_providers()
        self._quarantine_folder_cache.clear()

    def is_demo_mode(self) -> bool:
        settings = load_settings()
        return bool(settings.get("demo_mode", False))

    def get_provider_by_type(self, provider_type: str) -> Optional[BaseEmailProvider]:
        """Returns the requested provider instance, failing closed if unknown or unauthorized."""
        p_upper = (provider_type or "").strip().upper()
        if p_upper == "MICROSOFT_GRAPH":
            return self.graph_provider
        elif p_upper == "GMAIL":
            return self.gmail_provider
        elif p_upper == "IMAP":
            return self.imap_provider
        elif p_upper == "DEMO":
            if self.is_demo_mode():
                return self.demo_provider
            logger.warning("Attempted to access DemoProvider while demo_mode is False. Denying access.")
            return None
        return None

    def get_configured_accounts(self) -> List[Dict[str, Any]]:
        settings = load_settings()
        return settings.get("configured_accounts", [])

    def get_account_config(self, account_id: str) -> Optional[Dict[str, Any]]:
        settings = load_settings()
        clean_id = (account_id or "").strip().lower()
        for acc in settings.get("configured_accounts", []):
            acc_id = acc.get("account_id", "").lower()
            acc_email = acc.get("email", "").lower()
            if acc_id == clean_id or acc_email == clean_id:
                return acc
        return None

    def get_provider_for_account(self, account_id: str) -> Tuple[Optional[BaseEmailProvider], Optional[Dict[str, Any]]]:
        """Positively resolves provider and config for a given account.
        
        Strictly fails closed without silently guessing providers based on email domains.
        """
        if self.is_demo_mode():
            return self.demo_provider, {"account_id": "demo@auramail.local", "provider": "DEMO"}

        cfg = self.get_account_config(account_id)
        if not cfg:
            logger.warning(f"Account '{account_id}' is not configured in settings. Rejecting routing.")
            return None, None

        p_type = cfg.get("provider", "")
        provider = self.get_provider_by_type(p_type)
        return provider, cfg

    def get_provider_for_message(self, message_id: str) -> Tuple[Optional[BaseEmailProvider], str, str, Optional[str]]:
        """Resolves provider, account_id, native_id, and error_code from structured composite ID.
        
        Returns: (provider, account_id, native_id, error_code)
        """
        if self.is_demo_mode():
            return self.demo_provider, "demo@auramail.local", message_id, None

        provider_name, account_id, native_id = decode_composite_id(message_id)
        
        if provider_name in ["UNKNOWN", "MAC_DESKTOP"] or not provider_name:
            return None, account_id, native_id, "UNROUTABLE_MESSAGE"

        if provider_name == "DEMO":
            if not self.is_demo_mode():
                return None, account_id, native_id, "DEMO_ISOLATED"
            return self.demo_provider, "demo@auramail.local", native_id, None

        provider = self.get_provider_by_type(provider_name)
        if not provider:
            return None, account_id, native_id, "UNKNOWN_PROVIDER"

        cfg = self.get_account_config(account_id)
        if not cfg:
            return None, account_id, native_id, "ACCOUNT_NOT_FOUND"

        return provider, account_id, native_id, None

    def list_all_accounts(self, validate_remote: bool = False) -> List[AccountIdentity]:
        """Returns all configured accounts with validated connection statuses and capabilities."""
        if self.is_demo_mode():
            return self.demo_provider.list_accounts()

        settings = load_settings()
        configured = settings.get("configured_accounts", [])
        
        all_identities: List[AccountIdentity] = []
        for acc in configured:
            acc_id = acc.get("account_id", acc.get("email", ""))
            p_type = acc.get("provider", "MICROSOFT_GRAPH")
            provider = self.get_provider_by_type(p_type)
            
            if not provider:
                continue

            # Check if this is an alias
            is_alias = acc.get("is_alias", False)
            alias_of = acc.get("alias_of")
            
            if is_alias and alias_of:
                is_connected = False
                if validate_remote:
                    parent_res = provider.validate_connection(alias_of)
                    is_connected = parent_res.success
                elif p_type == "MICROSOFT_GRAPH":
                    is_connected = bool(self.graph_provider.get_access_token(alias_of))
                elif p_type == "GMAIL":
                    is_connected = bool(self.gmail_provider.get_access_token(alias_of))
                elif p_type == "IMAP":
                    is_connected = bool(get_secret(f"imap_password_{alias_of}"))

                all_identities.append(AccountIdentity(
                    account_id=acc_id,
                    email_address=acc.get("email", acc_id),
                    provider=ProviderType(p_type),
                    display_name=acc.get("display_name", f"{acc_id} (Alias)"),
                    is_connected=is_connected,
                    is_primary=False,
                    is_alias=True,
                    alias_of=alias_of,
                    last_sync_time=acc.get("last_sync_time"),
                    capabilities=sanitize_aura_capabilities(acc.get("capabilities"))
                ))
            else:
                is_connected = False
                last_error = acc.get("last_error")
                if validate_remote:
                    val_res = provider.validate_connection(acc_id)
                    is_connected = val_res.success
                    last_error = val_res.safe_message if not val_res.success else None
                elif p_type == "MICROSOFT_GRAPH":
                    is_connected = bool(self.graph_provider.get_access_token(acc_id)) and not bool(last_error)
                elif p_type == "GMAIL":
                    is_connected = bool(self.gmail_provider.get_access_token(acc_id)) and not bool(last_error)
                elif p_type == "IMAP":
                    is_connected = bool(get_secret(f"imap_password_{acc_id}")) and not bool(last_error)

                all_identities.append(AccountIdentity(
                    account_id=acc_id,
                    email_address=acc.get("email", acc_id),
                    provider=ProviderType(p_type),
                    display_name=acc.get("display_name", acc_id),
                    is_connected=is_connected,
                    is_primary=acc.get("is_primary", False),
                    is_alias=False,
                    last_sync_time=acc.get("last_sync_time"),
                    last_error=last_error,
                    capabilities=sanitize_aura_capabilities(acc.get("capabilities"))
                ))

        return all_identities

    def sync_unified_inbox(self, limit_per_account: int = 50, since_date: Optional[str] = None) -> Tuple[List[EmailMessage], Dict[str, Any]]:
        """Fetches and merges messages across all active mailboxes into a unified inbox."""
        if self.is_demo_mode():
            msgs, _ = self.demo_provider.fetch_inbox_messages("demo@auramail.local", limit=limit_per_account, since_date=since_date)
            return msgs, {
                "status": "SUCCESS",
                "demo_mode": True, 
                "accounts_synced": 1, 
                "synced_accounts": ["demo@auramail.local"],
                "accounts_failed": 0,
                "errors": [],
                "timestamp": datetime.now().isoformat()
            }

        settings = load_settings()
        user_profile = settings.get("user_profile", {})
        historical_accounts = set(a.lower() for a in user_profile.get("historical_email_accounts", []))
        
        configured = settings.get("configured_accounts", [])
        all_messages: List[EmailMessage] = []
        sync_stats = {
            "status": "SUCCESS",
            "accounts_synced": 0,
            "synced_accounts": [],
            "skipped_accounts": [],
            "accounts_failed": 0,
            "errors": [],
            "timestamp": datetime.now().isoformat()
        }

        fetched_mailboxes = set()

        for acc in configured:
            if not acc.get("enabled", True):
                continue
            
            acc_id = acc.get("account_id", acc.get("email", "")).lower()
            
            if acc_id in historical_accounts or any(h in acc_id for h in historical_accounts):
                sync_stats["skipped_accounts"].append({"account_id": acc_id, "reason": "historical"})
                continue
            
            if acc.get("is_alias") and acc.get("alias_of"):
                parent = acc.get("alias_of").lower()
                if parent in fetched_mailboxes:
                    sync_stats["skipped_accounts"].append({"account_id": acc_id, "reason": "alias", "alias_of": parent})
                    continue

            p_type = acc.get("provider", "MICROSOFT_GRAPH")
            provider = self.get_provider_by_type(p_type)
            if not provider:
                sync_stats["accounts_failed"] += 1
                sync_stats["errors"].append({"account_id": acc_id, "error": f"Unknown or unconfigured provider '{p_type}'"})
                continue

            try:
                msgs, err = provider.fetch_inbox_messages(acc_id, limit=limit_per_account, since_date=since_date)
                if err:
                    sync_stats["accounts_failed"] += 1
                    sync_stats["errors"].append({"account_id": acc_id, "error": err})
                    acc["last_error"] = err
                else:
                    all_messages.extend(msgs)
                    sync_stats["accounts_synced"] += 1
                    sync_stats["synced_accounts"].append(acc_id)
                    acc["last_sync_time"] = datetime.now().isoformat()
                    acc["last_error"] = None
                    fetched_mailboxes.add(acc_id)
            except Exception as ex:
                sync_stats["accounts_failed"] += 1
                sync_stats["errors"].append({"account_id": acc_id, "error": str(ex)})
                acc["last_error"] = str(ex)

        save_settings(settings)

        # Determine overall sync status truthfully
        if sync_stats["accounts_synced"] == 0 and sync_stats["accounts_failed"] > 0:
            sync_stats["status"] = "FAILED"
        elif sync_stats["accounts_failed"] > 0:
            sync_stats["status"] = "PARTIAL_SUCCESS"
        else:
            sync_stats["status"] = "SUCCESS"

        # Sort combined inbox by received_at descending
        all_messages.sort(key=lambda m: m.received_at, reverse=True)
        return all_messages, sync_stats

    def save_draft_reply(
        self, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None,
        account_id: Optional[str] = None
    ) -> ProviderOperationResult:
        provider, resolved_account_id, native_id, err_code = self.get_provider_for_message(message_id)
        if not provider:
            return ProviderOperationResult(
                success=False,
                provider="UNKNOWN",
                account_id=account_id or resolved_account_id or "unknown",
                operation="CREATE_DRAFT",
                error_code=err_code or "UNROUTABLE_MESSAGE",
                safe_message=f"Cannot create draft for unroutable message '{message_id}': {err_code or 'routing failed'}",
                retryable=False
            )

        if account_id and resolved_account_id:
            clean_acc = account_id.strip().lower()
            clean_res = resolved_account_id.strip().lower()
            if clean_acc not in ("primary", "default", clean_res):
                return ProviderOperationResult(
                    success=False,
                    provider=provider.provider_type.value if hasattr(provider, "provider_type") else "UNKNOWN",
                    account_id=account_id,
                    operation="CREATE_DRAFT",
                    error_code="ACCOUNT_MISMATCH",
                    safe_message=f"Account mismatch: requested '{account_id}' does not match message owner '{resolved_account_id}'.",
                    retryable=False
                )

        return provider.create_reply_draft(
            account_id=resolved_account_id,
            message_id=message_id,
            reply_body=reply_body,
            resume_filename=resume_filename
        )

    def send_reply(
        self, 
        message_id: str, 
        to_email: str, 
        subject: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None,
    ) -> ProviderOperationResult:
        """Centralized mail safety policy enforcement at ProviderManager boundary.

        FAIL-CLOSED INVARIANT:
        ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN.
        Aura prepares and stages drafts via save_draft_reply(); human sends via native mail client.
        """
        return ProviderOperationResult(
            success=False,
            provider="UNKNOWN",
            account_id="unknown",
            operation="SEND_REPLY",
            error_code="SEND_FORBIDDEN",
            safe_message=(
                "Mail Transmission Blocked: Aura direct mail transmission is permanently disabled. "
                "Outbound mail is prepared and staged in your Drafts folder for review and native client transmission."
            ),
            retryable=False,
            details={
                "safety_mode": "DRAFT_STAGING_ONLY",
                "reason": "Direct mail transmission forbidden from Aura execution boundary.",
            }
        )

    def move_message(self, message_id: str, destination_folder_id: str) -> ProviderOperationResult:
        provider, account_id, native_id, err_code = self.get_provider_for_message(message_id)
        if not provider:
            return ProviderOperationResult(
                success=False,
                provider="UNKNOWN",
                account_id=account_id or "unknown",
                operation="MOVE_MESSAGE",
                error_code=err_code or "UNROUTABLE_MESSAGE",
                safe_message=f"Cannot move unroutable message '{message_id}': {err_code or 'routing failed'}",
                retryable=False
            )
        return provider.move_message(
            account_id=account_id,
            message_id=message_id,
            destination_folder_id=destination_folder_id
        )

    def delete_message(self, message_id: str) -> ProviderOperationResult:
        provider, account_id, native_id, err_code = self.get_provider_for_message(message_id)
        if not provider:
            return ProviderOperationResult(
                success=False,
                provider="UNKNOWN",
                account_id=account_id or "unknown",
                operation="DELETE_MESSAGE",
                error_code=err_code or "UNROUTABLE_MESSAGE",
                safe_message=f"Cannot delete unroutable message '{message_id}': {err_code or 'routing failed'}",
                retryable=False
            )
        return provider.delete_message(
            account_id=account_id,
            message_id=message_id
        )

    def quarantine_message(self, message_id: str, folder_name: str = "AI Cleaned - Noise") -> ProviderOperationResult:
        """Resolves quarantine remote folder ID and moves noise message.
        
        Caches folder/label IDs per provider and account. Fails closed if remote resolution fails.
        """
        provider, account_id, native_id, err_code = self.get_provider_for_message(message_id)
        if not provider:
            return ProviderOperationResult(
                success=False,
                provider="UNKNOWN",
                account_id=account_id or "unknown",
                operation="QUARANTINE",
                error_code=err_code or "UNROUTABLE_MESSAGE",
                safe_message=f"Cannot quarantine unroutable message '{message_id}': {err_code or 'routing failed'}",
                retryable=False
            )

        # In demo mode, pass display name directly
        if self.is_demo_mode() or provider.provider_type == ProviderType.DEMO:
            return provider.move_message(account_id, message_id, folder_name)

        # Resolve remote folder / label ID
        cache_key = (provider.provider_type.value, account_id.lower())
        remote_folder_id = self._quarantine_folder_cache.get(cache_key)

        if not remote_folder_id:
            try:
                resolved_id = provider.create_or_resolve_quarantine_folder(account_id, folder_name)
                if resolved_id:
                    self._quarantine_folder_cache[cache_key] = resolved_id
                    remote_folder_id = resolved_id
                else:
                    return ProviderOperationResult(
                        success=False,
                        provider=provider.provider_type.value,
                        account_id=account_id,
                        operation="QUARANTINE",
                        error_code="QUARANTINE_RESOLUTION_FAILED",
                        safe_message=f"Could not create or resolve remote quarantine folder '{folder_name}' on mailbox '{account_id}'.",
                        retryable=False
                    )
            except Exception as e:
                return ProviderOperationResult(
                    success=False,
                    provider=provider.provider_type.value,
                    account_id=account_id,
                    operation="QUARANTINE",
                    error_code="EXCEPTION",
                    safe_message=f"Exception resolving quarantine folder on '{account_id}': {str(e)}",
                    retryable=False
                )

        return provider.move_message(
            account_id=account_id,
            message_id=message_id,
            destination_folder_id=remote_folder_id
        )

    def batch_quarantine_noise(self, emails_to_clean: List[EmailMessage], folder_name: str = "AI Cleaned - Noise") -> QuarantineBatchResult:
        """Executes cross-provider noise quarantine with accurate status reporting and per-message tracking."""
        if not emails_to_clean:
            return QuarantineBatchResult(
                status="SUCCESS",
                total_requested=0,
                cleaned_count=0,
                failed_count=0,
                cleaned_ids=[],
                results=[],
                message="No noise emails to clean."
            )

        cleaned_ids: List[str] = []
        results: List[QuarantineMessageResult] = []

        for email_msg in emails_to_clean:
            res = self.quarantine_message(email_msg.id, folder_name=folder_name)
            if res.success:
                cleaned_ids.append(email_msg.id)
                results.append(QuarantineMessageResult(
                    email_id=email_msg.id,
                    subject=email_msg.subject,
                    provider=res.provider,
                    account_id=res.account_id,
                    destination_folder_id=res.remote_object_id,
                    success=True,
                    message=res.safe_message
                ))
            else:
                results.append(QuarantineMessageResult(
                    email_id=email_msg.id,
                    subject=email_msg.subject,
                    provider=res.provider,
                    account_id=res.account_id,
                    success=False,
                    error_code=res.error_code,
                    message=res.safe_message
                ))

        total = len(emails_to_clean)
        cleaned_count = len(cleaned_ids)
        failed_count = total - cleaned_count

        if failed_count == 0 and cleaned_count > 0:
            status = "SUCCESS"
            msg = f"Successfully quarantined {cleaned_count} noise email(s) into '{folder_name}'."
        elif cleaned_count > 0 and failed_count > 0:
            status = "PARTIAL_SUCCESS"
            msg = f"Partial cleanup: {cleaned_count} quarantined, {failed_count} failed."
        else:
            status = "FAILED"
            msg = f"Quarantine failed for all {failed_count} noise email(s)."

        return QuarantineBatchResult(
            status=status,
            total_requested=total,
            cleaned_count=cleaned_count,
            failed_count=failed_count,
            cleaned_ids=cleaned_ids,
            results=results,
            message=msg
        )

provider_manager = ProviderManager()

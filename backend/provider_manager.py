"""Aura Mail AI - Unified Cloud Provider Manager.

Dispatches email operations across Microsoft Graph, Gmail, IMAP, and Demo providers.
Handles alias resolution, multi-mailbox aggregation, positive identity routing,
and strict non-destructive error handling.
"""

import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.models import EmailMessage
from backend.config import load_settings, save_settings
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

logger = logging.getLogger("provider_manager")

class ProviderManager:
    def __init__(self):
        self.settings = load_settings()
        self._init_providers()

    def _init_providers(self):
        settings = load_settings()
        azure_client_id = settings.get("azure_client_id", "")
        azure_tenant_id = settings.get("azure_tenant_id", "common")

        self.graph_provider = MicrosoftGraphProvider(client_id=azure_client_id, tenant_id=azure_tenant_id)
        self.gmail_provider = GmailProvider()
        self.imap_provider = ImapProvider()
        self.demo_provider = DemoProvider()

    def reload_config(self):
        self._init_providers()

    def is_demo_mode(self) -> bool:
        settings = load_settings()
        return bool(settings.get("demo_mode", False))

    def get_provider_by_type(self, provider_type: str) -> BaseEmailProvider:
        p_upper = provider_type.upper()
        if p_upper == "MICROSOFT_GRAPH":
            return self.graph_provider
        elif p_upper == "GMAIL":
            return self.gmail_provider
        elif p_upper == "IMAP":
            return self.imap_provider
        elif p_upper == "DEMO":
            return self.demo_provider
        return self.demo_provider

    def get_account_config(self, account_id: str) -> Optional[Dict[str, Any]]:
        settings = load_settings()
        for acc in settings.get("configured_accounts", []):
            if acc.get("account_id", "").lower() == account_id.lower() or acc.get("email", "").lower() == account_id.lower():
                return acc
        return None

    def get_provider_for_account(self, account_id: str) -> Tuple[BaseEmailProvider, Dict[str, Any]]:
        if self.is_demo_mode():
            return self.demo_provider, {"account_id": "demo@auramail.local", "provider": "DEMO"}

        cfg = self.get_account_config(account_id)
        if not cfg:
            # Fallback based on email domain
            if "@gmail.com" in account_id.lower():
                return self.gmail_provider, {"account_id": account_id, "provider": "GMAIL"}
            elif "@outlook.com" in account_id.lower() or "@hotmail.com" in account_id.lower():
                return self.graph_provider, {"account_id": account_id, "provider": "MICROSOFT_GRAPH"}
            else:
                return self.imap_provider, {"account_id": account_id, "provider": "IMAP"}

        p_type = cfg.get("provider", "MICROSOFT_GRAPH")
        return self.get_provider_by_type(p_type), cfg

    def get_provider_for_message(self, message_id: str) -> Tuple[BaseEmailProvider, str, str]:
        """Resolves provider, account_id, and native_id from structured composite ID."""
        if self.is_demo_mode():
            return self.demo_provider, "demo@auramail.local", message_id

        provider_name, account_id, native_id = decode_composite_id(message_id)
        provider = self.get_provider_by_type(provider_name)
        return provider, account_id, native_id

    def list_all_accounts(self) -> List[AccountIdentity]:
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
            
            # Check if this is an alias
            is_alias = acc.get("is_alias", False)
            alias_of = acc.get("alias_of")
            
            # If alias, mirror the parent's connection
            if is_alias and alias_of:
                parent_res = provider.validate_connection(alias_of)
                all_identities.append(AccountIdentity(
                    account_id=acc_id,
                    email_address=acc.get("email", acc_id),
                    provider=ProviderType(p_type),
                    display_name=acc.get("display_name", f"{acc_id} (Alias)"),
                    is_connected=parent_res.success,
                    is_primary=False,
                    is_alias=True,
                    alias_of=alias_of,
                    last_sync_time=acc.get("last_sync_time"),
                    capabilities=acc.get("capabilities", ["DRAFTS", "SEND", "ATTACHMENTS", "MOVE", "DELETE", "QUARANTINE"])
                ))
            else:
                val_res = provider.validate_connection(acc_id)
                all_identities.append(AccountIdentity(
                    account_id=acc_id,
                    email_address=acc.get("email", acc_id),
                    provider=ProviderType(p_type),
                    display_name=acc.get("display_name", acc_id),
                    is_connected=val_res.success,
                    is_primary=acc.get("is_primary", False),
                    is_alias=False,
                    last_sync_time=acc.get("last_sync_time"),
                    last_error=val_res.safe_message if not val_res.success else None,
                    capabilities=acc.get("capabilities", ["DRAFTS", "SEND", "ATTACHMENTS", "MOVE", "DELETE", "QUARANTINE"])
                ))

        return all_identities

    def sync_unified_inbox(self, limit_per_account: int = 50) -> Tuple[List[EmailMessage], Dict[str, Any]]:
        """Fetches and merges messages across all active mailboxes into a unified inbox."""
        if self.is_demo_mode():
            msgs, _ = self.demo_provider.fetch_inbox_messages("demo@auramail.local")
            return msgs, {"demo_mode": True, "accounts_synced": 1, "errors": []}

        settings = load_settings()
        user_profile = settings.get("user_profile", {})
        historical_accounts = set(a.lower() for a in user_profile.get("historical_email_accounts", []))
        
        configured = settings.get("configured_accounts", [])
        all_messages: List[EmailMessage] = []
        sync_stats = {
            "accounts_synced": 0,
            "accounts_failed": 0,
            "errors": [],
            "timestamp": datetime.now().isoformat()
        }

        # Track seen mailboxes to avoid duplicate fetching of aliases
        fetched_mailboxes = set()

        for acc in configured:
            if not acc.get("enabled", True):
                continue
            
            acc_id = acc.get("account_id", acc.get("email", "")).lower()
            
            # Skip historical accounts
            if acc_id in historical_accounts or any(h in acc_id for h in historical_accounts):
                continue
            
            # Skip aliases whose parent mailbox was already fetched
            if acc.get("is_alias") and acc.get("alias_of"):
                parent = acc.get("alias_of").lower()
                if parent in fetched_mailboxes:
                    continue

            p_type = acc.get("provider", "MICROSOFT_GRAPH")
            provider = self.get_provider_by_type(p_type)

            try:
                msgs, err = provider.fetch_inbox_messages(acc_id, limit=limit_per_account)
                if err:
                    sync_stats["accounts_failed"] += 1
                    sync_stats["errors"].append({"account_id": acc_id, "error": err})
                    acc["last_error"] = err
                else:
                    all_messages.extend(msgs)
                    sync_stats["accounts_synced"] += 1
                    acc["last_sync_time"] = datetime.now().isoformat()
                    acc["last_error"] = None
                    fetched_mailboxes.add(acc_id)
            except Exception as ex:
                sync_stats["accounts_failed"] += 1
                sync_stats["errors"].append({"account_id": acc_id, "error": str(ex)})
                acc["last_error"] = str(ex)

        save_settings(settings)

        # Sort combined inbox by received_at descending
        all_messages.sort(key=lambda m: m.received_at, reverse=True)
        return all_messages, sync_stats

    def save_draft_reply(
        self, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        provider, account_id, native_id = self.get_provider_for_message(message_id)
        return provider.create_reply_draft(
            account_id=account_id,
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
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        provider, account_id, native_id = self.get_provider_for_message(message_id)
        return provider.send_reply(
            account_id=account_id,
            message_id=message_id,
            to_email=to_email,
            subject=subject,
            reply_body=reply_body,
            resume_filename=resume_filename
        )

    def move_message(self, message_id: str, destination_folder_id: str) -> ProviderOperationResult:
        provider, account_id, native_id = self.get_provider_for_message(message_id)
        return provider.move_message(
            account_id=account_id,
            message_id=message_id,
            destination_folder_id=destination_folder_id
        )

    def delete_message(self, message_id: str) -> ProviderOperationResult:
        provider, account_id, native_id = self.get_provider_for_message(message_id)
        return provider.delete_message(
            account_id=account_id,
            message_id=message_id
        )

provider_manager = ProviderManager()

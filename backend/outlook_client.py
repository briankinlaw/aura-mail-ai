"""Aura Mail AI - Legacy Outlook Client Backward-Compatibility Adapter (v1.1).

Delegates operations to the new cloud-first ProviderManager while providing
backward-compatibility for legacy scripts and test signatures.
"""

import logging
from typing import List, Optional, Dict, Any, Union

from backend.models import EmailMessage
from backend.provider_manager import provider_manager
from backend.desktop_helper import is_outlook_desktop_running
from backend.safety_policy import SendAuthorizationTicket, ExecutionContext

logger = logging.getLogger("legacy_outlook_client")

class OutlookClientAdapter:
    """Adapter wrapping provider_manager with legacy outlook_client signatures."""

    def is_authenticated(self) -> bool:
        accounts = provider_manager.list_all_accounts()
        return any(a.is_connected for a in accounts)

    def get_auth_mode(self) -> str:
        if provider_manager.is_demo_mode():
            return "DEMO"
        accounts = provider_manager.list_all_accounts()
        connected = [a for a in accounts if a.is_connected]
        if connected:
            return f"CLOUD_{connected[0].provider.value}"
        return "DISCONNECTED"

    def is_mac_outlook_available(self) -> bool:
        return is_outlook_desktop_running()

    def get_auth_display_name(self) -> str:
        if provider_manager.is_demo_mode():
            return "Demo Mode (Offline Sandbox)"
        accounts = provider_manager.list_all_accounts()
        connected = [a for a in accounts if a.is_connected]
        if connected:
            return f"Connected ({len(connected)} Cloud Mailboxes)"
        return "Disconnected (Configure Accounts)"

    def fetch_inbox_emails(self, count: int = 50) -> List[EmailMessage]:
        messages, _ = provider_manager.sync_unified_inbox(limit_per_account=count)
        return messages

    def save_draft_reply(self, message_id: str, reply_body: str, resume_filename: Optional[str] = None) -> Dict[str, Any]:
        res = provider_manager.save_draft_reply(message_id, reply_body, resume_filename)
        return res.model_dump()

    def send_reply(
        self,
        to_email: str,
        subject: str,
        reply_body: str,
        resume_filename: Optional[str] = None,
        message_id: Optional[str] = None,
        authorization: Optional[Union[SendAuthorizationTicket, str]] = None,
    ) -> Dict[str, Any]:
        target_id = message_id or "primary"
        if not provider_manager.is_demo_mode() and target_id == "primary":
            return {
                "success": False,
                "provider": "UNKNOWN",
                "account_id": "unknown",
                "operation": "SEND_REPLY",
                "error_code": "UNROUTABLE_MESSAGE",
                "safe_message": "Direct send without a valid message or account ID is disallowed in live mode.",
                "retryable": False
            }
        res = provider_manager.send_reply(
            message_id=target_id,
            to_email=to_email,
            subject=subject,
            reply_body=reply_body,
            resume_filename=resume_filename,
            authorization=authorization,
        )
        return res.model_dump()

    def move_email_to_folder(self, message_id: str, destination_folder_id: str) -> bool:
        res = provider_manager.move_message(message_id, destination_folder_id)
        return res.success

    def delete_email(self, message_id: str) -> bool:
        res = provider_manager.delete_message(message_id)
        return res.success

    def logout(self):
        for acc in provider_manager.list_all_accounts():
            provider, _ = provider_manager.get_provider_for_account(acc.account_id)
            provider.logout(acc.account_id)

outlook_client = OutlookClientAdapter()

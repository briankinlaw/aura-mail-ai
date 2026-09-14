"""Aura Mail AI - Provider Neutral Base Architecture.

Defines the contract, structured models, and composite ID encoding
for all cloud email integrations (Microsoft Graph, Gmail API, IMAP, Demo).
"""

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field
import urllib.parse

from backend.models import EmailMessage
from backend.safety_policy import (
    evaluate_mail_action,
    MailAction,
    ExecutionContext,
    MailSafetyMode,
)

class ProviderType(str, Enum):
    MICROSOFT_GRAPH = "MICROSOFT_GRAPH"
    GMAIL = "GMAIL"
    IMAP = "IMAP"
    DEMO = "DEMO"

class AccountIdentity(BaseModel):
    account_id: str
    email_address: str
    provider: ProviderType
    display_name: str
    is_connected: bool = False
    is_primary: bool = False
    is_alias: bool = False
    alias_of: Optional[str] = None
    last_sync_time: Optional[str] = None
    last_error: Optional[str] = None
    capabilities: List[str] = Field(
        default_factory=lambda: ["DRAFTS", "SEND", "ATTACHMENTS", "MOVE", "DELETE", "QUARANTINE"]
    )
    mailbox_details: Optional[Dict[str, Any]] = None

class ProviderOperationResult(BaseModel):
    success: bool
    provider: str
    account_id: str
    operation: str
    remote_object_id: Optional[str] = None
    error_code: Optional[str] = None
    safe_message: str
    retryable: bool = False
    details: Optional[Dict[str, Any]] = None

def encode_composite_id(provider: str, account_id: str, native_id: str) -> str:
    """Encodes provider, account_id, and remote message ID into a single immutable composite ID."""
    clean_provider = provider.strip().upper()
    clean_account = urllib.parse.quote_plus(account_id.strip().lower())
    clean_native = urllib.parse.quote_plus(str(native_id).strip())
    return f"{clean_provider}::{clean_account}::{clean_native}"

def decode_composite_id(composite_id: str) -> Tuple[str, str, str]:
    """Decodes composite ID into (provider, account_id, native_id).
    
    Gracefully handles legacy string prefixes for backward compatibility.
    """
    if "::" in composite_id:
        parts = composite_id.split("::", 2)
        if len(parts) == 3:
            provider = parts[0].strip().upper()
            account_id = urllib.parse.unquote_plus(parts[1])
            native_id = urllib.parse.unquote_plus(parts[2])
            return provider, account_id, native_id
    
    # Backward compatibility with v1.0 IDs
    if composite_id.startswith("graph_"):
        return "MICROSOFT_GRAPH", "kinlawb@outlook.com", composite_id[6:]
    if composite_id.startswith("imap_"):
        return "IMAP", "kinlawb@outlook.com", composite_id[5:]
    if composite_id.startswith("mac_"):
        return "MAC_DESKTOP", "kinlawb@outlook.com", composite_id[4:]
    if composite_id.startswith("demo_") or composite_id.startswith("msg_rec_"):
        return "DEMO", "demo@auramail.local", composite_id
    
    return "UNKNOWN", "unknown@auramail.local", composite_id

class BaseEmailProvider(ABC):
    """Abstract contract for cloud email integrations."""

    provider_type: ProviderType

    @abstractmethod
    def authenticate(self, account_config: Dict[str, Any], auth_payload: Optional[Dict[str, Any]] = None) -> ProviderOperationResult:
        """Authenticates with the cloud provider and persists credentials in Keychain."""
        pass

    @abstractmethod
    def validate_connection(self, account_id: str) -> ProviderOperationResult:
        """Actively checks cloud connectivity and token validity."""
        pass

    @abstractmethod
    def list_accounts(self) -> List[AccountIdentity]:
        """Returns all configured accounts managed by this provider with connection status."""
        pass

    @abstractmethod
    def fetch_inbox_messages(self, account_id: str, limit: int = 50, folder: str = "Inbox") -> Tuple[List[EmailMessage], Optional[str]]:
        """Fetches live inbox messages from cloud mailbox.
        
        Returns (messages, error_message_if_any).
        NEVER silently substitutes sample data on failure.
        """
        pass

    @abstractmethod
    def create_reply_draft(
        self, 
        account_id: str, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        """Creates a threaded draft reply in the cloud mailbox Drafts folder.
        
        If an attachment is requested, validates attachment upload separately.
        """
        pass

    @abstractmethod
    def attach_file(
        self, 
        account_id: str, 
        draft_id: str, 
        filename: str, 
        file_path: Path
    ) -> ProviderOperationResult:
        """Uploads and attaches a file to an existing cloud draft."""
        pass

    def send_reply(
        self,
        account_id: str,
        message_id: str,
        to_email: str,
        subject: str,
        reply_body: str,
        resume_filename: Optional[str] = None,
        context: ExecutionContext = ExecutionContext.UNAUTHENTICATED_API,
        safety_mode: Optional[MailSafetyMode] = None,
    ) -> ProviderOperationResult:
        """Centralized mail safety policy enforcement at the provider transmission boundary.

        Guarantees that all concrete email providers fail closed unless transmission is
        independently authorized by an interactive human context and permitted by safety mode.
        """
        policy_eval = evaluate_mail_action(MailAction.SEND_REPLY, context=context, safety_mode=safety_mode)
        if not policy_eval.allowed:
            prov_name = self.provider_type.value if hasattr(self, "provider_type") and self.provider_type else "UNKNOWN"
            return ProviderOperationResult(
                success=False,
                provider=prov_name,
                account_id=account_id,
                operation="SEND_REPLY",
                error_code="SEND_FORBIDDEN",
                safe_message=f"Mail Transmission Blocked: {policy_eval.reason}",
                retryable=False,
                details={
                    "safety_mode": policy_eval.safety_mode.value,
                    "execution_context": context.value,
                    "reason": policy_eval.reason,
                }
            )

        return self._execute_send_reply(
            account_id=account_id,
            message_id=message_id,
            to_email=to_email,
            subject=subject,
            reply_body=reply_body,
            resume_filename=resume_filename,
        )

    @abstractmethod
    def _execute_send_reply(
        self,
        account_id: str,
        message_id: str,
        to_email: str,
        subject: str,
        reply_body: str,
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        """Sends an email reply through the cloud provider and archives it in Sent Items."""
        pass

    @abstractmethod
    def create_or_resolve_quarantine_folder(self, account_id: str, folder_name: str = "AI Cleaned - Noise") -> Optional[str]:
        """Resolves or creates the quarantine folder on the cloud mailbox."""
        pass

    @abstractmethod
    def move_message(self, account_id: str, message_id: str, destination_folder_id: str) -> ProviderOperationResult:
        """Moves a message to a destination folder on the cloud mailbox."""
        pass

    @abstractmethod
    def delete_message(self, account_id: str, message_id: str) -> ProviderOperationResult:
        """Moves a message to the Trash/Deleted Items folder on the cloud mailbox."""
        pass

    @abstractmethod
    def get_health_status(self, account_id: str) -> Dict[str, Any]:
        """Returns structured diagnostic health metrics for telemetry."""
        pass

    @abstractmethod
    def logout(self, account_id: Optional[str] = None) -> ProviderOperationResult:
        """Clears tokens and credentials from Keychain and provider session."""
        pass

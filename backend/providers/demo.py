"""Aura Mail AI - Explicit Demo Mode Provider.

Provides simulated offline email data strictly when Demo Mode is explicitly enabled.
Never used as a fallback for failed live sync.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from backend.models import EmailMessage, EmailCategory, ClassificationResult, RecruiterDetails, ResumeMatchResult
from backend.providers.base import (
    BaseEmailProvider,
    ProviderType,
    AccountIdentity,
    ProviderOperationResult,
    encode_composite_id
)

class DemoProvider(BaseEmailProvider):
    provider_type = ProviderType.DEMO

    def __init__(self):
        self.account_id = "demo@auramail.local"
        self._mock_messages: Dict[str, EmailMessage] = {}
        self._init_demo_messages()

    def _init_demo_messages(self):
        now = datetime.now()
        samples = [
            EmailMessage(
                id=encode_composite_id("DEMO", self.account_id, "demo_rec_01"),
                conversation_id="demo_conv_01",
                subject="[DEMO] Principal Solutions Architect (Google Cloud & Generative AI) - $260k-$320k",
                sender_name="Sarah Jenkins (Apex Recruiting)",
                sender_email="sarah.jenkins@apexrecruiters.example",
                received_at=(now - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M"),
                preview="Hi Brian, I came across your impressive background in Enterprise Architecture and Google Cloud...",
                body_text=(
                    "Hi Brian,\n\n"
                    "I came across your background in enterprise cloud architecture and pre-sales advisory. "
                    "We are looking for a Principal Solutions Architect to lead pre-sales and technical delivery "
                    "for high-impact Google Cloud and BigQuery enterprise migrations.\n\n"
                    "Compensation: $260,000 - $320,000 base + equity + bonus (Remote US).\n\n"
                    "Could you share your updated resume and availability for a quick introductory chat?\n\n"
                    "Best,\nSarah Jenkins\nExecutive Talent Partner"
                ),
                is_read=False,
                folder="Inbox"
            ),
            EmailMessage(
                id=encode_composite_id("DEMO", self.account_id, "demo_noise_01"),
                conversation_id="demo_conv_02",
                subject="[DEMO] Exclusive Cloud Infrastructure Webinar: 50% Off Annual Enterprise Plans",
                sender_name="CloudScale Marketing",
                sender_email="promotions@cloudscale-events.example",
                received_at=(now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
                preview="Don't miss our exclusive webinar on modern cloud optimization! Unsubscribe at any time...",
                body_text="Claim your 50% discount today by registering for our webinar. Unsubscribe at any time.",
                is_read=True,
                folder="Inbox"
            )
        ]
        self._mock_messages = {m.id: m for m in samples}

    def authenticate(self, account_config: Dict[str, Any], auth_payload: Optional[Dict[str, Any]] = None) -> ProviderOperationResult:
        return ProviderOperationResult(
            success=True,
            provider="DEMO",
            account_id=self.account_id,
            operation="AUTHENTICATE",
            safe_message="Demo Mode authenticated (Offline Mock Environment)."
        )

    def validate_connection(self, account_id: str) -> ProviderOperationResult:
        return ProviderOperationResult(
            success=True,
            provider="DEMO",
            account_id=self.account_id,
            operation="VALIDATE",
            safe_message="Demo Mode active."
        )

    def list_accounts(self) -> List[AccountIdentity]:
        return [
            AccountIdentity(
                account_id=self.account_id,
                email_address=self.account_id,
                provider=ProviderType.DEMO,
                display_name="Demo Mode (Offline Sandbox)",
                is_connected=True,
                is_primary=False,
                last_sync_time=datetime.now().isoformat(),
                capabilities=["DRAFTS", "SEND", "ATTACHMENTS", "MOVE", "DELETE", "QUARANTINE"]
            )
        ]

    def fetch_inbox_messages(self, account_id: str, limit: int = 50, folder: str = "Inbox") -> Tuple[List[EmailMessage], Optional[str]]:
        return list(self._mock_messages.values()), None

    def create_reply_draft(
        self, 
        account_id: str, 
        message_id: str, 
        reply_body: str, 
        resume_filename: Optional[str] = None
    ) -> ProviderOperationResult:
        draft_id = f"demo_draft_{int(datetime.now().timestamp())}"
        msg = self._mock_messages.get(message_id)
        if msg:
            msg.draft_reply = reply_body
            msg.selected_resume_file = resume_filename
            msg.status = "DRAFTED"
        return ProviderOperationResult(
            success=True,
            provider="DEMO",
            account_id=self.account_id,
            operation="CREATE_DRAFT",
            remote_object_id=draft_id,
            safe_message=f"[DEMO] Draft saved in simulated Drafts folder with '{resume_filename or 'resume'}' attached."
        )

    def attach_file(
        self, 
        account_id: str, 
        draft_id: str, 
        filename: str, 
        file_path: Path
    ) -> ProviderOperationResult:
        return ProviderOperationResult(
            success=True,
            provider="DEMO",
            account_id=self.account_id,
            operation="ATTACH_FILE",
            remote_object_id=draft_id,
            safe_message=f"[DEMO] File '{filename}' attached to draft {draft_id}."
        )


    def create_or_resolve_quarantine_folder(self, account_id: str, folder_name: str = "AI Cleaned - Noise") -> Optional[str]:
        return "demo_quarantine_folder_id"

    def move_message(self, account_id: str, message_id: str, destination_folder_id: str) -> ProviderOperationResult:
        msg = self._mock_messages.get(message_id)
        if msg:
            msg.status = "TRASHED"
            msg.folder = destination_folder_id
        return ProviderOperationResult(
            success=True,
            provider="DEMO",
            account_id=self.account_id,
            operation="MOVE_MESSAGE",
            safe_message=f"[DEMO] Message moved to simulated folder '{destination_folder_id}'."
        )

    def delete_message(self, account_id: str, message_id: str) -> ProviderOperationResult:
        msg = self._mock_messages.get(message_id)
        if msg:
            msg.status = "TRASHED"
        return ProviderOperationResult(
            success=True,
            provider="DEMO",
            account_id=self.account_id,
            operation="DELETE_MESSAGE",
            safe_message="[DEMO] Message deleted in simulated environment."
        )

    def get_health_status(self, account_id: str) -> Dict[str, Any]:
        return {"status": "HEALTHY", "mode": "DEMO", "account": self.account_id}

    def logout(self, account_id: Optional[str] = None) -> ProviderOperationResult:
        return ProviderOperationResult(
            success=True,
            provider="DEMO",
            account_id=self.account_id,
            operation="LOGOUT",
            safe_message="Demo mode reset."
        )

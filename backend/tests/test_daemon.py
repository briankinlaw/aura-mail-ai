"""
Unit Tests for Aura Mail AI Autonomous Background Daemon
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import tempfile

from backend.daemon import (
    load_processed_ids,
    save_processed_id,
    send_macos_notification,
    run_daemon_cycle
)
from backend.daemon_cli import generate_launchd_plist
from backend.models import EmailMessage, EmailCategory, ClassificationResult, RecruiterDetails
from backend.providers.base import ProviderOperationResult


class TestAuraDaemon(unittest.TestCase):
    def test_launchd_plist_generation(self):
        plist = generate_launchd_plist(interval_seconds=900)
        self.assertIn("com.briankinlaw.aura-mail-daemon", plist)
        self.assertIn("<integer>900</integer>", plist)
        self.assertIn("aura-daemon", plist)
        self.assertIn("<key>RunAtLoad</key>", plist)

    @patch("backend.daemon.sys.platform", "darwin")
    @patch("backend.daemon.subprocess.run")
    def test_send_macos_notification(self, mock_sub):
        send_macos_notification("Aura Mail", "New Lead", "Testing notification")
        self.assertTrue(mock_sub.called)
        args, kwargs = mock_sub.call_args
        cmd = args[0]
        self.assertEqual(cmd[0], "osascript")
        self.assertIn("Testing notification", cmd[2])

    @patch("backend.daemon.sys.platform", "linux")
    @patch("backend.daemon.subprocess.run")
    def test_send_macos_notification_non_darwin(self, mock_sub):
        send_macos_notification("Aura Mail", "New Lead", "Testing notification")
        self.assertFalse(mock_sub.called)

    @patch("backend.daemon.load_processed_ids", return_value=set())
    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.send_macos_notification")
    def test_run_daemon_cycle(self, mock_notify, mock_classify, mock_pm_cls, mock_processed):

        # Mock ProviderManager
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        test_msg = EmailMessage(
            id="daemon_test_msg_01",
            account_id="kinlawb@outlook.com",
            sender_name="Recruiter Emma",
            sender_email="emma@techrecruiting.com",
            subject="Opportunity: Principal AI & Cloud Architect ($260k-$290k)",
            body_text="Hi Brian, are you free for a quick call next week to discuss this Principal Architect role?",
            received_at="2026-09-13 10:00",
            preview="Hi Brian, are you free...",
            folder="Jobs"
        )
        mock_pm.sync_unified_inbox.return_value = ([test_msg], {"accounts_synced": 1, "accounts_failed": 0, "status": "SUCCESS"})
        mock_pm.save_draft_reply.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft created successfully",
            remote_object_id="draft_123"
        )



        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            confidence=0.95,
            reasoning="Recruiter inquiring about Principal AI role",
            is_noise=False,
            is_resume_request=True,
            recruiter_details=RecruiterDetails(
                recruiter_name="Emma",
                company_name="NextGen Tech",
                role_title="Principal AI & Cloud Architect",
                location="Remote (US)",
                salary_range="$260k-$290k",
                required_skills=["Google Cloud", "AI Governance", "Architecture"]
            ),
            suggested_action="REPLY"
        )

        # Run cycle in dry-run mode first
        summary = run_daemon_cycle(dry_run=True)
        self.assertEqual(summary["messages_checked"], 1)
        self.assertEqual(summary["drafts_staged"], 1)
        self.assertEqual(len(summary["high_fit_opportunities"]), 1)
        self.assertEqual(summary["high_fit_opportunities"][0]["role_title"], "Principal AI & Cloud Architect")

    @patch("backend.daemon.load_processed_ids", return_value=set())
    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.send_macos_notification")
    def test_permanent_invariant_daemon_never_calls_send_reply(self, mock_notify, mock_classify, mock_pm_cls, mock_processed):
        """
        PERMANENT SAFETY INVARIANT TEST:
        BACKGROUND EXECUTION -> SEND FORBIDDEN
        Verifies that non-dry-run autonomous daemon execution strictly stages drafts
        and NEVER invokes send_reply() under any circumstances.
        """
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        test_msg = EmailMessage(
            id="daemon_invariant_msg_01",
            account_id="kinlawb@outlook.com",
            sender_name="Recruiter Marcus",
            sender_email="marcus@talent.com",
            subject="Urgent: Lead Cloud & AI Solutions Architect",
            body_text="Hi Brian, please share your resume and availability for this urgent lead role.",
            received_at="2026-09-13 11:00",
            preview="Hi Brian...",
            folder="Inbox"
        )
        mock_pm.sync_unified_inbox.return_value = ([test_msg], {"accounts_synced": 1, "status": "SUCCESS"})
        mock_pm.save_draft_reply.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft created",
            remote_object_id="draft_inv_123"
        )

        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            confidence=0.98,
            reasoning="Recruiter inquiring about Lead Cloud Architect",
            is_noise=False,
            is_resume_request=True,
            recruiter_details=RecruiterDetails(
                recruiter_name="Marcus",
                company_name="Apex Cloud",
                role_title="Lead Cloud & AI Solutions Architect",
                salary_range="$250k-$280k",
                required_skills=["Google Cloud", "AI", "Architecture"]
            ),
            suggested_action="REPLY"
        )

        # Execute live (non-dry-run) daemon cycle
        summary = run_daemon_cycle(dry_run=False)

        # Invariant Assertions:
        self.assertEqual(summary["drafts_staged"], 1)
        # 1. save_draft_reply MUST be called
        mock_pm.save_draft_reply.assert_called_once()
        # 2. send_reply MUST NEVER be called
        mock_pm.send_reply.assert_not_called()
        self.assertFalse(mock_pm.send_reply.called, "CRITICAL INVARIANT VIOLATION: Daemon attempted to call send_reply()!")

    @patch("backend.daemon.save_processed_id")
    @patch("backend.daemon.load_processed_ids")
    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    def test_daemon_quarantine_failure_retried_on_next_cycle(self, mock_classify, mock_pm_cls, mock_load_processed, mock_save_processed):
        """
        RELIABILITY BOUNDARY:
        Verifies that when auto-quarantining a noise email fails:
        1. The message ID is NOT added to processed IDs.
        2. The failure is reported in summary['errors'].
        3. A subsequent daemon cycle retries and successfully quarantines the message.
        4. On success, the message ID is saved and subsequent cycles skip it.
        """
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        noise_msg = EmailMessage(
            id="noise_retry_01",
            account_id="kinlawb@outlook.com",
            sender_name="Spam Bot",
            sender_email="promo@spam.com",
            subject="Spam Promotion",
            body_text="Claim discount now",
            status="INBOUND"
        )
        mock_pm.sync_unified_inbox.return_value = ([noise_msg], {"accounts_synced": 1, "status": "SUCCESS"})

        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.99,
            reasoning="Promotional noise",
            is_noise=True
        )

        # Cycle 1: Quarantine fails (e.g. temporary network/folder error)
        mock_load_processed.return_value = set()
        mock_pm.quarantine_message.return_value = ProviderOperationResult(
            success=False,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="QUARANTINE",
            safe_message="Failed to move: folder lock conflict"
        )

        summary1 = run_daemon_cycle(dry_run=False)
        self.assertEqual(summary1["noise_quarantined"], 0)
        self.assertTrue(any("Failed to auto-quarantine noise_retry_01" in err for err in summary1["errors"]))
        # save_processed_id MUST NOT be called for the failed message
        mock_save_processed.assert_not_called()

        # Cycle 2: Subsequent cycle runs with message still unrecorded in processed_ids; succeeds
        mock_pm.quarantine_message.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="QUARANTINE",
            safe_message="Moved to AI Cleaned - Noise"
        )

        summary2 = run_daemon_cycle(dry_run=False)
        self.assertEqual(summary2["noise_quarantined"], 1)
        self.assertEqual(len(summary2["errors"]), 0)
        mock_save_processed.assert_called_once()
        save_args, _ = mock_save_processed.call_args
        self.assertEqual(save_args[0], "noise_retry_01")
        self.assertEqual(save_args[1]["action"], "QUARANTINED_NOISE")

    @patch("backend.daemon.save_processed_id")
    @patch("backend.daemon.load_processed_ids", return_value=set())
    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.load_settings")
    def test_daemon_dry_run_and_disabled_quarantine_explicit(self, mock_settings, mock_classify, mock_pm_cls, mock_load_processed, mock_save_processed):
        """
        Verifies dry-run and disabled auto-quarantine explicitly record truthful actions.
        """
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        noise_msg = EmailMessage(
            id="noise_dry_01",
            account_id="kinlawb@outlook.com",
            sender_name="Spam Bot",
            sender_email="promo@spam.com",
            subject="Spam Promotion",
            body_text="Claim discount now",
            status="INBOUND"
        )
        mock_pm.sync_unified_inbox.return_value = ([noise_msg], {"accounts_synced": 1, "status": "SUCCESS"})
        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.99,
            reasoning="Promotional noise",
            is_noise=True
        )

        # 1. Dry run: action is DRY_RUN_NOISE
        mock_settings.return_value = {"auto_quarantine_noise": True}
        summary_dry = run_daemon_cycle(dry_run=True)
        self.assertEqual(summary_dry["noise_skipped"], 1)
        mock_pm.quarantine_message.assert_not_called()
        self.assertTrue(mock_save_processed.called)
        self.assertEqual(mock_save_processed.call_args[0][1]["action"], "DRY_RUN_NOISE")

        # 2. Disabled auto-quarantine: action is AUTO_QUARANTINE_DISABLED
        mock_save_processed.reset_mock()
        mock_settings.return_value = {"auto_quarantine_noise": False}
        summary_disabled = run_daemon_cycle(dry_run=False)
        self.assertEqual(summary_disabled["noise_skipped"], 1)
        mock_pm.quarantine_message.assert_not_called()
        self.assertTrue(mock_save_processed.called)
        self.assertEqual(mock_save_processed.call_args[0][1]["action"], "AUTO_QUARANTINE_DISABLED")

if __name__ == "__main__":
    unittest.main()

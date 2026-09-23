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
    record_diagnostic_event,
    reconcile_processed_state,
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
        self.assertEqual(summary["drafts_staged"], 0)
        self.assertEqual(summary["drafts_simulated"], 1)
        self.assertEqual(len(summary["high_fit_opportunities"]), 1)
        self.assertEqual(summary["high_fit_opportunities"][0]["role_title"], "Principal AI & Cloud Architect")
        self.assertTrue(summary["high_fit_opportunities"][0]["simulated"])

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
        1. The message ID is NOT added to processed IDs (live_success=False).
        2. The failure is reported in summary['errors'].
        3. A subsequent daemon cycle retries and successfully quarantines the message.
        4. On success, the message ID is saved with live_success=True and subsequent cycles skip it.
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
        # Diagnostic record called with live_success=False
        self.assertTrue(mock_save_processed.called)
        _, k1 = mock_save_processed.call_args
        self.assertFalse(k1.get("live_success", True))

        # Cycle 2: Subsequent cycle runs with message still unrecorded in processed_ids; succeeds
        mock_save_processed.reset_mock()
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
        save_args, save_kwargs = mock_save_processed.call_args
        self.assertEqual(save_args[0], "noise_retry_01")
        self.assertEqual(save_args[1]["action"], "QUARANTINED_NOISE")
        self.assertTrue(save_kwargs.get("live_success", True))

    @patch("backend.daemon.save_processed_id")
    @patch("backend.daemon.load_processed_ids", return_value=set())
    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.load_settings")
    def test_daemon_dry_run_and_disabled_quarantine_explicit(self, mock_settings, mock_classify, mock_pm_cls, mock_load_processed, mock_save_processed):
        """
        Verifies dry-run and disabled auto-quarantine explicitly record diagnostic records without live success.
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

        # 1. Dry run: action is DRY_RUN_NOISE with live_success=False
        mock_settings.return_value = {"auto_quarantine_noise": True}
        summary_dry = run_daemon_cycle(dry_run=True)
        self.assertEqual(summary_dry["noise_skipped"], 1)
        mock_pm.quarantine_message.assert_not_called()
        self.assertTrue(mock_save_processed.called)
        self.assertEqual(mock_save_processed.call_args[0][1]["action"], "DRY_RUN_NOISE")
        self.assertFalse(mock_save_processed.call_args[1].get("live_success", True))

        # 2. Disabled auto-quarantine: action is AUTO_QUARANTINE_DISABLED with live_success=False
        mock_save_processed.reset_mock()
        mock_settings.return_value = {"auto_quarantine_noise": False}
        summary_disabled = run_daemon_cycle(dry_run=False)
        self.assertEqual(summary_disabled["noise_skipped"], 1)
        mock_pm.quarantine_message.assert_not_called()
        self.assertTrue(mock_save_processed.called)
        self.assertEqual(mock_save_processed.call_args[0][1]["action"], "AUTO_QUARANTINE_DISABLED")
        self.assertFalse(mock_save_processed.call_args[1].get("live_success", True))


class TestAuraDaemonProcessedState(unittest.TestCase):
    """
    State Transition Tests for Daemon Processed-State Semantics using real temporary files:
    1. Failed quarantine → successful retry → no third move.
    2. Noise dry run → successful live move.
    3. Auto-quarantine disabled → enabled → successful live move.
    4. Recruiter dry run → successful live draft stage.
    5. Existing skipped/dry-run record → reconciliation → live action.
    6. A later successful record for the same ID → reconciliation preserves the processed ID.
    7. An ID without sufficient historical evidence → reconciliation leaves it untouched.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.tmp_dir.name) / "daemon_processed.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_atomic_state_write_failure_preserves_prior_success(self):
        save_processed_id("already_staged", {"action": "DRAFT_STAGED"}, log_file=self.log_file)
        original = self.log_file.read_bytes()
        with patch("backend.daemon.os.replace", side_effect=OSError("interrupted replacement")):
            with self.assertRaisesRegex(OSError, "interrupted replacement"):
                record_diagnostic_event("other", {"action": "DRY_RUN_NOISE"}, log_file=self.log_file)
        self.assertEqual(self.log_file.read_bytes(), original)
        self.assertEqual(load_processed_ids(self.log_file), {"already_staged"})

    @patch("backend.daemon.ProviderManager")
    def test_reconciliation_error_stops_before_provider_actions(self, mock_pm_cls):
        self.log_file.write_text("{invalid json", encoding="utf-8")
        original = self.log_file.read_bytes()
        summary = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertTrue(any("reconciliation failed" in error for error in summary["errors"]))
        mock_pm_cls.assert_not_called()
        self.assertEqual(self.log_file.read_bytes(), original)

    @patch("backend.daemon.ProviderManager")
    def test_reconciliation_write_failure_stops_before_provider_actions(self, mock_pm_cls):
        self.log_file.write_text(json.dumps({"processed_message_ids": ["skipped"],
            "records": [{"message_id": "skipped", "details": {"action": "DRY_RUN_NOISE"}}]}), encoding="utf-8")
        original = self.log_file.read_bytes()
        with patch("backend.daemon.os.replace", side_effect=OSError("interrupted replacement")):
            summary = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertTrue(any("reconciliation failed" in error for error in summary["errors"]))
        mock_pm_cls.assert_not_called()
        self.assertEqual(self.log_file.read_bytes(), original)

    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.load_settings")
    def test_1_failed_quarantine_retry_then_no_third_move(self, mock_settings, mock_classify, mock_pm_cls):
        """1. Failed quarantine → successful retry → no third move."""
        mock_settings.return_value = {"auto_quarantine_noise": True, "safe_folder_name": "AI Cleaned - Noise"}
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        msg = EmailMessage(
            id="noise_flow_1",
            account_id="kinlawb@outlook.com",
            sender_name="Spam Bot",
            sender_email="promo@spam.com",
            subject="Discount Offer",
            body_text="Buy now",
            status="INBOUND"
        )
        mock_pm.sync_unified_inbox.return_value = ([msg], {"accounts_synced": 1, "status": "SUCCESS"})
        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.99,
            reasoning="Spam promo",
            is_noise=True
        )

        # Cycle 1: Quarantine fails
        mock_pm.quarantine_message.return_value = ProviderOperationResult(
            success=False,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="QUARANTINE",
            safe_message="Timeout moving message"
        )
        s1 = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s1["noise_quarantined"], 0)
        self.assertEqual(len(s1["errors"]), 1)
        self.assertNotIn("noise_flow_1", load_processed_ids(self.log_file))

        # Cycle 2: Quarantine succeeds on retry
        mock_pm.quarantine_message.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="QUARANTINE",
            safe_message="Moved"
        )
        s2 = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s2["noise_quarantined"], 1)
        self.assertIn("noise_flow_1", load_processed_ids(self.log_file))

        # Cycle 3: Message is already processed -> skipped (no 3rd move)
        mock_pm.quarantine_message.reset_mock()
        s3 = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s3["noise_quarantined"], 0)
        mock_pm.quarantine_message.assert_not_called()

    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.load_settings")
    def test_2_noise_dry_run_then_successful_live_move(self, mock_settings, mock_classify, mock_pm_cls):
        """2. Noise dry run → successful live move."""
        mock_settings.return_value = {"auto_quarantine_noise": True, "safe_folder_name": "AI Cleaned - Noise"}
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        msg = EmailMessage(
            id="noise_dry_live_1",
            account_id="kinlawb@outlook.com",
            sender_name="Newsletter",
            sender_email="news@daily.com",
            subject="Tech Updates",
            body_text="Daily digest",
            status="INBOUND"
        )
        mock_pm.sync_unified_inbox.return_value = ([msg], {"accounts_synced": 1, "status": "SUCCESS"})
        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.NOISE_NEWSLETTER,
            confidence=0.95,
            reasoning="Newsletter",
            is_noise=True
        )

        # Cycle 1: Dry run
        s1 = run_daemon_cycle(dry_run=True, log_file=self.log_file)
        self.assertEqual(s1["noise_skipped"], 1)
        self.assertEqual(s1["noise_quarantined"], 0)
        self.assertNotIn("noise_dry_live_1", load_processed_ids(self.log_file))
        mock_pm.quarantine_message.assert_not_called()

        # Cycle 2: Live execution
        mock_pm.quarantine_message.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="QUARANTINE",
            safe_message="Moved"
        )
        s2 = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s2["noise_quarantined"], 1)
        self.assertIn("noise_dry_live_1", load_processed_ids(self.log_file))

    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.load_settings")
    def test_3_auto_quarantine_disabled_then_enabled_successful_move(self, mock_settings, mock_classify, mock_pm_cls):
        """3. Auto-quarantine disabled → enabled → successful live move."""
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        msg = EmailMessage(
            id="noise_toggle_1",
            account_id="kinlawb@outlook.com",
            sender_name="Promo",
            sender_email="promo@shop.com",
            subject="Special Deals",
            body_text="Discounts",
            status="INBOUND"
        )
        mock_pm.sync_unified_inbox.return_value = ([msg], {"accounts_synced": 1, "status": "SUCCESS"})
        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.99,
            reasoning="Promotional offer",
            is_noise=True
        )

        # Cycle 1: Auto-quarantine disabled
        mock_settings.return_value = {"auto_quarantine_noise": False, "safe_folder_name": "AI Cleaned - Noise"}
        s1 = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s1["noise_skipped"], 1)
        self.assertEqual(s1["noise_quarantined"], 0)
        self.assertNotIn("noise_toggle_1", load_processed_ids(self.log_file))

        # Cycle 2: Auto-quarantine enabled
        mock_settings.return_value = {"auto_quarantine_noise": True, "safe_folder_name": "AI Cleaned - Noise"}
        mock_pm.quarantine_message.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="QUARANTINE",
            safe_message="Moved"
        )
        s2 = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s2["noise_quarantined"], 1)
        self.assertIn("noise_toggle_1", load_processed_ids(self.log_file))

    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.send_macos_notification")
    def test_4_recruiter_dry_run_then_successful_live_draft(self, mock_notify, mock_classify, mock_pm_cls):
        """4. Recruiter dry run → successful live draft stage."""
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        msg = EmailMessage(
            id="recruiter_dry_1",
            account_id="kinlawb@outlook.com",
            sender_name="Tech Recruiter",
            sender_email="recruiter@talent.com",
            subject="Principal Architect Search",
            body_text="Hi Brian, please share your resume for this Principal Architect role.",
            status="INBOUND"
        )
        mock_pm.sync_unified_inbox.return_value = ([msg], {"accounts_synced": 1, "status": "SUCCESS"})
        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            confidence=0.98,
            reasoning="Recruiter inquiry",
            is_noise=False,
            is_resume_request=True,
            recruiter_details=RecruiterDetails(
                recruiter_name="Sarah",
                company_name="Innovate",
                role_title="Principal Architect",
                salary_range="$275k-$310k",
                required_skills=["Cloud", "AI"]
            ),
            suggested_action="REPLY"
        )

        # Cycle 1: Dry run
        s1 = run_daemon_cycle(dry_run=True, log_file=self.log_file)
        self.assertEqual(s1["drafts_simulated"], 1)
        self.assertEqual(s1["drafts_staged"], 0)
        self.assertNotIn("recruiter_dry_1", load_processed_ids(self.log_file))
        mock_pm.save_draft_reply.assert_not_called()

        # Cycle 2: Live draft stage
        mock_pm.save_draft_reply.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft staged successfully"
        )
        s2 = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s2["drafts_staged"], 1)
        self.assertEqual(s2["drafts_simulated"], 0)
        self.assertIn("recruiter_dry_1", load_processed_ids(self.log_file))

    @patch("backend.daemon.ProviderManager")
    @patch("backend.daemon.classify_email_radar")
    @patch("backend.daemon.load_settings")
    def test_5_existing_dry_run_record_reconciliation_then_live_action(self, mock_settings, mock_classify, mock_pm_cls):
        """5. Existing skipped/dry-run record → reconciliation → live action."""
        mock_settings.return_value = {"auto_quarantine_noise": True, "safe_folder_name": "AI Cleaned - Noise"}
        mock_pm = MagicMock()
        mock_pm_cls.return_value = mock_pm

        # Pre-populate daemon_processed.json with an erroneous DRY_RUN_NOISE in processed_message_ids
        initial_data = {
            "processed_message_ids": ["legacy_dry_noise_1"],
            "records": [
                {
                    "message_id": "legacy_dry_noise_1",
                    "processed_at": "2026-09-15T12:00:00",
                    "details": {
                        "category": "NOISE_PROMOTIONAL",
                        "action": "DRY_RUN_NOISE",
                        "dry_run": True
                    }
                }
            ]
        }
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=2)

        # Before reconciliation, ID is in processed_ids
        self.assertIn("legacy_dry_noise_1", load_processed_ids(self.log_file))

        # Reconcile removes it
        rec_res = reconcile_processed_state(self.log_file)
        self.assertEqual(rec_res["reconciled_removed"], 1)
        self.assertNotIn("legacy_dry_noise_1", load_processed_ids(self.log_file))

        # Now running cycle processes it live
        msg = EmailMessage(
            id="legacy_dry_noise_1",
            account_id="kinlawb@outlook.com",
            sender_name="Spam Bot",
            sender_email="deals@promo.com",
            subject="Special discount",
            body_text="Deals",
            status="INBOUND"
        )
        mock_pm.sync_unified_inbox.return_value = ([msg], {"accounts_synced": 1, "status": "SUCCESS"})
        mock_classify.return_value = ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.99,
            reasoning="Promotional offer",
            is_noise=True
        )
        mock_pm.quarantine_message.return_value = ProviderOperationResult(
            success=True,
            provider="GRAPH",
            account_id="kinlawb@outlook.com",
            operation="QUARANTINE",
            safe_message="Moved"
        )

        s = run_daemon_cycle(dry_run=False, log_file=self.log_file)
        self.assertEqual(s["noise_quarantined"], 1)
        self.assertIn("legacy_dry_noise_1", load_processed_ids(self.log_file))

    def test_6_later_successful_record_preserves_processed_id_during_reconciliation(self):
        """6. A later successful record for the same ID → reconciliation preserves the processed ID."""
        initial_data = {
            "processed_message_ids": ["multi_event_msg_1"],
            "records": [
                {
                    "message_id": "multi_event_msg_1",
                    "processed_at": "2026-09-15T10:00:00",
                    "details": {
                        "category": "NOISE_PROMOTIONAL",
                        "action": "DRY_RUN_NOISE",
                        "dry_run": True
                    }
                },
                {
                    "message_id": "multi_event_msg_1",
                    "processed_at": "2026-09-15T11:00:00",
                    "details": {
                        "category": "NOISE_PROMOTIONAL",
                        "action": "QUARANTINED_NOISE",
                        "live_success": True
                    }
                }
            ]
        }
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=2)

        rec_res = reconcile_processed_state(self.log_file)
        self.assertEqual(rec_res["confirmed_preserved"], 1)
        self.assertEqual(rec_res["reconciled_removed"], 0)
        self.assertIn("multi_event_msg_1", load_processed_ids(self.log_file))

    def test_7_insufficient_history_leaves_id_untouched(self):
        """7. An ID without sufficient historical evidence → reconciliation leaves it untouched."""
        initial_data = {
            "processed_message_ids": ["capped_history_id_1", "capped_history_id_2"],
            "records": [
                # Records array has been capped/truncated and doesn't contain entries for capped_history_id_*
                {
                    "message_id": "other_recent_msg",
                    "processed_at": "2026-09-15T12:00:00",
                    "details": {
                        "category": "NOISE_PROMOTIONAL",
                        "action": "QUARANTINED_NOISE",
                        "live_success": True
                    }
                }
            ]
        }
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=2)

        rec_res = reconcile_processed_state(self.log_file)
        self.assertEqual(rec_res["insufficient_history"], 2)
        self.assertEqual(rec_res["reconciled_removed"], 0)
        processed = load_processed_ids(self.log_file)
        self.assertIn("capped_history_id_1", processed)
        self.assertIn("capped_history_id_2", processed)


if __name__ == "__main__":
    unittest.main()

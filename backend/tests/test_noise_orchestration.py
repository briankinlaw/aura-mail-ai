"""Unit and Integration Tests for Multi-Account Noise Orchestration & Zero-Noise Inbox Architecture.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app, CACHED_EMAILS
from backend.models import EmailMessage, ClassificationResult, EmailCategory, RecruiterDetails, QuarantineBatchResult, QuarantineMessageResult
from backend.providers.base import ProviderOperationResult
from backend.auth import get_auth_headers
from backend.analytics import init_analytics_db
from backend.daemon import run_daemon_cycle

auth_client = TestClient(app)
auth_client.headers.update(get_auth_headers())
unauth_client = TestClient(app)


def test_clean_noise_batch_api(tmp_path, monkeypatch):
    """Verifies that POST /api/emails/clean-noise relocates noise emails to cloud safe folder."""
    test_db = tmp_path / "test_noise.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    init_analytics_db()

    noise_id = "MICROSOFT_GRAPH::kinlawb@outlook.com::noise_promo_1"
    recruiter_id = "GMAIL::brian@mavencode.com::recruiter_req_1"

    CACHED_EMAILS[noise_id] = EmailMessage(
        id=noise_id,
        sender_name="Promo Marketing",
        sender_email="promo@deals.com",
        subject="50% Off Cloud Hosting Today!",
        body_text="Click here to claim your coupon...",
        preview="Click here to claim...",
        account_id="kinlawb@outlook.com",
        provider="MICROSOFT_GRAPH",
        status="INBOUND",
        classification=ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.99,
            reasoning="Promotional offer",
            is_noise=True,
            is_resume_request=False
        )
    )

    CACHED_EMAILS[recruiter_id] = EmailMessage(
        id=recruiter_id,
        sender_name="Tech Recruiter",
        sender_email="recruiter@enterprise.com",
        subject="Principal Cloud Architect Role",
        body_text="Hi Brian, let's connect regarding an Enterprise Architect position.",
        preview="Hi Brian...",
        account_id="brian@mavencode.com",
        provider="GMAIL",
        status="INBOUND",
        classification=ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            confidence=0.95,
            reasoning="Recruiter resume inquiry",
            is_noise=False,
            is_resume_request=True
        )
    )

    with patch("backend.main.provider_manager.batch_quarantine_noise") as mock_batch:
        mock_batch.return_value = QuarantineBatchResult(
            status="SUCCESS",
            total_requested=1,
            cleaned_count=1,
            failed_count=0,
            cleaned_ids=[noise_id],
            results=[
                QuarantineMessageResult(
                    email_id=noise_id,
                    subject="50% Off Cloud Hosting Today!",
                    provider="MICROSOFT_GRAPH",
                    account_id="kinlawb@outlook.com",
                    success=True,
                    message="Moved"
                )
            ],
            message="Cleaned 1 noise emails."
        )

        res = auth_client.post("/api/emails/clean-noise", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert data["cleaned_count"] == 1
        assert noise_id in data["cleaned_ids"]

        # Verify noise email status updated to TRASHED and recruiter remains INBOUND
        assert CACHED_EMAILS[noise_id].status == "TRASHED"
        assert CACHED_EMAILS[recruiter_id].status == "INBOUND"


def test_quarantine_single_email_api(tmp_path, monkeypatch):
    """Verifies single email quarantine endpoint /api/emails/{id}/quarantine."""
    test_db = tmp_path / "test_noise_single.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    init_analytics_db()

    email_id = "IMAP::briankinlaw@satx.rr.com::newsletter_1"
    CACHED_EMAILS[email_id] = EmailMessage(
        id=email_id,
        sender_name="Daily Digest",
        sender_email="newsletter@digest.com",
        subject="Top 10 Tech Stories This Week",
        body_text="Here are the top stories...",
        preview="Here are the top stories...",
        account_id="briankinlaw@satx.rr.com",
        provider="IMAP",
        status="INBOUND",
        classification=ClassificationResult(
            category=EmailCategory.NOISE_NEWSLETTER,
            confidence=0.95,
            reasoning="Weekly newsletter",
            is_noise=True,
            is_resume_request=False
        )
    )

    # Unauthenticated request rejected
    unauth_res = unauth_client.post(f"/api/emails/{email_id}/quarantine")
    assert unauth_res.status_code == 401

    with patch("backend.main.provider_manager.quarantine_message") as mock_q:
        mock_q.return_value = ProviderOperationResult(
            success=True,
            provider="IMAP",
            account_id="briankinlaw@satx.rr.com",
            operation="QUARANTINE",
            safe_message="Message quarantined."
        )

        res = auth_client.post(f"/api/emails/{email_id}/quarantine")
        assert res.status_code == 200
        assert res.json()["status"] == "SUCCESS"
        assert CACHED_EMAILS[email_id].status == "TRASHED"


def test_orchestrate_noise_endpoint(tmp_path, monkeypatch):
    """Verifies multi-account sweep via POST /api/inbox/orchestrate-noise."""
    test_db = tmp_path / "test_noise_orch.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    init_analytics_db()

    email_outlook = "MICROSOFT_GRAPH::kinlawb@outlook.com::noise_notif_1"
    email_gmail = "GMAIL::briankkinlaw@gmail.com::noise_promo_2"

    CACHED_EMAILS[email_outlook] = EmailMessage(
        id=email_outlook,
        sender_name="System Bot",
        sender_email="alerts@social.com",
        subject="You have 3 new notifications",
        body_text="Check your activity...",
        preview="Check your activity...",
        account_id="kinlawb@outlook.com",
        provider="MICROSOFT_GRAPH",
        status="INBOUND",
        classification=ClassificationResult(
            category=EmailCategory.NOISE_NOTIFICATION,
            confidence=0.98,
            reasoning="System alert notification",
            is_noise=True
        )
    )

    CACHED_EMAILS[email_gmail] = EmailMessage(
        id=email_gmail,
        sender_name="Sales Team",
        sender_email="sales@vendor.com",
        subject="Special pricing on licenses",
        body_text="Exclusive deal for your company...",
        preview="Exclusive deal...",
        account_id="briankkinlaw@gmail.com",
        provider="GMAIL",
        status="INBOUND",
        classification=ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.99,
            reasoning="Promotional sales pitch",
            is_noise=True
        )
    )

    with patch("backend.main.provider_manager.batch_quarantine_noise") as mock_batch:
        mock_batch.return_value = QuarantineBatchResult(
            status="SUCCESS",
            total_requested=2,
            cleaned_count=2,
            failed_count=0,
            cleaned_ids=[email_outlook, email_gmail],
            results=[
                QuarantineMessageResult(
                    email_id=email_outlook,
                    subject="You have 3 new notifications",
                    provider="MICROSOFT_GRAPH",
                    account_id="kinlawb@outlook.com",
                    success=True,
                    message="Moved"
                ),
                QuarantineMessageResult(
                    email_id=email_gmail,
                    subject="Special pricing on licenses",
                    provider="GMAIL",
                    account_id="briankkinlaw@gmail.com",
                    success=True,
                    message="Moved"
                )
            ],
            message="Cleaned 2 noise emails."
        )

        res = auth_client.post("/api/inbox/orchestrate-noise", json={"sync_first": False})
        assert res.status_code == 200
        data = res.json()
        assert "total_noise_quarantined" in data
        assert data["total_noise_quarantined"] == 2
        assert "per_account_stats" in data
        assert len(data["per_account_stats"]) > 0


@patch("backend.daemon.ProviderManager")
@patch("backend.daemon.classify_email_radar")
@patch("backend.daemon.load_processed_ids", return_value=set())
def test_daemon_auto_quarantine_cycle(mock_processed, mock_classify, mock_pm_cls, tmp_path, monkeypatch):
    """Verifies daemon cycle runs with auto-quarantine enabled without regressions."""
    test_db = tmp_path / "test_daemon_noise.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    init_analytics_db()

    mock_pm = MagicMock()
    mock_pm_cls.return_value = mock_pm

    noise_msg = EmailMessage(
        id="daemon_noise_01",
        account_id="kinlawb@outlook.com",
        sender_name="Spam Bot",
        sender_email="spam@promo.com",
        subject="Get rich quick",
        body_text="Spam body",
        preview="Spam preview",
        status="INBOUND"
    )

    mock_pm.sync_unified_inbox.return_value = ([noise_msg], {"accounts_synced": 1})
    mock_pm.quarantine_message.return_value = MagicMock(success=True)

    mock_classify.return_value = ClassificationResult(
        category=EmailCategory.NOISE_PROMOTIONAL,
        confidence=0.99,
        reasoning="Spam",
        is_noise=True
    )

    summary = run_daemon_cycle(dry_run=False)
    assert summary["messages_checked"] == 1
    assert summary["noise_quarantined"] == 1
    assert mock_pm.quarantine_message.called

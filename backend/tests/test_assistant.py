import pytest
from fastapi.testclient import TestClient
from backend.main import app, CACHED_EMAILS
from backend.models import EmailMessage, EmailCategory, UserProfile
from backend.ai_agent import classify_email, generate_personalized_reply, _classify_heuristics
from backend.config import get_user_profile

client = TestClient(app)

def test_system_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"
    assert data["version"] == "1.1.0"
    assert "total_accounts" in data
    assert "connected_accounts" in data
    assert "available_resumes" in data
    assert "desktop_outlook_app" in data

def test_email_classification_resume_request():
    email = EmailMessage(
        id="test_recruiter_01",
        subject="Staff AI Engineer role at ScaleAI ($250k-$300k)",
        sender_name="Alex Recruiter",
        sender_email="alex@recruiting-talent.com",
        received_at="2026-09-10 10:00",
        preview="Hi Brian, would love to see your updated resume for an exciting role...",
        body_text="Hi Brian, We are hiring for a Staff AI Systems Engineer at ScaleAI. Could you please share your updated resume and CV? The salary is $250k-$300k.",
        folder="Inbox"
    )
    result = classify_email(email)
    assert result.is_resume_request is True
    assert result.category == EmailCategory.RESUME_REQUEST
    assert result.recruiter_details is not None
    assert "ScaleAI" in result.recruiter_details.company_name or "AI" in result.recruiter_details.role_title

def test_email_classification_promotional_noise():
    email = EmailMessage(
        id="test_promo_01",
        subject="70% OFF Cyber Monday Sale - Limited Time Offer!",
        sender_name="MegaStore Deals",
        sender_email="deals@promotions-shop.com",
        received_at="2026-09-10 09:30",
        preview="Don't miss our exclusive discounts. Buy now and save big...",
        body_text="Huge sale today only! Use promo code SAVE70 for 70% off. To unsubscribe from our marketing list, click here.",
        folder="Inbox"
    )
    result = classify_email(email)
    assert result.is_noise is True
    assert result.category == EmailCategory.NOISE_PROMOTIONAL
    assert result.suggested_action == "TRASH"

def test_email_classification_newsletter():
    email = EmailMessage(
        id="test_news_01",
        subject="The Engineering Weekly Digest #88 - LLM Architecture Deep Dive",
        sender_name="Weekly Tech Digest",
        sender_email="editor@techdigest-newsletter.com",
        received_at="2026-09-10 08:00",
        preview="In this edition of our newsletter: modern data pipelines and agentic frameworks...",
        body_text="Welcome to this week's newsletter edition #88. You received this because you subscribed. Unsubscribe anytime.",
        folder="Inbox"
    )
    result = classify_email(email)
    assert result.is_noise is True
    assert result.category in [EmailCategory.NOISE_NEWSLETTER, EmailCategory.NOISE_PROMOTIONAL]

def test_personalized_reply_generation():
    email = EmailMessage(
        id="test_rec_02",
        subject="Principal Software Architect Opportunity @ Horizon Cloud",
        sender_name="Dana Vance",
        sender_email="dana@horizon-talent.com",
        received_at="2026-09-10 11:00",
        preview="We are looking for a Principal Architect with deep Python and cloud background...",
        body_text="Hi Brian, Horizon Cloud is looking for a Principal Architect to lead distributed systems. Please send over your updated resume.",
        folder="Inbox"
    )
    email.classification = classify_email(email)
    user_profile = get_user_profile()
    reply = generate_personalized_reply(email, user_profile)
    
    assert "Dana" in reply or "Hi" in reply
    assert "resume" in reply.lower()
    assert user_profile.full_name in reply

def test_list_and_triage_endpoints():
    response = client.get("/api/emails")
    assert response.status_code == 200
    emails = response.json()
    assert isinstance(emails, list)

def test_clean_noise_batch_endpoint():
    from unittest.mock import patch, MagicMock
    with patch("backend.main.provider_manager.move_message") as mock_move:
        mock_move.return_value = MagicMock(success=True, safe_message="Moved")
        response = client.post("/api/emails/clean-noise")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["SUCCESS", "PARTIAL_SUCCESS"]
        assert "cleaned_count" in data

def test_stats_endpoint():
    response = client.get("/api/stats")
    assert response.status_code == 200
    stats = response.json()
    assert "total_emails_analyzed" in stats
    assert "noise_detected" in stats
    assert "resume_requests" in stats
    assert "time_saved_minutes" in stats

def test_user_profile_email_accounts():
    response = client.get("/api/profile")
    assert response.status_code == 200
    prof = response.json()
    assert "active_email_accounts" in prof
    assert "historical_email_accounts" in prof
    
    # Check that active accounts are configured
    expected_active = [
        "kinlawb@outlook.com",
        "brian.kinlaw@outlook.com",
        "briankkinlaw@gmail.com",
        "cbkinlaw@satx.rr.com",
        "briankinlaw@satx.rr.com",
        "brian@mavencode.com"
    ]
    for acc in expected_active:
        assert acc in prof["active_email_accounts"]
        
    # Check historical accounts
    expected_hist = ["bkinlaw@dxc.com", "brian.kinlaw@cdw.com", "briankinlaw@revealwhy.com"]
    for acc in expected_hist:
        assert acc in prof["historical_email_accounts"]
    
    # Test updating profile via endpoint
    updated_prof = prof.copy()
    updated_prof["full_name"] = "Brian K. Kinlaw"
    post_res = client.post("/api/profile", json=updated_prof)
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["status"] == "SUCCESS"
    assert len(data["profile"]["active_email_accounts"]) == 6

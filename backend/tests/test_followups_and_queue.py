"""Tests for Aura Mail AI Follow-up Scheduler, Replied Status, and Analytics DB Integration.
"""

import pytest
from datetime import datetime, date
from fastapi.testclient import TestClient

from backend.main import app, CACHED_EMAILS
from backend.models import EmailMessage, RecruiterDetails, ClassificationResult, EmailCategory, ResumeMatchResult
from backend.auth import get_auth_headers
from backend.analytics import (
    init_analytics_db,
    create_followup_task,
    list_followup_tasks,
    update_followup_task,
    delete_followup_task,
    log_event,
    get_funnel_metrics,
)

auth_client = TestClient(app)
auth_client.headers.update(get_auth_headers())
unauth_client = TestClient(app)


def test_followup_crud_analytics_db(tmp_path, monkeypatch):
    """Test SQLite CRUD operations for followup_tasks table."""
    test_db = tmp_path / "test_analytics.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    init_analytics_db()

    # Create task
    task = create_followup_task(
        opportunity_id="MICROSOFT_GRAPH::kinlawb@outlook.com::test-1",
        email_id="MICROSOFT_GRAPH::kinlawb@outlook.com::test-1",
        recruiter_name="Sarah Miller",
        company_name="Snowflake",
        role_title="Enterprise Architect",
        due_date="2026-09-25",
        notes="Sent Level 3A Advisor canonical resume"
    )
    assert task is not None
    task_id = task["id"]

    # List tasks
    tasks = list_followup_tasks(status="PENDING")
    assert len(tasks) == 1
    assert tasks[0]["recruiter_name"] == "Sarah Miller"
    assert tasks[0]["company_name"] == "Snowflake"
    assert tasks[0]["status"] == "PENDING"
    assert tasks[0]["due_date"] == "2026-09-25"

    # Update status to COMPLETED
    updated = update_followup_task(task_id, status="COMPLETED")
    assert updated is not None
    assert updated["status"] == "COMPLETED"

    # Verify status changed
    pending_tasks = list_followup_tasks(status="PENDING")
    assert len(pending_tasks) == 0

    completed_tasks = list_followup_tasks(status="COMPLETED")
    assert len(completed_tasks) == 1
    assert completed_tasks[0]["status"] == "COMPLETED"

    # Delete task
    deleted = delete_followup_task(task_id)
    assert deleted is True

    all_tasks = list_followup_tasks()
    assert len(all_tasks) == 0


def test_followup_api_endpoints_auth_enforced(tmp_path, monkeypatch):
    """Test REST API endpoints for follow-up management and auth enforcement."""
    test_db = tmp_path / "test_api_analytics.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    monkeypatch.setattr("backend.main.CACHED_EMAILS", {})
    init_analytics_db()

    # Unauthenticated request fails with 401
    unauth_res = unauth_client.get("/api/followups")
    assert unauth_res.status_code == 401

    # POST /api/followups with auth
    res = auth_client.post("/api/followups", json={
        "title": "Call recruiter back",
        "recruiter_name": "Dave Wilson",
        "company_name": "Google Cloud",
        "due_date": "2026-09-28",
        "notes": "Discuss technical advisory scope"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "task" in data
    task_id = data["task"]["id"]

    # GET /api/followups with auth
    get_res = auth_client.get("/api/followups")
    assert get_res.status_code == 200
    tasks_data = get_res.json()
    assert len(tasks_data["tasks"]) == 1
    assert tasks_data["tasks"][0]["recruiter_name"] == "Dave Wilson"

    # PATCH /api/followups/{task_id} with auth
    patch_res = auth_client.patch(f"/api/followups/{task_id}", json={
        "status": "COMPLETED"
    })
    assert patch_res.status_code == 200
    assert patch_res.json()["success"] is True

    # DELETE /api/followups/{task_id} with auth
    del_res = auth_client.delete(f"/api/followups/{task_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True


def test_orchestrate_pipeline_endpoint(tmp_path, monkeypatch):
    """Test POST /api/pipeline/orchestrate auto-syncs active recruiter emails."""
    test_db = tmp_path / "test_orch_analytics.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    init_analytics_db()

    test_email_id = "MICROSOFT_GRAPH::kinlawb@outlook.com::orch_msg_001"
    test_msg = EmailMessage(
        id=test_email_id,
        sender_name="Sarah Miller",
        sender_email="sarah@execsearch.com",
        subject="Head of Architecture Opportunity",
        body_text="Are you open to discussing this opportunity?",
        account_id="kinlawb@outlook.com",
        provider="MICROSOFT_GRAPH",
        status="INBOUND",
        classification=ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            confidence=0.98,
            reasoning="Executive recruiter outreach",
            is_noise=False,
            is_resume_request=True,
            recruiter_details=RecruiterDetails(
                recruiter_name="Sarah Miller",
                company_name="Cloud Corp",
                role_title="Head of Architecture",
                salary_range="$300k - $350k"
            )
        )
    )
    mock_cached = {test_email_id: test_msg}
    monkeypatch.setattr("backend.main.CACHED_EMAILS", mock_cached)

    res = auth_client.post("/api/pipeline/orchestrate")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["tasks_created"] == 1
    assert data["pending_tasks"] == 1

    # Verify idempotency
    res2 = auth_client.post("/api/pipeline/orchestrate")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["tasks_created"] == 0
    assert data2["total_tasks"] == 1



def test_mark_replied_api(tmp_path, monkeypatch):
    """Test /api/emails/{id}/mark-replied endpoint with auth."""
    test_db = tmp_path / "test_replied_analytics.db"
    monkeypatch.setattr("backend.analytics.DB_PATH", test_db)
    init_analytics_db()

    # Seed email into CACHED_EMAILS
    test_email_id = "MICROSOFT_GRAPH::kinlawb@outlook.com::test_msg_999"
    test_msg = EmailMessage(
        id=test_email_id,
        sender_name="Jessica Hayes",
        sender_email="jessica@techrecruiting.com",
        subject="Staff Enterprise Architect Opportunity",
        body_text="Hi Brian, are you open to discussing a Principal / Staff Cloud Architect role?",
        preview="Hi Brian...",
        account_id="kinlawb@outlook.com",
        provider="MICROSOFT_GRAPH",
        status="INBOUND",
        classification=ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            confidence=0.95,
            reasoning="Recruiter inquiry",
            is_noise=False,
            is_resume_request=True,
            recruiter_details=RecruiterDetails(
                recruiter_name="Jessica Hayes",
                company_name="Stripe",
                role_title="Staff Enterprise Architect",
                salary_range="$280k - $340k"
            )
        )
    )
    CACHED_EMAILS[test_email_id] = test_msg

    # Unauthenticated request fails
    unauth_res = unauth_client.post(f"/api/emails/{test_email_id}/mark-replied", json={"due_days": 3})
    assert unauth_res.status_code == 401

    # Authenticated call
    res = auth_client.post(f"/api/emails/{test_email_id}/mark-replied", json={
        "due_days": 3,
        "notes": "Sent custom advisory response"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] == "REPLIED"
    assert "followup" in data
    assert data["followup"]["recruiter_name"] == "Jessica Hayes"
    assert data["followup"]["company_name"] == "Stripe"

    # Verify task was created in SQLite
    tasks = list_followup_tasks()
    assert len(tasks) == 1
    assert tasks[0]["opportunity_id"] == test_email_id
    assert tasks[0]["recruiter_name"] == "Jessica Hayes"
    assert tasks[0]["status"] == "PENDING"

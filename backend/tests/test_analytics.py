import pytest
import sqlite3
import json
from pathlib import Path
from backend.analytics import (
    init_analytics_db,
    get_db_connection,
    parse_salary_values,
    record_opportunity,
    update_opportunity_stage,
    log_event,
    log_grounding_audit,
    get_kpis_summary,
    get_funnel_metrics,
    get_compensation_benchmarks,
    get_resume_roi_leaderboard,
    get_recent_audit_events,
    export_analytics_data,
)
from backend.models import RecruiterDetails, ResumeMatchResult


def test_init_analytics_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]
    conn.close()

    assert "opportunities" in tables
    assert "event_telemetry" in tables
    assert "grounding_audit" in tables
    assert "system_telemetry" in tables


def test_parse_salary_values():
    # Annual salary range with k
    res1 = parse_salary_values("$240k - $310k/year")
    assert res1["min"] == 240000.0
    assert res1["max"] == 310000.0
    assert res1["type"] == "ANNUAL"

    # Hourly rate range
    res2 = parse_salary_values("$120 - $150 / hr")
    assert res2["min"] == 120.0
    assert res2["max"] == 150.0
    assert res2["type"] == "HOURLY"

    # Single annual number with comma
    res3 = parse_salary_values("$275,000 base salary")
    assert res3["min"] == 275000.0
    assert res3["max"] == 275000.0
    assert res3["type"] == "ANNUAL"

    # None or empty string
    res4 = parse_salary_values(None)
    assert res4["min"] is None
    assert res4["type"] == "UNSPECIFIED"

    res5 = parse_salary_values("Competitive with equity")
    assert res5["min"] is None
    assert res5["type"] == "UNSPECIFIED"


def test_record_opportunity_and_lifecycle():
    recruiter_details = RecruiterDetails(
        company_name="Apex Global Advisors",
        role_title="Principal AI Solutions Architect",
        salary_range="$260,000 - $320,000",
        urgency="High",
        action_requested="SEND_RESUME"
    )
    resume_match = ResumeMatchResult(
        matching_lens="level_3a_advisor",
        lens_name="Level 3A — Advisor",
        selected_resume="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
        match_score=92,
        reasoning="Strong alignment with enterprise AI solutions architecture."
    )

    import uuid
    opp_id = f"test_opp_{uuid.uuid4().hex[:8]}"
    record_opportunity(
        email_id=opp_id,
        subject="Executive AI Architecture Lead Opportunity",
        sender_name="David Sterling",
        sender_email="david@apexadvisors.com",
        recruiter_details=recruiter_details,
        resume_match=resume_match,
        status="INBOUND"
    )

    # Verify insertion
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["company_name"] == "Apex Global Advisors"
    assert row["role_title"] == "Principal AI Solutions Architect"
    assert row["salary_min"] == 260000.0
    assert row["salary_max"] == 320000.0
    assert row["status"] == "INBOUND"
    assert row["match_score"] == 92

    # Update pipeline stage to DRAFTED, then REPLIED
    update_opportunity_stage(opp_id, "DRAFTED")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM opportunities WHERE id = ?", (opp_id,))
    assert cursor.fetchone()["status"] == "DRAFTED"
    conn.close()

    update_opportunity_stage(opp_id, "REPLIED")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM opportunities WHERE id = ?", (opp_id,))
    assert cursor.fetchone()["status"] == "REPLIED"
    conn.close()


def test_log_event_and_grounding_audit():
    log_event(
        event_type="DRAFT_GENERATED",
        opportunity_id="test_opp_analytics_001",
        lens="level_3a_advisor",
        resume_file="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
        details="Generated fact-locked reply with $8M Google Cloud ledger metric",
        ai_model="Local Heuristic & Canonical Rules Engine",
        latency_ms=145
    )

    log_grounding_audit(
        opportunity_id="test_opp_analytics_001",
        subject="Executive AI Architecture Lead Opportunity",
        company="Apex Global Advisors",
        role="Principal AI Solutions Architect",
        resume_used="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
        facts_used=["$8M Google Cloud pipeline influenced", "$100M+ enterprise platform revenue"],
        reply_text="Hello David, Thank you for reaching out..."
    )

    events = get_recent_audit_events(limit=5)
    assert len(events) > 0
    recent = events[0]
    assert "event_type" in recent
    assert "timestamp" in recent


def test_analytics_kpis_and_aggregations():
    kpis = get_kpis_summary()
    assert "total_reachouts" in kpis
    assert "active_pipeline" in kpis
    assert "drafted_in_outlook" in kpis
    assert "replied_and_sent" in kpis
    assert "time_saved_hours" in kpis
    assert kpis["total_reachouts"] >= 1

    funnel = get_funnel_metrics()
    assert len(funnel) == 5
    assert funnel[0]["stage"] == "1. Inbound Reachout"
    assert funnel[0]["count"] >= 1

    comp = get_compensation_benchmarks()
    assert "benchmarks" in comp
    assert len(comp["benchmarks"]) > 0
    assert "recent_disclosed_roles" in comp

    roi = get_resume_roi_leaderboard()
    assert isinstance(roi, list)
    if len(roi) > 0:
        assert "filename" in roi[0]
        assert "total_attached" in roi[0]


def test_export_analytics_data():
    data = export_analytics_data()
    assert data["candidate"] == "Brian K. Kinlaw"
    assert data["total_opportunities"] >= 1
    assert "opportunities" in data
    assert "events" in data
    assert "grounding_audits" in data

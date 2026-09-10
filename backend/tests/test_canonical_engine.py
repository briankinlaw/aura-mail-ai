import pytest
from pathlib import Path
from backend.canonical_engine import (
    scan_canonical_system,
    find_best_resume_match,
    resolve_resume_file,
    get_canonical_ledger_summary,
    LENS_DEFINITIONS,
    LOCKED_FACTS
)
from backend.models import EmailMessage, UserProfile
from backend.ai_agent import classify_email, generate_personalized_reply

def test_scan_canonical_system():
    catalog = scan_canonical_system(force_refresh=True)
    assert catalog["status"] == "SUCCESS"
    assert catalog["total_resumes"] > 0
    assert len(catalog["standard_canonicals"]) > 0
    assert len(catalog["targeted_customs"]) > 0
    
    # Verify standard canonical presence
    standard_names = [r["filename"] for r in catalog["standard_canonicals"]]
    assert any("Advisor" in name for name in standard_names)
    assert any("TPM" in name for name in standard_names)
    assert any("Governance" in name for name in standard_names)

def test_resolve_resume_file():
    # Test resolving standard canonical
    p1 = resolve_resume_file("Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx")
    assert p1 is not None
    assert p1.exists()

    # Test resolving targeted resume
    p2 = resolve_resume_file("Brian_Kinlaw_2026-09-09_StanleyBlackDecker_Principal_Engineering_AI_Architect_Advisor_candidate.docx")
    assert p2 is not None
    assert p2.exists()

    # Test resolving pdf variant
    p3 = resolve_resume_file("Brian 2025-12-31_Expanded_Resume.pdf")
    assert p3 is not None
    assert p3.exists()

def test_match_solutions_architect():
    match = find_best_resume_match(
        job_title="Principal Enterprise Cloud & AI Solutions Architect",
        job_description="Seeking a Principal Solutions Architect with deep pre-sales, discovery, and cloud architecture experience.",
        sender="recruiter@techsearch.com"
    )
    assert match["matching_lens"] == "level_3a_advisor"
    assert match["match_score"] >= 75
    assert "Advisor" in match["selected_resume"] or "Architect" in match["selected_resume"]

def test_match_data_governance():
    match = find_best_resume_match(
        job_title="Director of Data Governance & AI Compliance",
        job_description="Lead enterprise metadata, Collibra lineage, stewardship, and NIST AI RMF framework implementation.",
        sender="talent@fintech.com"
    )
    assert match["matching_lens"] == "level_3c_governance"
    assert match["match_score"] >= 80
    assert "Governance" in match["selected_resume"]

def test_match_field_cto():
    match = find_best_resume_match(
        job_title="Field CTO / Technology Strategist",
        job_description="Executive advisory role working with enterprise C-suite on platform strategy and digital transformation.",
        sender="exec@heidrick.com"
    )
    assert match["matching_lens"] == "field_cto"
    assert "CTO" in match["selected_resume"] or "Strategist" in match["selected_resume"] or "Advisor" in match["selected_resume"]

def test_ledger_summary_and_locked_facts():
    summary = get_canonical_ledger_summary()
    assert len(summary) > 100
    assert "Brian" in summary
    assert "8M" in LOCKED_FACTS["google"]
    assert "100M+" in LOCKED_FACTS["career_impact"]

def test_grounded_reply_generation():
    email = EmailMessage(
        id="test_rec_01",
        subject="Senior Solutions Architect Role at CloudTech",
        sender_name="Sarah Jenkins",
        sender_email="sarah.jenkins@cloudtech.com",
        received_at="2026-09-10 09:00",
        preview="We are hiring for a Principal Solutions Architect...",
        body_text="Hi Brian, We are impressed with your background and are looking for a Principal Solutions Architect to lead enterprise GCP and AI advisory. Please share your resume.",
        is_read=False
    )
    profile = UserProfile()
    reply = generate_personalized_reply(email, profile)
    
    assert "Sarah" in reply
    assert "resume" in reply.lower()
    assert "Google Cloud" in reply or "cloud" in reply.lower()
    assert "Brian K. Kinlaw" in reply

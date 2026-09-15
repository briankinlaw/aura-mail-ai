import pytest
import zipfile
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


def _create_test_docx(path: Path, headline: str, text: str) -> Path:
    """Create a minimal synthetic docx file with valid XML structure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    xml_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{headline}</w:t></w:r></w:p>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml_content)
    return path


@pytest.fixture(autouse=True)
def setup_hermetic_canonical_env(tmp_path, monkeypatch):
    """
    Sets up a fully hermetic, isolated canonical test environment with synthetic documents.
    Patches canonical engine directories and resets all module caches before and after each test.
    """
    active_dir = tmp_path / "Canonical - Active"
    targeted_dir = tmp_path / "Targeted Applications"
    variants_dir = tmp_path / "Resume Variants"
    resumes_dir = tmp_path / "resumes"

    active_dir.mkdir(parents=True, exist_ok=True)
    targeted_dir.mkdir(parents=True, exist_ok=True)
    variants_dir.mkdir(parents=True, exist_ok=True)
    resumes_dir.mkdir(parents=True, exist_ok=True)

    # Standard canonical synthetic fixtures (non-personal TEST CANDIDATE)
    _create_test_docx(
        active_dir / "Test_Candidate_Advisor_Canonical.docx",
        "SOLUTIONS ARCHITECT & ENTERPRISE ADVISOR",
        "Pre-sales discovery cloud architecture advisory enterprise solutions."
    )
    _create_test_docx(
        active_dir / "Test_Candidate_TPM_Canonical.docx",
        "PRINCIPAL TECHNICAL PROGRAM MANAGER",
        "Program manager cross-functional orchestration delivery roadmap."
    )
    _create_test_docx(
        active_dir / "Test_Candidate_Governance_Canonical.docx",
        "DIRECTOR OF DATA GOVERNANCE & AI COMPLIANCE",
        "Enterprise data governance NIST Collibra lineage metadata compliance."
    )
    _create_test_docx(
        active_dir / "Test_Candidate_Field_CTO_Canonical.docx",
        "FIELD CTO & STRATEGIST",
        "Executive advisory platform strategy C-suite transformation."
    )
    _create_test_docx(
        active_dir / "Accomplishment_Ledger_Test.docx",
        "ACCOMPLISHMENT LEDGER",
        "Accomplishment ledger summary for TEST CANDIDATE (test.candidate@example.invalid). Influenced $8M revenue. $100M+ career impact."
    )

    # Targeted custom synthetic fixture
    _create_test_docx(
        targeted_dir / "Test_Candidate_Targeted_Custom_Strategy.docx",
        "STRATEGY & NEW PRODUCTS DIRECTOR",
        "Targeted application for strategy and leadership."
    )

    # Patch canonical directory paths
    monkeypatch.setattr("backend.canonical_engine.CANONICAL_ACTIVE_DIR", active_dir)
    monkeypatch.setattr("backend.canonical_engine.TARGETED_APPS_DIR", targeted_dir)
    monkeypatch.setattr("backend.canonical_engine.DOWNLOADS_VARIANTS_DIR", variants_dir)
    monkeypatch.setattr("backend.canonical_engine.RESUMES_DIR", resumes_dir)

    # Clear caches before test
    monkeypatch.setattr("backend.canonical_engine._RESUME_CACHE", {})
    monkeypatch.setattr("backend.canonical_engine._LAST_SCAN_TIME", None)

    yield

    # Clear caches after test
    import backend.canonical_engine as ce
    ce._RESUME_CACHE = {}
    ce._LAST_SCAN_TIME = None


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
    p1 = resolve_resume_file("Test_Candidate_Advisor_Canonical.docx")
    assert p1 is not None
    assert p1.exists()

    # Test resolving targeted resume
    p2 = resolve_resume_file("Test_Candidate_Targeted_Custom_Strategy.docx")
    assert p2 is not None
    assert p2.exists()

    # Test resolving default fallback when identifier is None
    p_default = resolve_resume_file(None)
    assert p_default is not None
    assert p_default.exists()


def test_match_solutions_architect():
    match = find_best_resume_match(
        job_title="Principal Enterprise Cloud & AI Solutions Architect",
        job_description="Seeking a Principal Solutions Architect with deep pre-sales, discovery, and cloud architecture experience.",
        sender="recruiter@techsearch.com"
    )
    assert match["matching_lens"] in ["level_3a_advisor", "field_cto"]
    assert match["match_score"] >= 70
    assert any(term in match["selected_resume"] for term in ["Advisor", "Architect", "Strategist", "Canonical"])


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
    assert len(summary) > 50
    assert "Accomplishment ledger" in summary or "TEST CANDIDATE" in summary or "LOCKED_FACTS" in summary or "Influenced" in summary
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

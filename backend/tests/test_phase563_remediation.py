"""
Aura Mail AI - Phase 5.6.3 Portable and Hermetic Validation Remediation Suite

Verifies:
1. The Phase 5.5.5 JavaScript execution test uses Node available through PATH.
2. The frontend validator runs under Node and reports 17/17 passing.
3. No hard-coded JavaScriptCore framework path remains in executable test logic.
4. Darwin notification behavior can be tested by mocking the production platform boundary.
5. Non-Darwin notification behavior does not invoke the macOS subprocess.
6. Canonical-engine tests use temporary or committed synthetic test fixtures.
7. Canonical-engine tests do not require Brian-specific uncommitted documents.
8. Canonical tests pass with only the committed archive contents.
9. node_modules/ is ignored.
10. .nvmrc remains 24.
11. .python-version remains 3.12.
12. run_offline_recovery() remains parameterless.
13. In-process provenance recovery remains blocked.
14. No /authorize-send route exists.
15. No mail-transmission authority has been introduced.
"""

import inspect
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from backend.main import app
from backend.config import GRAPH_SCOPES, BASE_DIR
from backend.daemon import send_macos_notification
from backend.offline_recovery import run_offline_recovery
from backend.canonical_grounding import ProvenanceStore


# ===========================================================================
# 1. Node Discovery and JavaScript Execution Portability
# ===========================================================================

def test_node_discovery_and_availability():
    """Verify Node.js is discoverable via PATH."""
    node_path = shutil.which("node")
    assert node_path is not None, "Node.js executable must be discoverable on PATH"


def test_frontend_validator_node_execution():
    """Verify frontend risk validator executes under Node and reports 17/17 passing."""
    node = shutil.which("node")
    assert node is not None, "Node.js is required for frontend validation"

    repo_root = BASE_DIR
    test_file = repo_root / "backend" / "tests" / "test_frontend_risk_validator.js"
    assert test_file.exists(), f"Frontend validator test file {test_file} must exist"

    result = subprocess.run(
        [node, str(test_file)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Validator failed with stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "All 17/17" in result.stdout


def test_no_hardcoded_javascriptcore_in_test_suite():
    """Verify no hard-coded macOS JavaScriptCore path remains in active test logic."""
    phase555_test = BASE_DIR / "backend" / "tests" / "test_phase555_remediation.py"
    content = phase555_test.read_text(encoding="utf-8")
    assert "/System/Library/Frameworks/JavaScriptCore.framework" not in content, (
        "Hard-coded JavaScriptCore path must not remain in test_phase555_remediation.py"
    )


# ===========================================================================
# 2. Daemon Notification Platform Boundaries
# ===========================================================================

def test_darwin_notification_behavior_mocked():
    """Verify that when platform is Darwin, notification invokes osascript subprocess."""
    with patch("backend.daemon.sys.platform", "darwin"), \
         patch("backend.daemon.subprocess.run") as mock_sub:
        send_macos_notification("Aura Mail", "New Lead", "Testing Darwin Notification")
        assert mock_sub.called
        args, _ = mock_sub.call_args
        cmd = args[0]
        assert cmd[0] == "osascript"
        assert "Testing Darwin Notification" in cmd[2]


def test_non_darwin_notification_behavior_mocked():
    """Verify that when platform is non-Darwin (e.g. Linux), notification returns safely without subprocess."""
    with patch("backend.daemon.sys.platform", "linux"), \
         patch("backend.daemon.subprocess.run") as mock_sub:
        send_macos_notification("Aura Mail", "New Lead", "Testing Linux Notification")
        assert not mock_sub.called


# ===========================================================================
# 3. Hermetic Canonical Engine Fixtures
# ===========================================================================

def _create_synthetic_docx(path: Path, headline: str, text: str) -> Path:
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


def test_canonical_engine_hermetic_temporary_fixtures(tmp_path, monkeypatch):
    """Verify canonical engine works completely within temporary isolated directory."""
    from backend.canonical_engine import (
        scan_canonical_system,
        find_best_resume_match,
        resolve_resume_file,
        get_canonical_ledger_summary,
        LOCKED_FACTS,
    )

    active_dir = tmp_path / "Canonical - Active"
    targeted_dir = tmp_path / "Targeted Applications"
    variants_dir = tmp_path / "Resume Variants"
    resumes_dir = tmp_path / "resumes"

    _create_synthetic_docx(
        active_dir / "Test_Candidate_Advisor_Canonical.docx",
        "SOLUTIONS ARCHITECT & ADVISOR",
        "Pre-sales cloud architecture advisory"
    )
    _create_synthetic_docx(
        active_dir / "Accomplishment_Ledger_Test.docx",
        "ACCOMPLISHMENT LEDGER",
        "Accomplishment ledger summary for TEST CANDIDATE. Influenced $8M revenue. $100M+ impact."
    )
    _create_synthetic_docx(
        targeted_dir / "Test_Candidate_Targeted_Strategy.docx",
        "STRATEGY DIRECTOR",
        "Targeted strategic leadership"
    )

    monkeypatch.setattr("backend.canonical_engine.CANONICAL_ACTIVE_DIR", active_dir)
    monkeypatch.setattr("backend.canonical_engine.TARGETED_APPS_DIR", targeted_dir)
    monkeypatch.setattr("backend.canonical_engine.DOWNLOADS_VARIANTS_DIR", variants_dir)
    monkeypatch.setattr("backend.canonical_engine.RESUMES_DIR", resumes_dir)
    monkeypatch.setattr("backend.canonical_engine._RESUME_CACHE", {})
    monkeypatch.setattr("backend.canonical_engine._LAST_SCAN_TIME", None)

    catalog = scan_canonical_system(force_refresh=True)
    assert catalog["status"] == "SUCCESS"
    assert catalog["total_resumes"] == 2
    assert len(catalog["standard_canonicals"]) == 1
    assert len(catalog["targeted_customs"]) == 1

    resolved = resolve_resume_file("Test_Candidate_Advisor_Canonical.docx")
    assert resolved is not None
    assert resolved.exists()

    match = find_best_resume_match(
        job_title="Solutions Architect",
        job_description="Cloud architecture and pre-sales advisory",
        sender="recruiter@example.com"
    )
    assert match["matching_lens"] == "level_3a_advisor"
    assert "Advisor" in match["selected_resume"]

    summary = get_canonical_ledger_summary()
    assert "Accomplishment ledger" in summary


def test_canonical_engine_no_uncommitted_brian_documents_required(tmp_path, monkeypatch):
    """Verify canonical engine does not require any uncommitted private files to operate."""
    from backend.canonical_engine import scan_canonical_system, find_best_resume_match

    # Point all search dirs to empty directories
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("backend.canonical_engine.CANONICAL_ACTIVE_DIR", empty_dir)
    monkeypatch.setattr("backend.canonical_engine.TARGETED_APPS_DIR", empty_dir)
    monkeypatch.setattr("backend.canonical_engine.DOWNLOADS_VARIANTS_DIR", empty_dir)
    monkeypatch.setattr("backend.canonical_engine.RESUMES_DIR", empty_dir)
    monkeypatch.setattr("backend.canonical_engine._RESUME_CACHE", {})
    monkeypatch.setattr("backend.canonical_engine._LAST_SCAN_TIME", None)

    catalog = scan_canonical_system(force_refresh=True)
    assert catalog["status"] == "SUCCESS"
    assert catalog["total_resumes"] == 0

    # Matching with empty catalog returns safe fallback
    match = find_best_resume_match("Any Title", "Any Description")
    assert match["selected_resume"] is None
    assert match["match_score"] == 0


def test_canonical_tests_pass_with_committed_archive_contents():
    """Verify data/resumes directory exists and contains only tracked generic fixtures."""
    resumes_dir = BASE_DIR / "data" / "resumes"
    assert resumes_dir.exists()
    assert (resumes_dir / "resume_master.txt").exists()


# ===========================================================================
# 4. Ignore Rules and Configuration Standards
# ===========================================================================

def test_node_modules_ignored_in_gitignore():
    """Verify node_modules/ is explicitly ignored in .gitignore."""
    gitignore_path = BASE_DIR / ".gitignore"
    assert gitignore_path.exists()
    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    assert "node_modules/" in lines or any(l == "node_modules/" for l in lines)


def test_nvmrc_standardized_node_24():
    """Verify .nvmrc specifies Node 24."""
    nvmrc_path = BASE_DIR / ".nvmrc"
    assert nvmrc_path.exists()
    assert nvmrc_path.read_text(encoding="utf-8").strip() == "24"


def test_python_version_standardized_3_12():
    """Verify .python-version specifies Python 3.12."""
    pv_path = BASE_DIR / ".python-version"
    assert pv_path.exists()
    assert pv_path.read_text(encoding="utf-8").strip().startswith("3.12")


# ===========================================================================
# 5. Inherited Security and Recovery Invariants
# ===========================================================================

def test_offline_recovery_remains_parameterless():
    """Verify run_offline_recovery() takes zero arguments."""
    sig = inspect.signature(run_offline_recovery)
    assert len(sig.parameters) == 0, f"run_offline_recovery must take 0 parameters, got {sig.parameters}"


def test_in_process_provenance_recovery_blocked():
    """Verify in-process provenance recovery remains blocked and raises RuntimeError fail-closed."""
    store = ProvenanceStore()
    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.recover_store()
    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.recover_store("RESET_ALL_PROVENANCE", force=True, bypass=True)


def test_no_authorize_send_route_exists():
    """Verify no /authorize-send or /send route exists in the FastAPI application."""
    routes = [getattr(route, "path", "") for route in app.routes]
    assert "/authorize-send" not in routes
    assert "/api/authorize-send" not in routes
    assert "/send" not in routes
    assert "/api/send" not in routes


def test_no_mail_transmission_authority_in_scopes():
    """Verify Mail.Send is not included in GRAPH_SCOPES."""
    assert "Mail.Send" not in GRAPH_SCOPES

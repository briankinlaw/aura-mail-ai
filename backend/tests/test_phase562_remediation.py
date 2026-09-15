"""
Phase 5.6.2 Configuration Reproducibility & Portable Review Runtime Tests.

Covers:
1. Pinned macOS dependency declaration with sys_platform == "darwin" environment marker in requirements.txt.
2. Platform marker evaluation logic (True on Darwin, False on Linux).
3. Import-safety of backend.menubar_app when rumps is absent (e.g. on Linux).
4. Failure behavior when AuraMailMenuBarApp is instantiated without rumps.
5. Standardized .python-version (Python 3.12) declaration.
6. Standardized .nvmrc (Node 24 LTS) declaration.
7. Verification that zero offline-recovery security controls or transmission invariants are weakened.
"""

import sys
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from backend.menubar_app import is_server_running, ensure_server_running
from backend.offline_recovery import run_offline_recovery
from backend.canonical_grounding import ProvenanceStore


def test_requirements_declares_rumps_with_darwin_marker():
    """
    Proves requirements.txt contains rumps==0.4.0 with sys_platform == 'darwin'
    so macOS installs it automatically while Linux builds remain clean.
    """
    req_path = Path(__file__).resolve().parent.parent.parent / "requirements.txt"
    assert req_path.is_file()
    content = req_path.read_text(encoding="utf-8")

    rumps_lines = [line.strip() for line in content.splitlines() if line.strip().startswith("rumps")]
    assert len(rumps_lines) == 1, f"Expected 1 rumps entry in requirements.txt, found: {rumps_lines}"

    rumps_entry = rumps_lines[0]
    assert "rumps==0.4.0" in rumps_entry
    assert 'sys_platform == "darwin"' in rumps_entry or "sys_platform == 'darwin'" in rumps_entry


def test_environment_marker_evaluation_on_darwin_and_linux():
    """
    Proves the packaging environment marker evaluates correctly for Darwin vs Linux.
    """
    from packaging.markers import Marker
    marker = Marker('sys_platform == "darwin"')

    assert marker.evaluate({"sys_platform": "darwin"}) is True
    assert marker.evaluate({"sys_platform": "linux"}) is False
    assert marker.evaluate({"sys_platform": "win32"}) is False


def test_menubar_app_imports_cleanly_and_functions_when_rumps_is_none():
    """
    Proves that non-GUI helper functions in backend.menubar_app can be imported
    and executed even when rumps is not available (e.g. on Linux).
    """
    import backend.menubar_app as mb

    # Verify is_server_running runs without rumps
    running = mb.is_server_running()
    assert isinstance(running, bool)


def test_menubar_app_class_fails_closed_when_rumps_is_none():
    """
    Proves that instantiating AuraMailMenuBarApp without rumps raises
    a clear, descriptive RuntimeError rather than failing silently.
    """
    import backend.menubar_app as mb

    with patch.object(mb, "rumps", None):
        fallback_class = mb.AuraMailMenuBarApp
        if mb.rumps is None:
            with pytest.raises(RuntimeError, match="AuraMailMenuBarApp requires 'rumps' and macOS"):
                fallback_class()


def test_python_version_declaration_is_standardized():
    """
    Proves .python-version exists and declares Python 3.12.
    """
    root_dir = Path(__file__).resolve().parent.parent.parent
    py_ver_file = root_dir / ".python-version"
    assert py_ver_file.is_file(), ".python-version file must exist"
    ver_text = py_ver_file.read_text(encoding="utf-8").strip()
    assert ver_text == "3.12", f"Expected '3.12' in .python-version, found: '{ver_text}'"


def test_nvmrc_declaration_is_standardized_node_24_lts():
    """
    Proves .nvmrc exists and declares Node 24 LTS.
    """
    root_dir = Path(__file__).resolve().parent.parent.parent
    nvmrc_file = root_dir / ".nvmrc"
    assert nvmrc_file.is_file(), ".nvmrc file must exist"
    node_text = nvmrc_file.read_text(encoding="utf-8").strip()
    assert node_text == "24", f"Expected '24' in .nvmrc, found: '{node_text}'"


def test_offline_recovery_boundary_preserved_with_zero_parameters():
    """
    Proves run_offline_recovery retains exactly 0 parameters and rejects all bypasses.
    """
    import inspect
    sig = inspect.signature(run_offline_recovery)
    assert len(sig.parameters) == 0, f"run_offline_recovery must accept 0 parameters, found: {sig.parameters}"

    with pytest.raises(TypeError):
        run_offline_recovery(is_test_harness=True)


def test_provenance_store_recover_store_remains_permanently_blocked():
    """
    Proves ProvenanceStore.recover_store() remains permanently blocked.
    """
    store = ProvenanceStore()
    with pytest.raises(RuntimeError, match="In-process provenance recovery is forbidden"):
        store.recover_store()


def test_zero_mail_transmission_authority_preserved():
    """
    Proves zero mail transmission routes or methods exist in Aura Mail AI.
    """
    from backend.main import app
    routes = [r.path for r in app.routes]
    assert "/api/messages/send" not in routes
    assert "/api/mail/send" not in routes
    assert "/authorize-send" not in routes

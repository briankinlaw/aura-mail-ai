"""
Unit Tests for macOS Menu Bar Companion
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
import pytest

if sys.platform != "darwin":
    pytest.skip("macOS menubar companion tests require macOS (darwin)", allow_module_level=True)

try:
    import rumps
except ImportError:
    pytest.skip("macOS menubar companion tests require 'rumps' dependency", allow_module_level=True)

from backend.menubar_app import AuraMailMenuBarApp, is_server_running

class TestMenuBarApp(unittest.TestCase):
    def test_menubar_initialization(self):
        app = AuraMailMenuBarApp()
        self.assertIn("Aura", app.title)
        self.assertIn("📅 Copy Available Booking Slots (CST)", app.menu)
        self.assertIn("📂 Open Canonical Career Vault", app.menu)
        self.assertIn("⚡ Run Triage Scan Now", app.menu)
        self.assertIn("🌐 Open Web Cockpit (https://localhost:8000)", app.menu)

    @patch("backend.menubar_app.copy_to_clipboard")
    @patch("backend.menubar_app.rumps.notification")
    def test_copy_booking_slots(self, mock_notify, mock_clip):
        app = AuraMailMenuBarApp()
        app.on_copy_booking_slots(None)
        args, kwargs = mock_clip.call_args
        self.assertIn("proposed times", args[0])
        self.assertIn("pending calendar verification", args[0])

if __name__ == "__main__":
    unittest.main()

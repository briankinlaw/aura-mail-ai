"""
Unit Tests for macOS Menu Bar Companion
"""

import unittest
from unittest.mock import patch, MagicMock
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
        self.assertTrue(mock_clip.called)
        args, kwargs = mock_clip.call_args
        self.assertIn("Here are a few times", args[0])

if __name__ == "__main__":
    unittest.main()

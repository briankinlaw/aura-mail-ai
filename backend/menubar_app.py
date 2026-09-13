"""
Aura Mail AI - macOS Menu Bar Companion (Tray App)
Provides at-a-glance opportunity radar, 1-click calendar slot copying, background scan triggers,
and seamless dashboard management directly from the macOS status bar.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
import subprocess
import threading
import webbrowser
from pathlib import Path
# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import rumps

from backend.config import DATA_DIR, load_settings, get_user_profile

from backend.daemon import (
    STATE_FILE,
    PROCESSED_LOG_FILE,
    run_daemon_cycle,
    send_macos_notification
)
from backend.calendar_broker.models import FreeBusyRequest
from backend.calendar_broker.availability_service import calculate_optimal_booking_windows
from backend.daemon_cli import install_launchd, uninstall_launchd, PLIST_LABEL

SERVER_PROCESS = None

def copy_to_clipboard(text: str):
    """Copies text to the macOS system clipboard using pbcopy."""
    try:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(text.encode("utf-8"))
    except Exception as e:
        print(f"Clipboard error: {e}")

def is_server_running() -> bool:
    """Checks if localhost:8000 is accepting connections."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 8000))
        s.close()
        return True
    except Exception:
        return False

def ensure_server_running():
    """Starts the FastAPI uvicorn server in a background subprocess if not running."""
    global SERVER_PROCESS
    if is_server_running():
        return
    
    root_dir = str(Path(__file__).resolve().parent.parent)
    python_bin = sys.executable
    cmd = [python_bin, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"]
    SERVER_PROCESS = subprocess.Popen(
        cmd,
        cwd=root_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1.0)

class AuraMailMenuBarApp(rumps.App):
    def __init__(self):
        super(AuraMailMenuBarApp, self).__init__("✉️ Aura", quit_button=None)
        self.menu = [
            rumps.MenuItem("Aura Mail AI (Executive Radar)", callback=None),
            None,  # Separator
            rumps.MenuItem("🎯 Active Recruiter Opportunities", callback=None),
            None,
            rumps.MenuItem("📅 Copy Available Booking Slots (CST)", callback=self.on_copy_booking_slots),
            rumps.MenuItem("📂 Open Canonical Career Vault", callback=self.on_open_canonical_vault),
            None,
            rumps.MenuItem("⚡ Run Triage Scan Now", callback=self.on_run_scan_now),
            rumps.MenuItem("🌐 Open Web Cockpit (localhost:8000)", callback=self.on_open_cockpit),
            rumps.MenuItem("⚙️ Background Daemon Service", callback=self.on_toggle_daemon),
            None,
            rumps.MenuItem("🚪 Quit Aura Companion", callback=self.on_quit)
        ]
        self.refresh_timer = rumps.Timer(self.on_tick, 30)
        self.refresh_timer.start()
        self.update_menu_state()

    def update_menu_state(self):
        """Refreshes status bar title and dynamic submenus based on daemon telemetry."""
        state = {}
        if STATE_FILE.is_file():
            try:
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
            except Exception:
                pass

        summary = state.get("last_summary", {})
        opps = summary.get("high_fit_opportunities", [])
        staged_count = summary.get("drafts_staged", len(opps))

        # Update Status Bar Title
        if staged_count > 0:
            self.title = f"⚡ Aura ({staged_count} Leads)"
        else:
            self.title = "✉️ Aura"

        # Update Opportunities Menu Item
        opp_menu = self.menu["🎯 Active Recruiter Opportunities"]
        if getattr(opp_menu, "_menu", None) is not None:
            opp_menu.clear()

        if opps:
            for opp in opps[:4]:
                role = opp.get("role_title", "Leadership Opportunity")
                fit = opp.get("fit_score", 75)
                resume = opp.get("attached_resume", "Advisor_Canonical.docx")
                sender = opp.get("sender", "Recruiter")
                
                item_label = f"🎯 {sender}: {role[:32]} ({fit}% Fit)"
                lead_item = rumps.MenuItem(item_label, callback=None)
                lead_item.add(rumps.MenuItem(f"📄 Resume: {resume}", callback=None))
                lead_item.add(rumps.MenuItem("🚀 Open in Microsoft Outlook", callback=self.on_open_outlook))
                opp_menu.add(lead_item)
        else:
            opp_menu.add(rumps.MenuItem("No pending leads — Inboxes clean", callback=None))


        # Update Daemon Menu Status
        launchctl_res = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        is_daemon_active = PLIST_LABEL in launchctl_res.stdout
        daemon_item = self.menu["⚙️ Background Daemon Service"]
        daemon_item.title = f"⚙️ Daemon: {'🟢 ACTIVE (Every 30m)' if is_daemon_active else '⚪ INACTIVE (Click to Start)'}"

    def on_tick(self, sender):
        """Periodic background refresh."""
        self.update_menu_state()

    def on_copy_booking_slots(self, sender):
        """Calculates optimal booking windows and copies them to clipboard."""
        now = datetime.now()
        start_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=5)).strftime("%Y-%m-%d")

        req = FreeBusyRequest(
            start_date=start_date,
            end_date=end_date,
            timezone="America/Chicago",
            meeting_duration_minutes=30,
            buffer_minutes=15
        )
        res = calculate_optimal_booking_windows([], req)
        formatted = res.formatted_summary
        copy_to_clipboard(formatted)

        rumps.notification(
            title="📅 Aura Mail AI",
            subtitle="Booking Slots Copied to Clipboard",
            message="Optimal windows for next week copied (ready to paste in LinkedIn/Slack)."
        )

    def on_open_canonical_vault(self, sender):
        """Opens the Canonical Career System active documents in macOS Finder."""
        vault_path = Path("/Users/briankinlaw/CCS-v211-upload/Canonical – Active")
        if vault_path.exists():
            subprocess.run(["open", str(vault_path)], check=False)
        else:
            subprocess.run(["open", "/Users/briankinlaw/CCS-v211-upload"], check=False)

    def on_run_scan_now(self, sender):
        """Runs an immediate triage scan cycle in a background thread."""
        def _scan():
            rumps.notification("⚡ Aura Mail", "Triage Scan Started", "Scanning configured mailboxes...")
            summary = run_daemon_cycle(dry_run=False)
            self.update_menu_state()
            rumps.notification(
                "✅ Aura Mail",
                "Triage Scan Complete",
                f"Checked {summary['messages_checked']} emails. Staged {summary['drafts_staged']} drafts."
            )

        t = threading.Thread(target=_scan, daemon=True)
        t.start()

    def on_open_cockpit(self, sender):
        """Launches the web cockpit in the default browser."""
        ensure_server_running()
        webbrowser.open("http://localhost:8000")

    def on_open_outlook(self, sender):
        """Opens Microsoft Outlook on macOS."""
        subprocess.run(["open", "-a", "Microsoft Outlook"], check=False)

    def on_toggle_daemon(self, sender):
        """Toggles the macOS background launchd service on/off."""
        launchctl_res = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        if PLIST_LABEL in launchctl_res.stdout:
            uninstall_launchd()
            rumps.notification("⚙️ Aura Daemon", "Service Stopped", "Background triage LaunchAgent uninstalled.")
        else:
            install_launchd(interval_seconds=1800)
            rumps.notification("⚙️ Aura Daemon", "Service Active", "Autonomous triage active (every 30m).")
        self.update_menu_state()

    def on_quit(self, sender):
        """Gracefully quits the menu bar application."""
        rumps.quit_application()

def main():
    app = AuraMailMenuBarApp()
    app.run()

if __name__ == "__main__":
    main()

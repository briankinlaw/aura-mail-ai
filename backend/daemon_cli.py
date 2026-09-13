"""
Aura Mail AI Daemon CLI & Service Manager
Handles execution loops, manual scan triggers, and macOS LaunchAgent plist registration.
"""

import os
import sys
import time
import json
import argparse
import subprocess
import logging
from pathlib import Path

from backend.daemon import (
    run_daemon_cycle,
    send_macos_notification,
    STATE_FILE,
    PROCESSED_LOG_FILE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("aura_daemon_cli")

PLIST_LABEL = "com.briankinlaw.aura-mail-daemon"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{PLIST_LABEL}.plist"

def generate_launchd_plist(interval_seconds: int = 1800) -> str:
    """Generates a native macOS LaunchAgent XML plist."""
    python_bin = sys.executable
    script_path = str(Path(__file__).resolve().parent.parent / "aura-daemon")
    working_dir = str(Path(__file__).resolve().parent.parent)
    log_out = str(Path.home() / "Library" / "Logs" / "aura-mail-daemon.log")
    log_err = str(Path.home() / "Library" / "Logs" / "aura-mail-daemon.err")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{script_path}</string>
        <string>--once</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_out}</string>
    <key>StandardErrorPath</key>
    <string>{log_err}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{working_dir}</string>
    </dict>
</dict>
</plist>
"""

def install_launchd(interval_seconds: int = 1800):
    """Installs and loads the macOS LaunchAgent plist."""
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plist_content = generate_launchd_plist(interval_seconds)

    # Unload existing if loaded
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], stderr=subprocess.DEVNULL, check=False)

    with open(PLIST_PATH, "w", encoding="utf-8") as f:
        f.write(plist_content)

    res = subprocess.run(["launchctl", "load", str(PLIST_PATH)], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"✅ Successfully installed & loaded LaunchAgent: {PLIST_PATH}")
        print(f"   • Scan Interval: Every {interval_seconds // 60} minutes")
        print(f"   • Standard Log : ~/Library/Logs/aura-mail-daemon.log")
        send_macos_notification(
            "✉️ Aura Mail AI Daemon",
            "Background Service Active",
            f"Autonomous triage is now active (every {interval_seconds // 60}m)."
        )
    else:
        print(f"❌ Failed to load LaunchAgent: {res.stderr}")

def uninstall_launchd():
    """Unloads and removes the LaunchAgent plist."""
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.unlink()
        print(f"✅ Successfully uninstalled LaunchAgent: {PLIST_PATH}")
        send_macos_notification(
            "✉️ Aura Mail AI Daemon",
            "Background Service Stopped",
            "Autonomous background triage has been uninstalled."
        )
    else:
        print("ℹ️ LaunchAgent is not currently installed.")

def print_status():
    """Displays current daemon service status and latest triage telemetry."""
    print("=== Aura Mail AI Background Daemon Status ===")
    
    # Check launchctl status
    launchctl_res = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    is_running = PLIST_LABEL in launchctl_res.stdout
    print(f"• LaunchAgent Service : {'🟢 ACTIVE (Loaded in launchd)' if is_running else '⚪ INACTIVE / NOT LOADED'}")
    print(f"• Plist File Location : {PLIST_PATH} (Exists: {PLIST_PATH.exists()})")

    if STATE_FILE.is_file():
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            print(f"• Daemon State        : {state.get('status', 'UNKNOWN')}")
            print(f"• Last Heartbeat      : {state.get('last_heartbeat', 'N/A')}")
            summary = state.get("last_summary", {})
            if summary:
                print(f"• Last Cycle Telemetry:")
                print(f"    - Messages Checked : {summary.get('messages_checked', 0)}")
                print(f"    - Drafts Staged    : {summary.get('drafts_staged', 0)}")
                print(f"    - Noise Skipped    : {summary.get('noise_skipped', 0)}")
                opps = summary.get("high_fit_opportunities", [])
                if opps:
                    print(f"    - Recent Opportunities Staged:")
                    for opp in opps:
                        print(f"        * {opp.get('role_title')} ({opp.get('fit_score')}% Fit) -> Resume: {opp.get('attached_resume')}")
        except Exception as e:
            print(f"• State File Error    : {e}")
    else:
        print("• Daemon State        : No previous cycle records found.")

def main():
    parser = argparse.ArgumentParser(description="Aura Mail AI Background Daemon")
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle and exit")
    parser.add_argument("--loop", action="store_true", help="Run continuously in a loop")
    parser.add_argument("--interval", type=int, default=1800, help="Scan interval in seconds (default: 1800s / 30m)")
    parser.add_argument("--dry-run", action="store_true", help="Run triage and generate drafts locally without cloud staging")
    parser.add_argument("--install-launchd", action="store_true", help="Install and start macOS background LaunchAgent")
    parser.add_argument("--uninstall-launchd", action="store_true", help="Stop and remove macOS background LaunchAgent")
    parser.add_argument("--status", action="store_true", help="Display daemon status and metrics")
    parser.add_argument("--notify-test", action="store_true", help="Test native macOS desktop notification")

    args = parser.parse_args()

    if args.install_launchd:
        install_launchd(args.interval)
        return

    if args.uninstall_launchd:
        uninstall_launchd()
        return

    if args.status:
        print_status()
        return

    if args.notify_test:
        send_macos_notification(
            "✉️ Aura Mail AI: Test Alert",
            "Opportunity Radar Active",
            "This is a test notification confirming macOS desktop alerts are operational."
        )
        print("✅ Dispatched test notification to macOS Notification Center.")
        return

    if args.once:
        summary = run_daemon_cycle(dry_run=args.dry_run)
        print("\n=== Daemon Cycle Complete ===")
        print(json.dumps(summary, indent=2))
        return

    if args.loop:
        print(f"🚀 Starting Aura Mail Daemon loop (interval: {args.interval}s, dry_run: {args.dry_run})...")
        try:
            while True:
                summary = run_daemon_cycle(dry_run=args.dry_run)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checked: {summary['messages_checked']}, Staged: {summary['drafts_staged']}, Noise: {summary['noise_skipped']}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n🛑 Daemon stopped by user.")
        return

    parser.print_help()

if __name__ == "__main__":
    main()

"""Aura Mail AI - Optional macOS Desktop Convenience Helper.

Provides optional local helpers (e.g. checking if Microsoft Outlook desktop app is open).
Decoupled completely from cloud synchronization and authentication.
"""

import subprocess
import logging
from typing import Dict, Any

logger = logging.getLogger("desktop_helper")

def is_outlook_desktop_running() -> bool:
    """Checks if Microsoft Outlook process is running locally on macOS."""
    try:
        res = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Microsoft Outlook"'],
            capture_output=True, text=True, timeout=3
        )
        return "true" in res.stdout.lower()
    except Exception:
        return False

def get_desktop_app_status() -> Dict[str, Any]:
    """Returns local desktop application status without affecting cloud connectivity status."""
    is_running = is_outlook_desktop_running()
    return {
        "app_name": "Microsoft Outlook for Mac",
        "is_running": is_running,
        "note": "Desktop status is advisory only. Cloud synchronization operates independently."
    }

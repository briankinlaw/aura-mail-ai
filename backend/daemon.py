"""
Aura Mail AI - Autonomous Background Daemon
Silently monitors connected email accounts, runs Opportunity Radar fit scoring, queries the Calendar Broker,
stages executive drafts directly in cloud Drafts folders, and triggers macOS desktop notifications.
"""

import os
import sys
import json
import time
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta


from backend.config import DATA_DIR, get_user_profile, load_settings
from backend.runtime_lock import acquire_shared_runtime_lock
from backend.models import EmailMessage, EmailCategory, UserProfile, ReplyDraftRequest
from backend.provider_manager import ProviderManager
from backend.radar.triage_service import classify_email_radar, calculate_opportunity_fit_score
from backend.radar.scribe_service import generate_executive_reply
from backend.calendar_broker.models import TimeSlot, FreeBusyRequest
from backend.calendar_broker.availability_service import calculate_optimal_booking_windows
from backend.canonical_engine import find_best_resume_match

logger = logging.getLogger("aura_daemon")

PROCESSED_LOG_FILE = DATA_DIR / "daemon_processed.json"
STATE_FILE = DATA_DIR / "daemon_state.json"

def load_processed_ids() -> set:
    """Loads set of previously processed message IDs to guarantee idempotency."""
    if PROCESSED_LOG_FILE.is_file():
        try:
            with open(PROCESSED_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("processed_message_ids", []))
        except Exception as e:
            logger.warning(f"Error loading processed IDs: {e}")
    return set()

def save_processed_id(message_id: str, details: Dict[str, Any]):
    """Records message ID and triage metadata to prevent duplicate draft staging."""
    processed_ids = load_processed_ids()
    processed_ids.add(message_id)
    
    records = []
    if PROCESSED_LOG_FILE.is_file():
        try:
            with open(PROCESSED_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                records = data.get("records", [])
        except Exception:
            records = []

    records.append({
        "message_id": message_id,
        "processed_at": datetime.utcnow().isoformat(),
        "details": details
    })

    # Keep last 500 records
    records = records[-500:]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "processed_message_ids": list(processed_ids),
            "records": records,
            "last_updated": datetime.utcnow().isoformat()
        }, f, indent=2)

def update_daemon_state(status: str, last_summary: Optional[Dict[str, Any]] = None):
    """Saves daemon heartbeat and last execution metrics for the dashboard & CLI."""
    state = {
        "status": status,
        "last_heartbeat": datetime.utcnow().isoformat(),
        "last_summary": last_summary or {}
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def send_macos_notification(title: str, subtitle: str, message: str):
    """Dispatches a native macOS desktop banner using osascript."""
    if sys.platform != "darwin":
        logger.info(f"Notification [{title}]: {message}")
        return

    try:
        # Sanitize quotes for AppleScript
        safe_title = title.replace('"', '\\"')
        safe_subtitle = subtitle.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        
        script = f'display notification "{safe_msg}" with title "{safe_title}" subtitle "{safe_subtitle}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.warning(f"Failed to dispatch macOS notification: {e}")

def run_daemon_cycle(dry_run: bool = False, target_folders: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Executes a single autonomous triage cycle across all configured provider accounts:
    1. Fetches unread messages.
    2. Runs Opportunity Radar classification & fit scoring.
    3. Integrates Calendar Broker availability if scheduling is requested.
    4. Stages grounded executive response drafts in cloud Drafts folders.
    5. Automatically relocates noise emails to cloud safe folder if auto-quarantine is active.
    6. Dispatches macOS desktop alerts for high-fit roles.
    """
    logger.info(f"Starting Aura Daemon cycle (dry_run={dry_run})...")
    lock_ctx = acquire_shared_runtime_lock()
    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "dry_run": dry_run,
        "accounts_scanned": 0,
        "messages_checked": 0,
        "drafts_staged": 0,
        "noise_skipped": 0,
        "noise_quarantined": 0,
        "high_fit_opportunities": [],
        "errors": []
    }

    try:
        folders = target_folders or ["Inbox", "Jobs", "CCK Career", "AI Reachouts"]
        processed_ids = load_processed_ids()
        manager = ProviderManager()
        profile = get_user_profile()
        settings = load_settings()
        auto_quarantine = settings.get("auto_quarantine_noise", True)
        safe_folder = settings.get("safe_folder_name", "AI Cleaned - Noise")

        # Fetch emails from all configured provider accounts
        emails, sync_stats = manager.sync_unified_inbox(limit_per_account=50)
        summary["messages_checked"] = len(emails)
        summary["accounts_scanned"] = sync_stats.get("accounts_synced", 0)

        for email in emails:
            # Skip if already processed in previous cycles
            if email.id in processed_ids:
                continue

            # Run Opportunity Radar classification
            classification = classify_email_radar(email)
            email.classification = classification

            if classification.is_noise:
                quarantine_action = "SKIPPED_NOISE"
                if auto_quarantine and not dry_run:
                    q_res = manager.quarantine_message(email.id, folder_name=safe_folder)
                    if q_res.success:
                        summary["noise_quarantined"] += 1
                        quarantine_action = "QUARANTINED_NOISE"
                    else:
                        summary["errors"].append(f"Failed to auto-quarantine {email.id}: {q_res.safe_message}")
                else:
                    summary["noise_skipped"] += 1

                save_processed_id(email.id, {
                    "category": classification.category.value,
                    "action": quarantine_action,
                    "subject": email.subject
                })
                continue

            # Evaluate opportunity fit
            rec_details = classification.recruiter_details
            role_title = rec_details.role_title if rec_details else (email.subject or "Solutions Leadership Role")
            skills = rec_details.required_skills if rec_details else []
            
            fit_data = calculate_opportunity_fit_score(
                role_title=role_title,
                body_text=email.body_text,
                required_skills=skills
            )

            is_opportunity = (
                classification.is_resume_request or 
                fit_data["fit_score"] >= 60 or 
                classification.category == EmailCategory.RESUME_REQUEST
            )

            if is_opportunity:
                # Determine attached resume
                match_res = find_best_resume_match(
                    job_title=role_title,
                    job_description=email.body_text,
                    sender=email.sender_email
                )
                selected_resume = match_res.get("selected_resume") or profile.active_resume_file

                # Generate grounded executive reply
                draft_request = ReplyDraftRequest(
                    tone="Professional & Strategic",
                    custom_instructions=profile.custom_reply_instructions,
                    selected_resume=selected_resume
                )
                reply_body = generate_executive_reply(email, profile, draft_request)

                # Check if meeting / availability is requested
                body_lower = (email.body_text or "").lower()
                meeting_keywords = ["availability", "time to chat", "quick call", "are you free", "schedule a call", "speak this week"]
                if any(kw in body_lower for kw in meeting_keywords):
                    # Propose optimal booking slots for the coming week
                    now = datetime.now()
                    start_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                    end_date = (now + timedelta(days=5)).strftime("%Y-%m-%d")

                    
                    cal_req = FreeBusyRequest(
                        start_date=start_date,
                        end_date=end_date,
                        timezone="America/Chicago",
                        meeting_duration_minutes=30,
                        buffer_minutes=15
                    )
                    cal_res = calculate_optimal_booking_windows([], cal_req)
                    if cal_res.available_windows:
                        if cal_res.is_verified:
                            header = "\nI am currently available during the following windows (CST):"
                        else:
                            header = "\nI can propose the following windows (pending calendar verification, CST):"
                        slot_lines = [header]
                        for win in cal_res.available_windows[:3]:
                            slot_lines.append(f"• {win.formatted_display}")
                        slot_lines.append("Please feel free to suggest an alternative or send across a calendar invite.")
                        
                        # Insert before signature
                        if "\n\nBest regards," in reply_body:
                            parts = reply_body.split("\n\nBest regards,", 1)
                            reply_body = parts[0] + "\n" + "\n".join(slot_lines) + "\n\nBest regards," + parts[1]
                        else:
                            reply_body += "\n" + "\n".join(slot_lines)

                staged_success = False
                if not dry_run:
                    draft_res = manager.save_draft_reply(
                        message_id=email.id,
                        reply_body=reply_body,
                        resume_filename=selected_resume
                    )
                    staged_success = draft_res.success
                else:
                    staged_success = True


                if staged_success:
                    summary["drafts_staged"] += 1
                    summary["high_fit_opportunities"].append({
                        "subject": email.subject,
                        "sender": email.sender_name or email.sender_email,
                        "role_title": role_title,
                        "fit_score": fit_data["fit_score"],
                        "attached_resume": selected_resume,
                        "account_id": email.account_id
                    })

                    # Dispatch macOS alert banner
                    company = rec_details.company_name if rec_details else "Enterprise Client"
                    send_macos_notification(
                        title="✉️ Aura Mail: Recruiter Draft Staged",
                        subtitle=f"{role_title} ({fit_data['fit_score']}% Fit)",
                        message=f"Draft response with {selected_resume} staged in Drafts for {company}."
                    )

                    save_processed_id(email.id, {
                        "category": "OPPORTUNITY_STAGED",
                        "role_title": role_title,
                        "fit_score": fit_data["fit_score"],
                        "selected_resume": selected_resume,
                        "dry_run": dry_run
                    })

        update_daemon_state("IDLE", summary)
    except Exception as e:
        logger.error(f"Daemon cycle failed with error: {e}", exc_info=True)
        summary["errors"].append(str(e))
        update_daemon_state("ERROR", summary)
    finally:
        lock_ctx.release()

    return summary

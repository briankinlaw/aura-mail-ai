"""Aura Mail AI - Settings & Database Migration (v1.0 to v1.1).

Preserves non-secret user preferences, migrates credentials into macOS Keychain,
and sanitizes on-disk configuration files.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

from backend.security import set_secret, logger

def migrate_v1_to_v1_1(settings_file: Path, base_dir: Path) -> Dict[str, Any]:
    """Migrates settings from v1.0 schema to v1.1 cloud-first architecture."""
    sanitized_settings: Dict[str, Any] = {
        "azure_client_id": "",
        "azure_tenant_id": "common",
        "user_profile": {
            "full_name": "Brian K. Kinlaw",
            "current_title": "Enterprise Cloud, Data & AI Solutions Architecture Advisor",
            "email": "kinlawb@outlook.com",
            "phone": "(210) 717-5305",
            "linkedin_url": "https://linkedin.com/in/briankinlaw/",
            "portfolio_url": "https://linkedin.com/in/briankinlaw/",
            "summary_bio": "Principal-level cloud, data, and AI solutions architect and trusted advisor with 20+ years of experience translating complex business requirements into enterprise architectures, implementation strategies, and production deployments.",
            "core_skills": [
                "Enterprise Architecture", "Cloud Data & AI", "Google Cloud / GCP", "BigQuery / Databricks",
                "Pre-sales & Discovery", "AI Governance & NIST AI RMF", "Technical Program Management", "Agentic AI Systems"
            ],
            "target_roles": [
                "Advisor / Principal Solutions Architect", "Field CTO / Technology Strategist",
                "Principal Technical Program Manager", "AI Governance & Enterprise Data Leader"
            ],
            "work_preferences": "Remote or Hybrid (San Antonio, TX / Remote US). Open to advisory, contract, and full-time leadership roles.",
            "active_resume_file": "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
            "active_email_accounts": [
                "kinlawb@outlook.com",
                "brian.kinlaw@outlook.com",
                "briankkinlaw@gmail.com",
                "cbkinlaw@satx.rr.com",
                "briankinlaw@satx.rr.com",
                "brian@mavencode.com"
            ],
            "historical_email_accounts": [
                "bkinlaw@dxc.com",
                "brian.kinlaw@cdw.com",
                "briankinlaw@revealwhy.com"
            ],
            "custom_reply_instructions": "Be warm, concise, professional, and executive-ready. Connect my verified background directly to the employer's objectives. Highlight 2-3 verified metrics (e.g. $8M Google Cloud revenue influenced, $100M+ enterprise revenue delivered, Promevo pipeline $2M+). Explicitly mention that my updated resume is attached. Invite them to schedule a brief intro discussion.",
            "safety_mode": "SAFE_REVIEW",
            "noise_handling": "MOVE_TO_CLEANED_FOLDER"
        },
        "configured_accounts": [
            {
                "account_id": "kinlawb@outlook.com",
                "email": "kinlawb@outlook.com",
                "provider": "MICROSOFT_GRAPH",
                "display_name": "Brian Kinlaw (Primary Outlook)",
                "enabled": True,
                "is_primary": True
            },
            {
                "account_id": "brian.kinlaw@outlook.com",
                "email": "brian.kinlaw@outlook.com",
                "provider": "MICROSOFT_GRAPH",
                "display_name": "Brian Kinlaw (Outlook Alias)",
                "enabled": True,
                "is_primary": False
            },
            {
                "account_id": "briankkinlaw@gmail.com",
                "email": "briankkinlaw@gmail.com",
                "provider": "GMAIL",
                "display_name": "Brian Kinlaw (Google)",
                "enabled": True,
                "is_primary": False
            },
            {
                "account_id": "cbkinlaw@satx.rr.com",
                "email": "cbkinlaw@satx.rr.com",
                "provider": "IMAP",
                "display_name": "Brian Kinlaw (Spectrum Roadrunner 1)",
                "imap_server": "mail.twc.com",
                "smtp_server": "mail.twc.com",
                "enabled": True,
                "is_primary": False
            },
            {
                "account_id": "briankinlaw@satx.rr.com",
                "email": "briankinlaw@satx.rr.com",
                "provider": "IMAP",
                "display_name": "Brian Kinlaw (Spectrum Roadrunner 2)",
                "imap_server": "mail.twc.com",
                "smtp_server": "mail.twc.com",
                "enabled": True,
                "is_primary": False
            },
            {
                "account_id": "brian@mavencode.com",
                "email": "brian@mavencode.com",
                "provider": "IMAP",
                "display_name": "Brian Kinlaw (MavenCode Advisory)",
                "imap_server": "mail.mavencode.com",
                "smtp_server": "mail.mavencode.com",
                "enabled": True,
                "is_primary": False
            }
        ],
        "auto_pilot_enabled": False,
        "safe_folder_name": "AI Cleaned - Noise",
        "demo_mode": False
    }

    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            
            # 1. Migrate secrets to Keychain if present
            raw_gemini = raw_data.get("gemini_api_key", "")
            if raw_gemini and not raw_gemini.startswith("YOUR_"):
                set_secret("gemini_api_key", raw_gemini)
                logger.info("Migrated Gemini API key to macOS Keychain.")

            imap_cfg = raw_data.get("imap_config", {})
            if imap_cfg.get("password") and imap_cfg.get("email"):
                set_secret(f"imap_password_{imap_cfg['email']}", imap_cfg["password"])
                logger.info(f"Migrated IMAP password for {imap_cfg['email']} to macOS Keychain.")

            # 2. Preserve non-secret user preferences
            if "user_profile" in raw_data and isinstance(raw_data["user_profile"], dict):
                sanitized_settings["user_profile"].update(raw_data["user_profile"])
            
            if "azure_client_id" in raw_data:
                # Do not carry over the hard-coded Azure CLI id
                cid = raw_data["azure_client_id"]
                if cid and cid != "04b07795-8ddb-461a-bbee-02f9e1bf7b46" and cid != "d3590ed6-52b3-4102-aeff-aad2292ab01c":
                    sanitized_settings["azure_client_id"] = cid

            if "azure_tenant_id" in raw_data:
                sanitized_settings["azure_tenant_id"] = raw_data["azure_tenant_id"]
            if "safe_folder_name" in raw_data:
                sanitized_settings["safe_folder_name"] = raw_data["safe_folder_name"]
            if "auto_pilot_enabled" in raw_data:
                sanitized_settings["auto_pilot_enabled"] = raw_data["auto_pilot_enabled"]
            if "demo_mode" in raw_data:
                sanitized_settings["demo_mode"] = raw_data["demo_mode"]

        except Exception as e:
            logger.warning(f"Error during settings migration: {e}")

    # Write back clean settings (without plaintext secrets)
    try:
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(sanitized_settings, f, indent=2)
        logger.info("Sanitized settings.json written successfully.")
    except Exception as e:
        logger.error(f"Failed to write sanitized settings: {e}")

    return sanitized_settings

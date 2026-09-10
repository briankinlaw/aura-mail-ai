import os
import json
from pathlib import Path
from backend.models import UserProfile

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESUMES_DIR = DATA_DIR / "resumes"
SETTINGS_FILE = DATA_DIR / "settings.json"
EMAILS_CACHE_FILE = DATA_DIR / "emails_cache.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
RESUMES_DIR.mkdir(parents=True, exist_ok=True)

# Azure MSAL Client Configuration defaults (public client app / Device Code flow)
DEFAULT_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "d3590ed6-52b3-4102-aeff-aad2292ab01c") # Standard public graph client ID or user provided
GRAPH_SCOPES = [
    "User.Read",
    "Mail.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "MailboxSettings.ReadWrite"
]

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                # Ensure user_profile has Brian Kinlaw defaults
                if not settings.get("user_profile") or settings.get("user_profile", {}).get("full_name") == "Jane Doe":
                    settings["user_profile"] = UserProfile().model_dump()
                return settings
        except Exception:
            pass
    
    # Default settings
    default_profile = UserProfile().model_dump()
    settings = {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "azure_client_id": DEFAULT_CLIENT_ID,
        "azure_tenant_id": "common",
        "auth_token": None,
        "user_profile": default_profile,
        "auto_pilot_enabled": False,
        "safe_folder_name": "AI Cleaned - Noise",
        "demo_mode": False
    }
    save_settings(settings)
    return settings

def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

def get_user_profile() -> UserProfile:
    settings = load_settings()
    profile_data = settings.get("user_profile", {})
    return UserProfile(**profile_data)

def update_user_profile(profile: UserProfile):
    settings = load_settings()
    settings["user_profile"] = profile.model_dump()
    save_settings(settings)

def ensure_sample_resume():
    sample_resume = RESUMES_DIR / "resume_master.pdf"
    sample_text_resume = RESUMES_DIR / "resume_master.txt"
    if not sample_resume.exists() and not sample_text_resume.exists():
        with open(sample_text_resume, "w", encoding="utf-8") as f:
            f.write(
                "JANE DOE\n"
                "Staff Software Engineer & AI Architect\n"
                "Email: jane.doe@example.com | Phone: +1 (555) 019-2834 | San Francisco, CA\n"
                "LinkedIn: linkedin.com/in/example | GitHub: github.com/example\n\n"
                "SUMMARY:\n"
                "Accomplished Software Engineer with 10+ years of expertise in distributed systems, "
                "enterprise AI platforms, LLM agent orchestration, and cloud infrastructure (GCP/AWS/Azure). "
                "Proven track record leading engineering teams to deliver high-throughput, mission-critical systems.\n\n"
                "CORE SKILLS:\n"
                "- Languages: Python, Go, TypeScript, SQL, Rust\n"
                "- AI/ML: LLM Orchestration, LangChain/LlamaIndex, Gemini API, RAG Architecture, Vector DBs (pgvector, Pinecone)\n"
                "- Backend & Cloud: FastAPI, Docker, Kubernetes, Terraform, PostgreSQL, Redis, Kafka\n\n"
                "EXPERIENCE:\n"
                "Principal AI Systems Architect | Apex Tech Inc (2021 - Present)\n"
                "- Led 14 engineers building enterprise LLM workflows processing 10M+ daily requests.\n"
                "- Designed scalable agentic triage pipeline cutting customer support latency by 72%.\n\n"
                "Senior Software Engineer | CloudScale Networks (2017 - 2021)\n"
                "- Architected high-concurrency microservices in Go and Python serving 50M+ active users.\n\n"
                "EDUCATION:\n"
                "B.S. in Computer Science | University of California, Berkeley\n"
            )

ensure_sample_resume()

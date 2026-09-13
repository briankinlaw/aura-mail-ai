from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class EmailCategory(str, Enum):
    RESUME_REQUEST = "RESUME_REQUEST"
    NOISE_PROMOTIONAL = "NOISE_PROMOTIONAL"
    NOISE_NEWSLETTER = "NOISE_NEWSLETTER"
    NOISE_NOTIFICATION = "NOISE_NOTIFICATION"
    OTHER_IMPORTANT = "OTHER_IMPORTANT"
    UNCLASSIFIED = "UNCLASSIFIED"

class RecruiterDetails(BaseModel):
    recruiter_name: Optional[str] = "Recruiter"
    company_name: Optional[str] = "Prospective Employer"
    role_title: Optional[str] = "Open Position"
    location: Optional[str] = "Remote / Hybrid / On-site"
    salary_range: Optional[str] = None
    required_skills: List[str] = Field(default_factory=list)
    key_responsibilities: Optional[str] = None
    urgency: Optional[str] = "Normal"  # High, Normal, Low
    contact_phone_or_link: Optional[str] = None

class ResumeVariant(BaseModel):
    id: str
    filename: str
    filepath: str
    display_title: str
    category: str  # standard_canonical, targeted_custom, source_of_truth, master_variant
    target_lens: str
    lens_name: str
    lens_badge: str
    lens_color: str
    headline: str
    snippet: str
    format: str
    size_kb: float
    last_modified: str
    raw_text_length: int = 0

class ResumeMatchResult(BaseModel):
    selected_resume: Optional[str] = None
    selected_resume_path: Optional[str] = None
    selected_resume_meta: Optional[Dict[str, Any]] = None
    match_score: int = 0
    matching_lens: str = "level_3a_advisor"
    lens_name: str = "Level 3A — Advisor / Principal Solutions Architect"
    lens_badge: str = "🎯 Level 3A"
    lens_color: str = "#8b5cf6"
    rationale: str = ""
    key_skills_matched: List[str] = Field(default_factory=list)

class ClassificationResult(BaseModel):
    category: EmailCategory
    confidence: float = 1.0
    reasoning: str
    is_noise: bool = False
    is_resume_request: bool = False
    recruiter_details: Optional[RecruiterDetails] = None
    suggested_action: str = "REVIEW"  # TRASH, ARCHIVE, REPLY, KEEP
    resume_match: Optional[ResumeMatchResult] = None

class EmailMessage(BaseModel):
    id: str
    account_id: str = "primary"
    provider: Optional[str] = None
    conversation_id: Optional[str] = None
    subject: str
    sender_name: str
    sender_email: str
    received_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    preview: str = ""
    body_text: str
    body_html: Optional[str] = None
    is_read: bool = False
    has_attachments: bool = False
    folder: str = "Inbox"
    classification: Optional[ClassificationResult] = None
    draft_reply: Optional[str] = None
    selected_resume_file: Optional[str] = None
    status: str = "PENDING"  # PENDING, REPLIED, TRASHED, ARCHIVED, SKIPPED

class UserProfile(BaseModel):
    full_name: str = "Brian K. Kinlaw"
    current_title: str = "Enterprise Cloud, Data & AI Solutions Architecture Advisor"
    email: str = "kinlawb@outlook.com"
    phone: Optional[str] = "(210) 717-5305"
    linkedin_url: Optional[str] = "https://linkedin.com/in/briankinlaw"
    portfolio_url: Optional[str] = "https://linkedin.com/in/briankinlaw"
    summary_bio: str = (
        "Principal-level cloud, data, and AI solutions architect and trusted advisor with 20+ years of experience "
        "translating complex business requirements into enterprise architectures, implementation strategies, and production deployments."
    )
    core_skills: List[str] = Field(
        default_factory=lambda: [
            "Enterprise Architecture", "Cloud Data & AI", "Google Cloud / GCP", "BigQuery / Databricks",
            "Pre-sales & Discovery", "AI Governance & NIST AI RMF", "Technical Program Management", "Agentic AI Systems"
        ]
    )
    target_roles: List[str] = Field(
        default_factory=lambda: [
            "Advisor / Principal Solutions Architect", "Field CTO / Technology Strategist", 
            "Principal Technical Program Manager", "AI Governance & Enterprise Data Leader"
        ]
    )
    work_preferences: str = "Remote or Hybrid (San Antonio, TX / Remote US). Open to advisory, contract, and full-time leadership roles."
    active_resume_file: Optional[str] = "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
    active_email_accounts: List[str] = Field(
        default_factory=lambda: [
            "kinlawb@outlook.com",
            "brian.kinlaw@outlook.com",
            "briankkinlaw@gmail.com",
            "cbkinlaw@satx.rr.com",
            "briankinlaw@satx.rr.com",
            "brian@mavencode.com"
        ]
    )
    historical_email_accounts: List[str] = Field(
        default_factory=lambda: [
            "bkinlaw@dxc.com",
            "brian.kinlaw@cdw.com",
            "briankinlaw@revealwhy.com"
        ]
    )
    custom_reply_instructions: str = (
        "Be warm, concise, professional, and executive-ready. Connect my verified background directly to the employer's objectives. "
        "Highlight 2-3 verified metrics (e.g. $8M Google Cloud revenue influenced, $100M+ enterprise revenue delivered). "
        "Explicitly mention that my updated resume is attached. Invite them to schedule a brief intro discussion."
    )
    cloud_ai_enabled: bool = False
    safety_mode: str = "DRAFT_ONLY"  # DRAFT_ONLY (fail-closed default) vs MANUAL_SEND_ONLY
    noise_handling: str = "MOVE_TO_CLEANED_FOLDER"  # MOVE_TO_CLEANED_FOLDER vs DELETE_PERMANENTLY

class ReplyDraftRequest(BaseModel):
    custom_instructions: Optional[str] = None
    selected_resume: Optional[str] = None
    tone: Optional[str] = "Professional & Warm"

class SendReplyRequest(BaseModel):
    reply_body: str
    subject: Optional[str] = None
    attach_resume: bool = True
    resume_filename: Optional[str] = None
    to_email: Optional[str] = None

class QuarantineMessageResult(BaseModel):
    email_id: str
    subject: str
    provider: str
    account_id: str
    destination_folder_id: Optional[str] = None
    success: bool
    error_code: Optional[str] = None
    message: str

class QuarantineBatchResult(BaseModel):
    status: str  # SUCCESS, PARTIAL_SUCCESS, FAILED
    total_requested: int
    cleaned_count: int
    failed_count: int
    cleaned_ids: List[str] = Field(default_factory=list)
    results: List[QuarantineMessageResult] = Field(default_factory=list)
    message: str

import os
import re
import json
import logging
from typing import Optional, Tuple
from backend.models import (
    EmailMessage,
    ClassificationResult,
    EmailCategory,
    RecruiterDetails,
    UserProfile,
    ReplyDraftRequest
)
from backend.config import load_settings

from backend.canonical_engine import (
    find_best_resume_match,
    scan_canonical_system,
    get_canonical_ledger_summary,
    LOCKED_FACTS,
    LENS_DEFINITIONS
)

logger = logging.getLogger(__name__)

# Heuristic Patterns for Fallback & Pre-filtering
NOISE_PROMO_KEYWORDS = [
    "unsubscribe", "sale", "discount", "special offer", "limited time", "buy now", 
    "deal of the day", "% off", "promo code", "free shipping", "clearance", "webinar",
    "exclusive invitation", "book a demo", "b2b leads"
]

NOISE_NOTIFICATION_PATTERNS = [
    r"no-reply@", r"donotreply@", r"notification@", r"alerts?@", r"mailer-daemon@",
    r"security alert", r"password reset", r"verify your email", r"two-factor",
    r"github notification", r"jira issue", r"pagerduty alert", r"your order has shipped",
    r"invoice #", r"receipt for your"
]

RESUME_REQUEST_PATTERNS = [
    r"resume", r"cv", r"curriculum vitae", r"profile", r"candidate", r"recruiter",
    r"talent acquisition", r"headhunter", r"job opening", r"opportunity",
    r"position at", r"hiring for", r"interview", r"open role", r"staff engineer",
    r"send over your updated resume", r"attach your resume", r"forward your resume",
    r"share your resume", r"would you be open to", r"quick chat"
]

def get_gemini_client():
    settings = load_settings()
    api_key = settings.get("gemini_api_key") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.warning(f"Could not initialize google-genai client: {e}")
        return None

_GEMINI_COOLDOWN_UNTIL = 0.0

def classify_email(email: EmailMessage) -> ClassificationResult:
    """Classifies email using smart heuristic pre-filtering and Gemini GenAI with canonical resume matching."""
    global _GEMINI_COOLDOWN_UNTIL

    # Fast heuristic pre-filter for obvious noise
    sender_lower = (f"{email.sender_name} {email.sender_email}").lower()
    subject_lower = (email.subject or "").lower()
    body_lower = (email.body_text or "").lower()

    for pattern in NOISE_NOTIFICATION_PATTERNS:
        if re.search(pattern, sender_lower) or re.search(pattern, subject_lower):
            return ClassificationResult(
                category=EmailCategory.NOISE_NOTIFICATION,
                confidence=0.95,
                reasoning="Automated transactional/system notification.",
                is_noise=True,
                is_resume_request=False,
                suggested_action="TRASH"
            )

    promo_score = sum(1 for kw in NOISE_PROMO_KEYWORDS if kw in f"{subject_lower} {body_lower}")
    if promo_score >= 3 or ("unsubscribe" in body_lower and promo_score >= 1):
        cat = EmailCategory.NOISE_NEWSLETTER if ("newsletter" in body_lower or "digest" in body_lower) else EmailCategory.NOISE_PROMOTIONAL
        return ClassificationResult(
            category=cat,
            confidence=0.92,
            reasoning="Promotional marketing email or newsletter.",
            is_noise=True,
            is_resume_request=False,
            suggested_action="TRASH"
        )

    # If currently in API rate limit cooldown, use heuristics immediately
    import time
    if time.time() < _GEMINI_COOLDOWN_UNTIL:
        return _classify_heuristics(email)

    client = get_gemini_client()
    if client:
        try:
            prompt = f"""
You are an expert executive email triage and career assistant.
Analyze the following email and determine if it is:
1. RESUME_REQUEST: A recruiter, talent acquisition specialist, hiring manager, or headhunter reaching out about a job opportunity, asking for a resume/CV, or inquiring about career interest.
2. NOISE_PROMOTIONAL: Marketing emails, sales pitches, discounts, promotional offers, vendor spam.
3. NOISE_NEWSLETTER: Blog digests, mailing lists, industry newsletters, automated publications.
4. NOISE_NOTIFICATION: Automated system notifications, GitHub/Jira alerts, automated receipts, password alerts.
5. OTHER_IMPORTANT: Direct human-to-human correspondence, client communication, team project messages, personal emails.

Email Details:
Sender: {email.sender_name} <{email.sender_email}>
Subject: {email.subject}
Body:
\"\"\"
{email.body_text[:3000]}
\"\"\"

Respond STRICTLY in JSON format matching this schema:
{{
  "category": "RESUME_REQUEST" | "NOISE_PROMOTIONAL" | "NOISE_NEWSLETTER" | "NOISE_NOTIFICATION" | "OTHER_IMPORTANT",
  "confidence": 0.0 to 1.0,
  "reasoning": "Concise 1-sentence explanation of why this category was chosen",
  "suggested_action": "REPLY" | "TRASH" | "ARCHIVE" | "KEEP",
  "recruiter_details": {{
      "recruiter_name": "Name of recruiter/sender or null",
      "company_name": "Company hiring or staffing agency or null",
      "role_title": "Specific job title offered or null",
      "location": "Location / Remote status or null",
      "salary_range": "Salary or compensation range if mentioned or null",
      "required_skills": ["Skill1", "Skill2"],
      "key_responsibilities": "Brief summary or null",
      "urgency": "High" | "Normal" | "Low",
      "contact_phone_or_link": "Link to calendar or phone if provided or null"
  }}
}}
"""
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            raw_text = response.text.strip()
            data = json.loads(raw_text)
            
            category = EmailCategory(data.get("category", EmailCategory.OTHER_IMPORTANT.value))
            is_noise = category in [
                EmailCategory.NOISE_PROMOTIONAL,
                EmailCategory.NOISE_NEWSLETTER,
                EmailCategory.NOISE_NOTIFICATION
            ]
            is_resume_request = (category == EmailCategory.RESUME_REQUEST)
            
            rec_details = None
            resume_match_res = None
            if is_resume_request and data.get("recruiter_details"):
                rec_details = RecruiterDetails(**data["recruiter_details"])
                # Match against canonical resume system
                match_data = find_best_resume_match(
                    job_title=rec_details.role_title or email.subject,
                    job_description=email.body_text,
                    sender=email.sender_email
                )
                from backend.models import ResumeMatchResult
                resume_match_res = ResumeMatchResult(**match_data)
            
            return ClassificationResult(
                category=category,
                confidence=float(data.get("confidence", 0.95)),
                reasoning=data.get("reasoning", "Classified by Gemini AI"),
                is_noise=is_noise,
                is_resume_request=is_resume_request,
                recruiter_details=rec_details,
                suggested_action=data.get("suggested_action", "REVIEW"),
                resume_match=resume_match_res
            )
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                _GEMINI_COOLDOWN_UNTIL = time.time() + 20
            logger.warning(f"Gemini API classification failed, using fallback: {e}")

    # Heuristic Fallback Analysis
    return _classify_heuristics(email)

def _classify_heuristics(email: EmailMessage) -> ClassificationResult:
    subject_lower = (email.subject or "").lower()
    body_lower = (email.body_text or "").lower()
    sender_lower = (f"{email.sender_name} {email.sender_email}").lower()
    full_text = f"{subject_lower} {body_lower} {sender_lower}"
    
    # 1. Check for Resume Requests / Recruiters / Job Inquiries
    recruiter_signals = [
        "recruiter", "talent", "headhunter", "hiring", "staffing", "career opportunity", 
        "open role", "job opportunity", "send your resume", "attached resume", "resume",
        "inmail-hit-reply", "job alert", "solutions architect", "technical sme", "director",
        "opportunity", "position", "candidate", "capgemini"
    ]
    recruiter_score = sum(1 for s in recruiter_signals if s in full_text)
    
    if (recruiter_score >= 2 or ("inmail" in sender_lower) or ("job alert" in sender_lower) or ("resume" in full_text and ("role" in full_text or "opportunity" in full_text or "position" in full_text))):
        recruiter_details = _extract_recruiter_details_heuristic(email)
        match_data = find_best_resume_match(
            job_title=recruiter_details.role_title or email.subject,
            job_description=email.body_text,
            sender=email.sender_email
        )
        from backend.models import ResumeMatchResult
        resume_match_res = ResumeMatchResult(**match_data)
        return ClassificationResult(
            category=EmailCategory.RESUME_REQUEST,
            confidence=0.92,
            reasoning=f"Identified inbound talent reachout for '{recruiter_details.role_title}' from '{recruiter_details.company_name}'.",
            is_noise=False,
            is_resume_request=True,
            recruiter_details=recruiter_details,
            suggested_action="REPLY",
            resume_match=resume_match_res
        )
    
    # 2. Check for Automated System Notifications
    for pattern in NOISE_NOTIFICATION_PATTERNS:
        if re.search(pattern, email.sender_email.lower()) or re.search(pattern, subject_lower):
            return ClassificationResult(
                category=EmailCategory.NOISE_NOTIFICATION,
                confidence=0.88,
                reasoning="Automated transactional/system notification or alert.",
                is_noise=True,
                is_resume_request=False,
                suggested_action="TRASH"
            )
    
    # 3. Check for Promotional / Marketing
    promo_score = sum(1 for kw in NOISE_PROMO_KEYWORDS if kw in full_text)
    if promo_score >= 2 or "unsubscribe" in body_lower:
        if "newsletter" in full_text or "digest" in full_text or "edition" in full_text:
            return ClassificationResult(
                category=EmailCategory.NOISE_NEWSLETTER,
                confidence=0.85,
                reasoning="Newsletter publication or periodic industry digest.",
                is_noise=True,
                is_resume_request=False,
                suggested_action="ARCHIVE"
            )
        return ClassificationResult(
            category=EmailCategory.NOISE_PROMOTIONAL,
            confidence=0.89,
            reasoning="Marketing offer, promotional campaign, or unsolicited sales pitch.",
            is_noise=True,
            is_resume_request=False,
            suggested_action="TRASH"
        )
    
    # 4. Default to Other Important / Direct Message
    return ClassificationResult(
        category=EmailCategory.OTHER_IMPORTANT,
        confidence=0.80,
        reasoning="Direct human correspondence or project-related message.",
        is_noise=False,
        is_resume_request=False,
        suggested_action="KEEP"
    )

def _extract_recruiter_details_heuristic(email: EmailMessage) -> RecruiterDetails:
    text = f"{email.subject}\n{email.body_text}"
    
    # Extract role title
    role_match = re.search(r"(?:role of|position of|hiring for a|looking for a|seeking a|opportunity for a|title:)\s*([A-Za-z0-9\s\-\/\+]{4,40})", text, re.IGNORECASE)
    role_title = role_match.group(1).strip() if role_match else "Solutions Architecture & AI Leadership Opportunity"
    
    # Extract company name
    company_match = re.search(r"(?:at|with|join our team at|on behalf of)\s+([A-Z][A-Za-z0-9\s\.\,\&]{2,30})", text)
    company_name = company_match.group(1).strip() if company_match else "Prospective Client / Employer"
    if "our team" in company_name.lower() or "the company" in company_name.lower():
        company_name = "Client Company"

    # Extract salary/rate
    salary_match = re.search(r"(\$\d{2,3}(?:,\d{3})*(?:\s*-\s*\$\d{2,3}(?:,\d{3})*|\s*k\b|\s*\/hr|\s*\/yr)?)", text, re.IGNORECASE)
    salary_range = salary_match.group(1).strip() if salary_match else None
    
    # Extract skills
    tech_keywords = [
        "Google Cloud", "GCP", "BigQuery", "Databricks", "Cloud Architecture", 
        "Enterprise Architecture", "AI Governance", "Data Governance", "Collibra", 
        "Lakehouse", "Agentic AI", "Pre-sales", "TPM", "PMP", "FastAPI", "Python"
    ]
    found_skills = [skill for skill in tech_keywords if re.search(rf"\b{re.escape(skill)}\b", text, re.IGNORECASE)]
    
    # Recruiter name
    recruiter_name = email.sender_name or "there"
    if "@" in recruiter_name:
        recruiter_name = recruiter_name.split("@")[0].replace(".", " ").title()

    return RecruiterDetails(
        recruiter_name=recruiter_name,
        company_name=company_name,
        role_title=role_title,
        location="Remote / Hybrid (US)",
        salary_range=salary_range,
        required_skills=found_skills or ["Enterprise Architecture", "Cloud Data & AI", "Google Cloud"],
        urgency="High" if "urgent" in text.lower() or "immediate" in text.lower() else "Normal"
    )

def generate_personalized_reply(
    email: EmailMessage, 
    user_profile: UserProfile, 
    request_params: Optional[ReplyDraftRequest] = None
) -> str:
    """Generates an executive, strictly grounded, personalized reply to recruiter with matching canonical resume attached."""
    client = get_gemini_client()
    tone = request_params.tone if request_params else "Professional & Warm"
    custom_instr = (request_params.custom_instructions if request_params and request_params.custom_instructions 
                    else user_profile.custom_reply_instructions)
    
    details = (email.classification.recruiter_details if email.classification and email.classification.recruiter_details 
               else _extract_recruiter_details_heuristic(email))
    
    # Resolve active attached resume name
    selected_resume = None
    if request_params and request_params.selected_resume:
        selected_resume = request_params.selected_resume
    elif email.classification and email.classification.resume_match:
        rm = email.classification.resume_match
        if isinstance(rm, dict):
            selected_resume = rm.get("selected_resume")
        else:
            selected_resume = getattr(rm, "selected_resume", None)
    if not selected_resume:
        selected_resume = user_profile.active_resume_file or "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"

    if client:
        try:
            prompt = f"""
You are an executive ghostwriter crafting a strategic recruiter email response on behalf of {user_profile.full_name}.
A recruiter has reached out regarding an opportunity. Draft an executive, concise, and compelling response grounded STRICTLY in Brian Kinlaw's Canonical Career System.

Candidate Authoritative Facts:
- Name: {user_profile.full_name}
- Current Title: {user_profile.current_title}
- Background Summary: {user_profile.summary_bio}
- Key Skills: {', '.join(user_profile.core_skills)}
- Work Preferences: {user_profile.work_preferences}
- Attached Resume Document: {selected_resume}
- Verified Canonical Metrics (DO NOT EXCEED OR INVENT):
  * Influenced $8M in new Google Cloud revenue (never say 'generated $8M')
  * $100M+ enterprise revenue influenced and delivered across career
  * Closed $2.1M in services and influenced $4M in annual revenue (CDW)
  * Promevo pipeline contribution estimated $2M+ (presales efficiency roadmap targeting 30% improvement)
  * Realized results: 23% POC-to-production conversion, 40% reduced scoping turnaround, 20% shorter sales cycles
  * Current status: Strategic Advisor, Data & AI at MavenCode / Senior Solutions Architect at Promevo (Concurrent)

Recruiter & Role Information:
- Recruiter Name: {details.recruiter_name}
- Company: {details.company_name}
- Role Title: {details.role_title}
- Compensation: {details.salary_range or 'Not specified'}
- Stated Focus / Skills: {', '.join(details.required_skills)}

Inbound Recruiter Email:
\"\"\"
From: {email.sender_name}
Subject: {email.subject}
{email.body_text}
\"\"\"

Guidelines:
1. Tone: {tone}
2. Instructions: {custom_instr}
3. Executive Hook: Connect Brian's verified background directly to the opportunity ({details.role_title} at {details.company_name}) without generic introductory fluff.
4. Quantified Value: Select 2 of the strongest VERIFIED metrics from the list above that directly align with this role.
5. Strict Grounding: Zero hallucination. Do not invent unapproved metrics, tools, or dates.
6. Attachment Reference: Explicitly state that the updated resume ({selected_resume}) is attached for review.
7. Call to Action: Professional, low-friction invitation to discuss alignment (e.g. 15-minute introductory conversation).
8. Signature: {user_profile.full_name} | {user_profile.current_title} | {user_profile.phone or '(210) 717-5305'} | {user_profile.linkedin_url or 'linkedin.com/in/briankinlaw'}

Output ONLY the plain text email body.
"""
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            logger.warning(f"Gemini reply generation failed, using fallback: {e}")

    # Canonical-grounded fallback template
    recruiter_first = details.recruiter_name.split()[0] if details.recruiter_name else "there"
    skills_bullet = ", ".join(details.required_skills[:4]) if details.required_skills else "enterprise cloud, data architectures, and AI systems"
    
    return (
        f"Hi {recruiter_first},\n\n"
        f"Thank you for reaching out regarding the {details.role_title} opportunity at {details.company_name}. "
        f"The scope aligns directly with my background in {skills_bullet}.\n\n"
        f"Over my career across Google, CDW, and enterprise advisory, I have influenced and delivered $100M+ in enterprise revenue, "
        f"including influencing $8M in new Google Cloud revenue and accelerating complex data & AI architectures from concept to production.\n\n"
        f"I have attached my updated resume ({selected_resume}) for your review. "
        f"It details my track record across enterprise solutions architecture, AI platform strategy, and technical delivery.\n\n"
        f"I would be glad to connect for a brief 15-minute conversation to discuss how my background aligns with {details.company_name}'s goals. "
        f"Please feel free to suggest a time that suits your schedule or share a calendar link.\n\n"
        f"Best regards,\n\n"
        f"{user_profile.full_name}\n"
        f"{user_profile.current_title}\n"
        f"{user_profile.phone or '(210) 717-5305'} | {user_profile.linkedin_url or 'https://linkedin.com/in/briankinlaw'}"
    )


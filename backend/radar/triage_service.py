"""
Opportunity Radar Triage Service
Handles multi-signal heuristic pre-filtering, Gemini LLM classification, recruiter detail extraction, and opportunity fit scoring.
"""

import os
import re
import json
import logging
import time
from typing import Optional, Dict, Any, List

from backend.models import (
    EmailMessage,
    ClassificationResult,
    EmailCategory,
    RecruiterDetails,
    ResumeMatchResult
)
from backend.canonical_engine import find_best_resume_match

logger = logging.getLogger("radar.triage")

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

_GEMINI_COOLDOWN_UNTIL = 0.0

# Alias for backward compatibility
_classify_heuristics = None

def get_gemini_client():
    from backend.security import get_secret
    api_key = get_secret("gemini_api_key", "GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.warning(f"Could not initialize google-genai client: {e}")
        return None

def calculate_opportunity_fit_score(
    role_title: str,
    body_text: str,
    required_skills: List[str]
) -> Dict[str, Any]:
    """Calculates a deterministic 0-100 opportunity fit score against Brian Kinlaw's core career pillars."""
    score = 50  # Baseline
    reasons = []

    text_lower = f"{role_title} {body_text}".lower()

    # Leadership & Architecture Signals (+10 each)
    if any(k in text_lower for k in ["principal", "lead", "director", "head of", "architect", "strategist", "advisor"]):
        score += 15
        reasons.append("Senior / Principal / Advisory tier")

    # Cloud & Enterprise Signals (+10 each)
    if any(k in text_lower for k in ["google cloud", "gcp", "bigquery", "databricks", "lakehouse", "enterprise architecture"]):
        score += 15
        reasons.append("High alignment with Google Cloud / Data Platform expertise")

    # AI & Governance Signals (+10 each)
    if any(k in text_lower for k in ["agentic", "genai", "governance", "collibra", "nist", "ai platform"]):
        score += 10
        reasons.append("AI Governance / Modern Agentic systems alignment")

    # Compensation indicators
    if any(k in text_lower for k in ["$200", "$220", "$250", "$300", "200k", "250k", "300k"]):
        score += 10
        reasons.append("Strong compensation bracket")

    # Junior / Entry / Mismatch penalties
    if any(k in text_lower for k in ["junior", "entry level", "intern", "tier 1 helpdesk", "junior sysadmin"]):
        score -= 40
        reasons.append("Seniority mismatch (Junior/Entry level)")

    final_score = max(5, min(100, score))
    return {
        "fit_score": final_score,
        "fit_tier": "HIGH" if final_score >= 75 else "MEDIUM" if final_score >= 50 else "LOW",
        "alignment_reasons": reasons
    }

def extract_recruiter_details(email: EmailMessage) -> RecruiterDetails:
    """Extracts structured recruiter and opportunity scope from email content."""
    text = f"{email.subject or ''}\n{email.body_text or ''}"
    
    # Extract role title (including &, +, -, /)
    role_match = re.search(r"(?:opportunity:?\s*|role of\s*|position of\s*|hiring for a\s*|looking for a\s*|seeking a\s*|title:\s*)([A-Za-z0-9\s\-\/\+\&]{4,60})", text, re.IGNORECASE)
    role_title = role_match.group(1).strip() if role_match else "Solutions Architecture & AI Leadership Opportunity"
    if " at " in role_title.lower():
        role_title = re.split(r"\s+at\s+", role_title, flags=re.IGNORECASE)[0].strip()
    
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

def classify_email_radar(email: EmailMessage) -> ClassificationResult:
    """Classifies inbound email using Opportunity Radar pre-filtering and Gemini GenAI."""
    global _GEMINI_COOLDOWN_UNTIL

    sender_lower = (f"{email.sender_name} {email.sender_email}").lower()
    subject_lower = (email.subject or "").lower()
    body_lower = (email.body_text or "").lower()

    # Fast heuristic pre-filter for automated noise
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

    if time.time() < _GEMINI_COOLDOWN_UNTIL:
        return _classify_heuristics_radar(email)

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
                match_data = find_best_resume_match(
                    job_title=rec_details.role_title or email.subject,
                    job_description=email.body_text,
                    sender=email.sender_email
                )
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

    return _classify_heuristics_radar(email)

def _classify_heuristics_radar(email: EmailMessage) -> ClassificationResult:
    subject_lower = (email.subject or "").lower()
    body_lower = (email.body_text or "").lower()
    sender_lower = (f"{email.sender_name} {email.sender_email}").lower()
    full_text = f"{subject_lower} {body_lower} {sender_lower}"
    
    recruiter_signals = [
        "recruiter", "talent", "headhunter", "hiring", "staffing", "career opportunity", 
        "open role", "job opportunity", "send your resume", "attached resume", "resume",
        "inmail-hit-reply", "job alert", "solutions architect", "technical sme", "director",
        "opportunity", "position", "candidate", "capgemini"
    ]
    recruiter_score = sum(1 for s in recruiter_signals if s in full_text)
    
    if (recruiter_score >= 2 or ("inmail" in sender_lower) or ("job alert" in sender_lower) or ("resume" in full_text and ("role" in full_text or "opportunity" in full_text or "position" in full_text))):
        recruiter_details = extract_recruiter_details(email)
        match_data = find_best_resume_match(
            job_title=recruiter_details.role_title or email.subject,
            job_description=email.body_text,
            sender=email.sender_email
        )
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
    
    return ClassificationResult(
        category=EmailCategory.OTHER_IMPORTANT,
        confidence=0.80,
        reasoning="Direct human correspondence or project-related message.",
        is_noise=False,
        is_resume_request=False,
        suggested_action="KEEP"
    )

_classify_heuristics = _classify_heuristics_radar


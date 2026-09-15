"""
Opportunity Radar Scribe Service
Generates executive, strictly grounded recruiter responses linked to the Canonical Career System (CCS v2.1).
"""

import logging
from typing import Optional, Dict, Any

from backend.models import (
    EmailMessage,
    UserProfile,
    ReplyDraftRequest
)
from backend.radar.triage_service import get_gemini_client, extract_recruiter_details
from backend.canonical_grounding import validate_canonical_grounding

logger = logging.getLogger("radar.scribe")

def generate_executive_reply(
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
               else extract_recruiter_details(email))

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
  * Realized results: 23% POC-to-production conversion, 40% reduced scoping turnaround, 20% shorter sales cycles
  * Current status: Strategic Advisor, Data & AI at MavenCode / Senior Solutions Architect (Concurrent)

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
            raw_text = getattr(response, "text", None)
            if raw_text is None or not isinstance(raw_text, str) or not raw_text.strip():
                logger.warning("Gemini generated empty/None response; falling back to deterministic template.")
                return compose_grounded_response(
                    recruiter_name=details.recruiter_name,
                    company_name=details.company_name,
                    role_title=details.role_title,
                    required_skills=details.required_skills,
                    selected_resume=selected_resume,
                    user_profile=user_profile
                )

            generated_text = raw_text.strip()

            # Post-generation deterministic canonical grounding validation
            validation = validate_canonical_grounding(generated_text, recipient_company=details.company_name)
            if not validation.is_grounded:
                logger.warning(
                    f"Generated reply failed canonical grounding validation ({validation.validation_summary}); falling back to deterministic grounded template."
                )
                return compose_grounded_response(
                    recruiter_name=details.recruiter_name,
                    company_name=details.company_name,
                    role_title=details.role_title,
                    required_skills=details.required_skills,
                    selected_resume=selected_resume,
                    user_profile=user_profile
                )
            return generated_text
        except Exception as e:
            logger.warning(f"Gemini reply generation failed, using fallback: {e}")

    return compose_grounded_response(
        recruiter_name=details.recruiter_name,
        company_name=details.company_name,
        role_title=details.role_title,
        required_skills=details.required_skills,
        selected_resume=selected_resume,
        user_profile=user_profile
    )

def compose_grounded_response(
    recruiter_name: str,
    company_name: str,
    role_title: str,
    required_skills: list,
    selected_resume: str,
    user_profile: UserProfile
) -> str:
    """Deterministic, fallback template strictly grounded in verified accomplishments."""
    recruiter_first = recruiter_name.split()[0] if recruiter_name and recruiter_name != "there" else "there"
    skills_bullet = ", ".join(required_skills[:4]) if required_skills else "enterprise cloud, data architectures, and AI systems"

    draft = (
        f"Hi {recruiter_first},\n\n"
        f"Thank you for reaching out regarding the {role_title} opportunity at {company_name}. "
        f"The scope aligns directly with my background in {skills_bullet}.\n\n"
        f"Across my career, I have influenced and delivered $100M+ in enterprise revenue, "
        f"including influencing $8M in new Google Cloud revenue at Google and closing $2.1M in services at CDW.\n\n"
        f"I have attached my updated resume ({selected_resume}) for your review. "
        f"It details my track record across enterprise solutions architecture, AI platform strategy, and technical delivery.\n\n"
        f"I would be glad to connect for a brief 15-minute conversation to discuss how my background aligns with {company_name}'s goals. "
        f"Please feel free to suggest a time that suits your schedule or share a calendar link.\n\n"
        f"Best regards,\n\n"
        f"{user_profile.full_name}\n"
        f"{user_profile.current_title}\n"
        f"{user_profile.phone or '(210) 717-5305'} | {user_profile.linkedin_url or 'https://linkedin.com/in/briankinlaw'}"
    )

    # Authoritative revalidation of constructed fallback
    val = validate_canonical_grounding(draft, recipient_company=company_name)
    if not val.is_grounded:
        raise RuntimeError(f"Deterministic fallback failed canonical grounding validation: {val.validation_summary}")
    return draft

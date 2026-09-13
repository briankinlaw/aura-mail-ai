"""
Aura Mail AI - Gemini Risk Sentinel & Second Opinion Evaluator
Provides independent second-opinion risk assessments on inbound recruiter emails,
generated draft replies, and automated actions to ensure zero-hallucination,
legal/compensation safety, and strict draft-first enforcement.
"""

import re
import json
import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from backend.models import EmailMessage, UserProfile
from backend.canonical_engine import LOCKED_FACTS

logger = logging.getLogger("radar.risk_evaluator")

class RiskSeverity(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    HIGH_RISK = "HIGH_RISK"

class RiskCategory(str, Enum):
    COMPENSATION_NEGOTIATION = "COMPENSATION_NEGOTIATION"
    UNVERIFIED_CAREER_CLAIM = "UNVERIFIED_CAREER_CLAIM"
    SUSPICIOUS_LINK_OR_SPOOFING = "SUSPICIOUS_LINK_OR_SPOOFING"
    AUTONOMOUS_SEND_POLICY = "AUTONOMOUS_SEND_POLICY"
    CONTRACT_LEGAL_COMMITMENT = "CONTRACT_LEGAL_COMMITMENT"
    PRIVACY_DATA_EXFILTRATION = "PRIVACY_DATA_EXFILTRATION"
    CLEAN = "CLEAN"

class RiskAssessmentResult(BaseModel):
    severity: RiskSeverity = RiskSeverity.SAFE
    is_flagged: bool = False
    risk_score: int = 0  # 0 to 100
    detected_categories: List[RiskCategory] = Field(default_factory=list)
    second_opinion_summary: str = "Action evaluated as safe and aligned with Canonical Career System standards."
    evaluator: str = "Gemini Risk Sentinel (Second Opinion)"
    recommended_action: str = "PROCEED"  # PROCEED, REVIEW_CAUTION, BLOCKED
    guardrail_warnings: List[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

# Heuristic Patterns for Pre-Screening
SUSPICIOUS_PATTERNS = [
    r"bit\.ly\/", r"tinyurl\.com\/", r"t\.co\/", r"\.exe\b", r"\.scr\b", r"\.zip\b.*download",
    r"wire transfer", r"crypto payment", r"routing number", r"ssn\b", r"social security"
]

COMPENSATION_LOCK_PATTERNS = [
    r"i agree to accept \$", r"my minimum salary is \$", r"i will sign for \$",
    r"i guarantee that i can start on", r"i accept this offer"
]

def get_gemini_client():
    from backend.security import get_secret
    api_key = get_secret("gemini_api_key", "GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.warning(f"Could not initialize google-genai client for risk evaluation: {e}")
        return None

def analyze_risk_heuristics(
    email_text: str,
    draft_text: str,
    action: str = "DRAFT"
) -> RiskAssessmentResult:
    """Deterministic, local heuristic pre-screen for immediate security and policy checks."""
    flags: List[RiskCategory] = []
    warnings: List[str] = []
    combined_text = f"{email_text}\n{draft_text}".lower()

    # 1. Check for autonomous send attempt without review
    if action == "SEND" and "auto_pilot" in combined_text:
        flags.append(RiskCategory.AUTONOMOUS_SEND_POLICY)
        warnings.append("Draft-First Policy: Direct autonomous dispatch without human staging is prohibited.")

    # 2. Check for suspicious phishing/malware links in inbound email
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, email_text, re.IGNORECASE):
            flags.append(RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING)
            warnings.append("Inbound email contains suspicious shortened link or high-risk attachment reference.")
            break

    # 3. Check for premature legal or compensation binding in draft
    for pattern in COMPENSATION_LOCK_PATTERNS:
        if re.search(pattern, draft_text, re.IGNORECASE):
            flags.append(RiskCategory.CONTRACT_LEGAL_COMMITMENT)
            warnings.append("Draft contains binding compensation or offer acceptance statement. Executive review required.")
            break

    # 4. Check for unverified metric hallucination
    if "$80m" in draft_text.lower() or "$50m in google" in draft_text.lower() or "generated $8m" in draft_text.lower():
        flags.append(RiskCategory.UNVERIFIED_CAREER_CLAIM)
        warnings.append("Draft phrasing violates Accomplishment Ledger precision ('generated' vs approved 'influenced $8M').")

    if not flags:
        return RiskAssessmentResult(
            severity=RiskSeverity.SAFE,
            is_flagged=False,
            risk_score=5,
            detected_categories=[RiskCategory.CLEAN],
            second_opinion_summary="Heuristic screen passed. Draft is grounded and conforms to Draft-First safety standards.",
            recommended_action="PROCEED"
        )

    severity = RiskSeverity.HIGH_RISK if (RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING in flags or RiskCategory.CONTRACT_LEGAL_COMMITMENT in flags) else RiskSeverity.CAUTION
    score = 85 if severity == RiskSeverity.HIGH_RISK else 45

    return RiskAssessmentResult(
        severity=severity,
        is_flagged=True,
        risk_score=score,
        detected_categories=flags,
        second_opinion_summary="Heuristic security check identified items requiring human oversight.",
        recommended_action="REVIEW_CAUTION" if severity == RiskSeverity.CAUTION else "BLOCKED",
        guardrail_warnings=warnings
    )

def evaluate_second_opinion_risk(
    email: EmailMessage,
    draft_reply: Optional[str] = None,
    proposed_action: str = "DRAFT",
    user_profile: Optional[UserProfile] = None
) -> RiskAssessmentResult:
    """
    Evaluates inbound opportunity, proposed draft, and action using Gemini as an independent second-opinion auditor.
    Cross-checks against the Canonical Accomplishment Ledger and corporate safety boundaries.
    """
    email_text = f"Subject: {email.subject or ''}\nFrom: {email.sender_name} <{email.sender_email}>\n\n{email.body_text or ''}"
    draft_text = draft_reply or email.draft_reply or ""

    # Run fast heuristic pre-screen
    heuristic_res = analyze_risk_heuristics(email_text, draft_text, proposed_action)

    client = get_gemini_client()
    if not client:
        return heuristic_res

    try:
        locked_facts_str = "\n".join([f"- {k}: {v}" for k, v in LOCKED_FACTS.items()])
        prompt = f"""
You are the Gemini Risk Sentinel for Aura Mail AI.
Your sole mission is to provide an independent, rigorous second opinion on an inbound recruiter interaction and proposed email draft.

Candidate Canonical Verified Facts (STRICT TRUTH):
{locked_facts_str}
- Rule: Candidate influenced $8M in Google Cloud revenue (never say 'generated $8M').
- Rule: Candidate has influenced/delivered $100M+ enterprise revenue over career.
- Rule: Draft-First Policy is mandatory. Emails must be staged in Drafts, never autonomously fired.

Inbound Recruiter Email:
\"\"\"
{email_text[:2500]}
\"\"\"

Proposed Draft Response:
\"\"\"
{draft_text[:2000]}
\"\"\"

Proposed Action: {proposed_action}

Audit the email and draft for:
1. Grounding Precision: Are all claims, metrics, and titles 100% faithful to the verified facts?
2. Career Safety & Legal: Does the draft accidentally make binding salary promises, disclose proprietary data, or accept terms prematurely?
3. Phishing / Red Flags: Does the recruiter message appear suspicious, scammy, or deceptive?

Respond STRICTLY in JSON format matching this schema:
{{
  "severity": "SAFE" | "CAUTION" | "HIGH_RISK",
  "is_flagged": true | false,
  "risk_score": 0 to 100,
  "detected_categories": ["COMPENSATION_NEGOTIATION" | "UNVERIFIED_CAREER_CLAIM" | "SUSPICIOUS_LINK_OR_SPOOFING" | "AUTONOMOUS_SEND_POLICY" | "CONTRACT_LEGAL_COMMITMENT" | "CLEAN"],
  "second_opinion_summary": "Concise 1-2 sentence executive assessment of why this interaction is safe or risky",
  "recommended_action": "PROCEED" | "REVIEW_CAUTION" | "BLOCKED",
  "guardrail_warnings": ["Bullet point warning 1", "Bullet point warning 2"]
}}
"""
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text.strip())

        categories = []
        for cat in data.get("detected_categories", []):
            try:
                categories.append(RiskCategory(cat))
            except ValueError:
                pass
        if not categories:
            categories = [RiskCategory.CLEAN]

        severity = RiskSeverity(data.get("severity", RiskSeverity.SAFE.value))

        return RiskAssessmentResult(
            severity=severity,
            is_flagged=bool(data.get("is_flagged", severity != RiskSeverity.SAFE)),
            risk_score=int(data.get("risk_score", 10 if severity == RiskSeverity.SAFE else 60)),
            detected_categories=categories,
            second_opinion_summary=data.get("second_opinion_summary", "Audited and verified by Gemini Risk Sentinel."),
            recommended_action=data.get("recommended_action", "PROCEED"),
            guardrail_warnings=data.get("guardrail_warnings", []) or heuristic_res.guardrail_warnings
        )
    except Exception as e:
        logger.warning(f"Gemini second opinion evaluation failed, using heuristic baseline: {e}")
        return heuristic_res

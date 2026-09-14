"""
Aura Mail AI - Gemini Risk Sentinel & Second Opinion Evaluator
Provides monotonic, non-downgradable second-opinion risk assessments on inbound recruiter emails,
generated draft replies, and automated actions to ensure zero-hallucination,
legal/compensation safety, and strict draft-first enforcement.

SECURITY INVARIANT:
Deterministic security findings are strictly NON-DOWNGRADABLE.
Gemini may:
- add warnings
- add categories
- increase severity
- recommend a more restrictive action
Gemini may never:
- remove deterministic warnings
- remove deterministic categories
- decrease deterministic severity
- convert BLOCKED to PROCEED (or REVIEW_CAUTION to PROCEED)
- convert an identified suspicious link into clean status
"""

import re
import json
import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field

from backend.models import EmailMessage, UserProfile
from backend.canonical_engine import LOCKED_FACTS
from backend.safety_policy import (
    MailAction,
    ExecutionContext,
    TRANSMISSION_ACTIONS,
    BACKGROUND_CONTEXTS,
    resolve_mail_action
)

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

# Lattice order mappings for monotonic merge arithmetic
SEVERITY_ORDER: Dict[RiskSeverity, int] = {
    RiskSeverity.SAFE: 0,
    RiskSeverity.CAUTION: 1,
    RiskSeverity.HIGH_RISK: 2
}

ACTION_ORDER: Dict[str, int] = {
    "PROCEED": 0,
    "REVIEW_CAUTION": 1,
    "BLOCKED": 2
}

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

def merge_risk_assessments(
    heuristic: RiskAssessmentResult,
    gemini: Optional[RiskAssessmentResult] = None,
    error_note: Optional[str] = None
) -> RiskAssessmentResult:
    """
    Deterministically merges heuristic pre-screen findings with Gemini second-opinion results.
    Enforces the Monotonic Security Invariant:
    Deterministic security findings are strictly NON-DOWNGRADABLE.
    """
    if gemini is None:
        if error_note:
            heuristic_copy = heuristic.model_copy(deep=True)
            heuristic_copy.second_opinion_summary = f"{heuristic.second_opinion_summary} ({error_note})"
            return heuristic_copy
        return heuristic

    # 1. Monotonic Severity: max(heuristic, gemini)
    h_sev_rank = SEVERITY_ORDER.get(heuristic.severity, 0)
    g_sev_rank = SEVERITY_ORDER.get(gemini.severity, 0)
    merged_severity = heuristic.severity if h_sev_rank >= g_sev_rank else gemini.severity

    # 2. Monotonic Recommended Action: max(heuristic, gemini)
    h_act_rank = ACTION_ORDER.get(heuristic.recommended_action, 0)
    g_act_rank = ACTION_ORDER.get(gemini.recommended_action, 0)
    merged_action = heuristic.recommended_action if h_act_rank >= g_act_rank else gemini.recommended_action

    # 3. Monotonic Risk Score: max(heuristic, gemini)
    merged_score = max(heuristic.risk_score, gemini.risk_score)
    if merged_severity == RiskSeverity.HIGH_RISK and merged_score < 80:
        merged_score = max(heuristic.risk_score, 80)
    elif merged_severity == RiskSeverity.CAUTION and merged_score < 40:
        merged_score = max(heuristic.risk_score, 40)

    # 4. Monotonic Categories: Deterministic categories are strictly preserved; Gemini additions merged.
    merged_categories: List[RiskCategory] = list(heuristic.detected_categories)
    for cat in gemini.detected_categories:
        if cat not in merged_categories:
            merged_categories.append(cat)

    # If any non-CLEAN category exists, prune CLEAN
    if any(c != RiskCategory.CLEAN for c in merged_categories):
        merged_categories = [c for c in merged_categories if c != RiskCategory.CLEAN]

    if not merged_categories:
        merged_categories = [RiskCategory.CLEAN]

    # 5. Monotonic Guardrail Warnings: Deterministic warnings strictly preserved; new Gemini warnings appended.
    merged_warnings: List[str] = list(heuristic.guardrail_warnings)
    existing_warn_lower = {w.strip().lower() for w in merged_warnings}
    for w in gemini.guardrail_warnings:
        if w and w.strip().lower() not in existing_warn_lower:
            merged_warnings.append(w.strip())
            existing_warn_lower.add(w.strip().lower())

    # 6. Flagged status
    merged_flagged = (
        heuristic.is_flagged
        or gemini.is_flagged
        or merged_severity != RiskSeverity.SAFE
        or merged_action != "PROCEED"
        or any(c != RiskCategory.CLEAN for c in merged_categories)
    )

    # 7. Summary
    if error_note:
        summary = f"{heuristic.second_opinion_summary} ({error_note})"
    elif g_sev_rank < h_sev_rank or g_act_rank < h_act_rank:
        # Gemini attempted downgrade - retain heuristic summary and note override
        summary = (
            f"{heuristic.second_opinion_summary} "
            f"(Deterministic security guardrail retained: Gemini second opinion suggested {gemini.severity.value}/{gemini.recommended_action})."
        )
    else:
        summary = gemini.second_opinion_summary or heuristic.second_opinion_summary

    return RiskAssessmentResult(
        severity=merged_severity,
        is_flagged=merged_flagged,
        risk_score=merged_score,
        detected_categories=merged_categories,
        second_opinion_summary=summary,
        evaluator="Gemini Risk Sentinel (Second Opinion)",
        recommended_action=merged_action,
        guardrail_warnings=merged_warnings,
        timestamp=time.time()
    )

def analyze_risk_heuristics(
    email_text: str,
    draft_text: str,
    action: Union[MailAction, str] = "DRAFT",
    execution_context: Optional[Union[ExecutionContext, str]] = None
) -> RiskAssessmentResult:
    """Deterministic, local heuristic pre-screen for immediate security and policy checks."""
    flags: List[RiskCategory] = []
    warnings: List[str] = []

    # Resolve structured mail action and execution context
    resolved_action = resolve_mail_action(action)
    action_name = resolved_action.value if resolved_action else (str(action).upper() if action else "DRAFT")

    resolved_context: Optional[ExecutionContext] = None
    if isinstance(execution_context, ExecutionContext):
        resolved_context = execution_context
    elif isinstance(execution_context, str):
        try:
            resolved_context = ExecutionContext(execution_context.strip().upper())
        except ValueError:
            pass

    # 1. Check for autonomous send attempt or transmission action
    # Execution context and proposed privileged action determine policy without reliance on literal 'auto_pilot' string
    is_transmission_action = (
        (resolved_action is not None and resolved_action in TRANSMISSION_ACTIONS)
        or (action_name in {a.value for a in TRANSMISSION_ACTIONS} or action_name == "SEND")
    )
    is_background_ctx = resolved_context in BACKGROUND_CONTEXTS if resolved_context else False

    if is_transmission_action:
        flags.append(RiskCategory.AUTONOMOUS_SEND_POLICY)
        if is_background_ctx and resolved_context:
            warnings.append(
                f"Draft-First Policy: Background execution context '{resolved_context.value}' is strictly prohibited from transmitting email."
            )
        else:
            warnings.append(
                "Draft-First Policy: Direct mail transmission without human staging is prohibited."
            )

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
            recommended_action="PROCEED",
            guardrail_warnings=[]
        )

    severity = RiskSeverity.HIGH_RISK if (
        RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING in flags
        or RiskCategory.CONTRACT_LEGAL_COMMITMENT in flags
        or RiskCategory.AUTONOMOUS_SEND_POLICY in flags
    ) else RiskSeverity.CAUTION
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
    proposed_action: Union[MailAction, str] = "DRAFT",
    execution_context: Optional[Union[ExecutionContext, str]] = None,
    user_profile: Optional[UserProfile] = None
) -> RiskAssessmentResult:
    """
    Evaluates inbound opportunity, proposed draft, and action using Gemini as an independent second-opinion auditor.
    Cross-checks against the Canonical Accomplishment Ledger and corporate safety boundaries.
    Applies deterministic monotonic merge logic to guarantee security findings cannot be downgraded.
    """
    email_text = f"Subject: {email.subject or ''}\nFrom: {email.sender_name} <{email.sender_email}>\n\n{email.body_text or ''}"
    draft_text = draft_reply or email.draft_reply or ""

    # Run fast heuristic pre-screen
    heuristic_res = analyze_risk_heuristics(
        email_text=email_text,
        draft_text=draft_text,
        action=proposed_action,
        execution_context=execution_context
    )

    client = get_gemini_client()
    if not client:
        return merge_risk_assessments(heuristic_res, error_note="Gemini client unavailable; heuristic baseline enforced")

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
  "detected_categories": ["COMPENSATION_NEGOTIATION" | "UNVERIFIED_CAREER_CLAIM" | "SUSPICIOUS_LINK_OR_SPOOFING" | "AUTONOMOUS_SEND_POLICY" | "CONTRACT_LEGAL_COMMITMENT" | "PRIVACY_DATA_EXFILTRATION" | "CLEAN"],
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
        resp_text = (response.text or "").strip()
        if not resp_text:
            return merge_risk_assessments(heuristic_res, error_note="Empty response from Gemini; deterministic baseline enforced")

        data = json.loads(resp_text)
        if not isinstance(data, dict):
            return merge_risk_assessments(heuristic_res, error_note="Malformed non-object JSON from Gemini; deterministic baseline enforced")

        categories = []
        for cat in data.get("detected_categories", []):
            try:
                categories.append(RiskCategory(cat))
            except (ValueError, TypeError):
                pass
        if not categories:
            categories = [RiskCategory.CLEAN]

        raw_severity = data.get("severity", RiskSeverity.SAFE.value)
        try:
            severity = RiskSeverity(raw_severity)
        except (ValueError, TypeError):
            severity = RiskSeverity.SAFE

        raw_action = str(data.get("recommended_action", "PROCEED")).upper()
        if raw_action not in ACTION_ORDER:
            raw_action = "PROCEED"

        try:
            risk_score = int(data.get("risk_score", 10 if severity == RiskSeverity.SAFE else 60))
        except (ValueError, TypeError):
            risk_score = 10 if severity == RiskSeverity.SAFE else 60

        gemini_res = RiskAssessmentResult(
            severity=severity,
            is_flagged=bool(data.get("is_flagged", severity != RiskSeverity.SAFE)),
            risk_score=risk_score,
            detected_categories=categories,
            second_opinion_summary=str(data.get("second_opinion_summary", "Audited by Gemini Risk Sentinel.")),
            recommended_action=raw_action,
            guardrail_warnings=[str(w) for w in data.get("guardrail_warnings", []) if w]
        )

        return merge_risk_assessments(heuristic_res, gemini_res)
    except Exception as e:
        logger.warning(f"Gemini second opinion evaluation failed, enforcing monotonic heuristic baseline: {e}")
        return merge_risk_assessments(heuristic_res, error_note=f"Gemini evaluation error ({e}); deterministic baseline enforced")

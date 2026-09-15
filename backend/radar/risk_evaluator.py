"""
Aura Mail AI - Gemini Risk Sentinel & Second Opinion Evaluator
Provides monotonic, non-downgradable second-opinion risk assessments on inbound recruiter emails,
generated draft replies, and automated actions to ensure zero-hallucination,
legal/compensation safety, and strict draft-first enforcement.

SECURITY INVARIANTS:
1. Deterministic security findings are strictly NON-DOWNGRADABLE: FINAL_RISK >= DETERMINISTIC_RISK.
2. The final authoritative risk result is MONOTONIC + INTERNALLY COHERENT + DETERMINISTICALLY NORMALIZED.
3. CONTRADICTIONS RESOLVE UPWARD toward the more restrictive security posture. Never downward.
4. Risk evaluation NEVER grants transmission authorization: AURA TRANSMISSION IS PERMANENTLY FORBIDDEN.
"""

import re
import json
import time
import math
import logging
from enum import Enum
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field

from backend.models import EmailMessage, UserProfile
from backend.canonical_engine import LOCKED_FACTS
from backend.canonical_grounding import (
    validate_canonical_grounding,
    GroundingValidationResult,
    ClaimCategory
)
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

HIGH_RISK_CATEGORIES = {
    RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING,
    RiskCategory.CONTRACT_LEGAL_COMMITMENT,
    RiskCategory.AUTONOMOUS_SEND_POLICY,
    RiskCategory.PRIVACY_DATA_EXFILTRATION,
}

CAUTION_CATEGORIES = {
    RiskCategory.UNVERIFIED_CAREER_CLAIM,
    RiskCategory.COMPENSATION_NEGOTIATION,
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

def safe_parse_risk_score(val: Any, default_score: int = 0) -> int:
    """
    Strictly validates and parses risk score as a bounded integer in [0, 100].
    Rejects booleans (isinstance(True, int) is True in Python), strings, nulls,
    NaN, Infinity, and non-numeric structures, falling back to default_score.
    """
    if isinstance(val, bool) or val is None:
        return default_score
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return default_score
        clamped = int(round(val))
        if clamped < 0:
            return 0
        if clamped > 100:
            return 100
        return clamped
    return default_score

def normalize_risk_assessment(result: RiskAssessmentResult) -> RiskAssessmentResult:
    """
    Authoritative single normalization choke point enforcing:
    MONOTONIC + INTERNALLY COHERENT + DETERMINISTICALLY NORMALIZED

    Invariants:
    1. CONTRADICTIONS RESOLVE UPWARD toward the more restrictive security posture.
    2. Severity, action, score, categories, and warnings are mutually consistent.
    3. Operation is strictly idempotent: normalize(normalize(x)) == normalize(x).
    """
    if not isinstance(result, RiskAssessmentResult):
        raise TypeError("normalize_risk_assessment requires a RiskAssessmentResult instance.")

    # 1. Parse & validate fields safely
    raw_score = safe_parse_risk_score(result.risk_score, 0)

    # Severity signal
    sev_rank = SEVERITY_ORDER.get(result.severity, 0)

    # Action signal
    act_rank = ACTION_ORDER.get(result.recommended_action, 0)

    # Score signal (score maps to severity: 0-39 -> 0, 40-79 -> 1, 80-100 -> 2)
    if raw_score >= 80:
        score_rank = 2
    elif raw_score >= 40:
        score_rank = 1
    else:
        score_rank = 0

    # Categories signal
    cat_rank = 0
    clean_categories: List[RiskCategory] = []
    for cat in result.detected_categories:
        if isinstance(cat, RiskCategory):
            clean_categories.append(cat)
        elif isinstance(cat, str) and cat.strip().upper() in RiskCategory.__members__:
            clean_categories.append(RiskCategory[cat.strip().upper()])

    if any(c in HIGH_RISK_CATEGORIES for c in clean_categories):
        cat_rank = 2
    elif any(c in CAUTION_CATEGORIES or (c != RiskCategory.CLEAN) for c in clean_categories):
        cat_rank = 1

    # Flag signal
    flag_rank = 1 if result.is_flagged else 0

    # Strongest valid security rank (Universal Upward Normalization)
    canonical_rank = max(sev_rank, act_rank, score_rank, cat_rank, flag_rank)

    # 2. Derive normalized authoritative states
    if canonical_rank == 2:
        norm_severity = RiskSeverity.HIGH_RISK
        norm_action = "BLOCKED"
        norm_score = max(raw_score, 80)
        norm_flagged = True
        norm_categories = [c for c in clean_categories if c != RiskCategory.CLEAN]
    elif canonical_rank == 1:
        norm_severity = RiskSeverity.CAUTION
        norm_action = "REVIEW_CAUTION"
        norm_score = max(raw_score, 40)
        norm_flagged = True
        norm_categories = [c for c in clean_categories if c != RiskCategory.CLEAN]
    else:
        norm_severity = RiskSeverity.SAFE
        norm_action = "PROCEED"
        norm_score = min(raw_score, 39)
        norm_flagged = False
        norm_categories = [RiskCategory.CLEAN]

    # 3. Clean and deduplicate warnings
    norm_warnings: List[str] = []
    seen_warn = set()
    for w in result.guardrail_warnings:
        if isinstance(w, str) and w.strip():
            w_clean = w.strip()
            w_lower = w_clean.lower()
            if w_lower not in seen_warn:
                seen_warn.add(w_lower)
                norm_warnings.append(w_clean)

    return RiskAssessmentResult(
        severity=norm_severity,
        is_flagged=norm_flagged,
        risk_score=norm_score,
        detected_categories=norm_categories,
        second_opinion_summary=result.second_opinion_summary,
        evaluator=result.evaluator,
        recommended_action=norm_action,
        guardrail_warnings=norm_warnings,
        timestamp=result.timestamp
    )

def merge_risk_assessments(
    heuristic: RiskAssessmentResult,
    gemini: Optional[RiskAssessmentResult] = None,
    error_note: Optional[str] = None
) -> RiskAssessmentResult:
    """
    Deterministically merges heuristic pre-screen findings with Gemini second-opinion results,
    then routes through canonical normalization.
    Enforces the Monotonic Security Invariant: FINAL_RISK >= DETERMINISTIC_RISK
    """
    # Normalize heuristic baseline first to guarantee solid floor
    norm_heuristic = normalize_risk_assessment(heuristic)

    if gemini is None:
        if error_note:
            res_copy = norm_heuristic.model_copy(deep=True)
            res_copy.second_opinion_summary = f"{norm_heuristic.second_opinion_summary} ({error_note})"
            return normalize_risk_assessment(res_copy)
        return norm_heuristic

    # 1. Monotonic Severity: max(heuristic, gemini)
    h_sev_rank = SEVERITY_ORDER.get(norm_heuristic.severity, 0)
    g_sev_rank = SEVERITY_ORDER.get(gemini.severity, 0) if isinstance(gemini.severity, RiskSeverity) else 0
    merged_severity = norm_heuristic.severity if h_sev_rank >= g_sev_rank else gemini.severity

    # 2. Monotonic Recommended Action: max(heuristic, gemini)
    h_act_rank = ACTION_ORDER.get(norm_heuristic.recommended_action, 0)
    g_act_rank = ACTION_ORDER.get(gemini.recommended_action, 0) if isinstance(gemini.recommended_action, str) else 0
    merged_action = norm_heuristic.recommended_action if h_act_rank >= g_act_rank else gemini.recommended_action

    # 3. Monotonic Risk Score: max(heuristic, gemini) with safe parsing
    g_score = safe_parse_risk_score(gemini.risk_score, 0)
    merged_score = max(norm_heuristic.risk_score, g_score)

    # 4. Monotonic Categories: Deterministic categories strictly preserved; Gemini additions merged.
    merged_categories: List[RiskCategory] = list(norm_heuristic.detected_categories)
    for cat in gemini.detected_categories:
        if isinstance(cat, RiskCategory) and cat not in merged_categories:
            merged_categories.append(cat)
        elif isinstance(cat, str) and cat.strip().upper() in RiskCategory.__members__:
            parsed_cat = RiskCategory[cat.strip().upper()]
            if parsed_cat not in merged_categories:
                merged_categories.append(parsed_cat)

    # 5. Monotonic Guardrail Warnings: Deterministic warnings strictly preserved; new Gemini warnings appended.
    merged_warnings: List[str] = list(norm_heuristic.guardrail_warnings)
    existing_warn_lower = {w.strip().lower() for w in merged_warnings}
    for w in gemini.guardrail_warnings:
        if isinstance(w, str) and w.strip() and w.strip().lower() not in existing_warn_lower:
            merged_warnings.append(w.strip())
            existing_warn_lower.add(w.strip().lower())

    # 6. Flagged status
    merged_flagged = norm_heuristic.is_flagged or bool(gemini.is_flagged)

    # 7. Summary
    if error_note:
        summary = f"{norm_heuristic.second_opinion_summary} ({error_note})"
    elif g_sev_rank < h_sev_rank or g_act_rank < h_act_rank:
        summary = (
            f"{norm_heuristic.second_opinion_summary} "
            f"(Deterministic security guardrail retained: Gemini second opinion suggested {gemini.severity.value if isinstance(gemini.severity, RiskSeverity) else gemini.severity}/{gemini.recommended_action})."
        )
    else:
        summary = gemini.second_opinion_summary or norm_heuristic.second_opinion_summary

    raw_merged = RiskAssessmentResult(
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

    # Single Authoritative Exit Point: Normalize the merged assessment
    return normalize_risk_assessment(raw_merged)

def analyze_risk_heuristics(
    email_text: str,
    draft_text: str,
    action: Union[MailAction, str] = "DRAFT",
    execution_context: Optional[Union[ExecutionContext, str]] = None
) -> RiskAssessmentResult:
    """
    Deterministic, local heuristic pre-screen for immediate security and policy checks.
    Always returns a normalized RiskAssessmentResult.
    """
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
    # PRIVILEGE / SEND INVARIANT: All Aura SEND proposals are HIGH_RISK + BLOCKED regardless of execution context
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

    # 4. Check for unverified career claims and hallucinated metrics via deterministic canonical grounding
    if draft_text:
        grounding_res = validate_canonical_grounding(draft_text)
        if not grounding_res.is_grounded:
            flags.append(RiskCategory.UNVERIFIED_CAREER_CLAIM)
            for u in grounding_res.unsupported_claims:
                warnings.append(f"Canonical Grounding Violation: {u.reason}")

    if not flags:
        raw_res = RiskAssessmentResult(
            severity=RiskSeverity.SAFE,
            is_flagged=False,
            risk_score=5,
            detected_categories=[RiskCategory.CLEAN],
            second_opinion_summary="Heuristic screen passed. Draft is canonically grounded and conforms to Draft-First safety standards.",
            recommended_action="PROCEED",
            guardrail_warnings=[]
        )
        return normalize_risk_assessment(raw_res)

    severity = RiskSeverity.HIGH_RISK if (
        RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING in flags
        or RiskCategory.CONTRACT_LEGAL_COMMITMENT in flags
        or RiskCategory.AUTONOMOUS_SEND_POLICY in flags
    ) else RiskSeverity.CAUTION
    score = 85 if severity == RiskSeverity.HIGH_RISK else 45

    raw_res = RiskAssessmentResult(
        severity=severity,
        is_flagged=True,
        risk_score=score,
        detected_categories=flags,
        second_opinion_summary="Heuristic security check identified items requiring human oversight.",
        recommended_action="REVIEW_CAUTION" if severity == RiskSeverity.CAUTION else "BLOCKED",
        guardrail_warnings=warnings
    )
    return normalize_risk_assessment(raw_res)

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
    Applies deterministic monotonic merge logic and canonical normalization to guarantee security findings cannot be downgraded.
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

        # Strict extraction & type validation of Gemini fields
        categories: List[RiskCategory] = []
        raw_categories = data.get("detected_categories")
        if isinstance(raw_categories, list):
            for cat in raw_categories:
                if isinstance(cat, str) and cat.strip().upper() in RiskCategory.__members__:
                    categories.append(RiskCategory[cat.strip().upper()])
        if not categories:
            categories = [RiskCategory.CLEAN]

        raw_severity = data.get("severity")
        if isinstance(raw_severity, str) and raw_severity.strip().upper() in RiskSeverity.__members__:
            severity = RiskSeverity[raw_severity.strip().upper()]
        else:
            severity = RiskSeverity.SAFE

        raw_action = data.get("recommended_action")
        if isinstance(raw_action, str) and raw_action.strip().upper() in ACTION_ORDER:
            action_val = raw_action.strip().upper()
        else:
            action_val = "PROCEED"

        raw_score_val = data.get("risk_score")
        default_score = 10 if severity == RiskSeverity.SAFE else (85 if severity == RiskSeverity.HIGH_RISK else 45)
        risk_score = safe_parse_risk_score(raw_score_val, default_score)

        raw_flagged = data.get("is_flagged")
        is_flagged = bool(raw_flagged) if isinstance(raw_flagged, bool) else (severity != RiskSeverity.SAFE)

        raw_warnings = data.get("guardrail_warnings")
        valid_warnings = [str(w).strip() for w in raw_warnings if isinstance(w, str) and w.strip()] if isinstance(raw_warnings, list) else []

        raw_summary = data.get("second_opinion_summary")
        summary_str = str(raw_summary).strip() if isinstance(raw_summary, str) and raw_summary.strip() else "Audited by Gemini Risk Sentinel."

        gemini_res = RiskAssessmentResult(
            severity=severity,
            is_flagged=is_flagged,
            risk_score=risk_score,
            detected_categories=categories,
            second_opinion_summary=summary_str,
            recommended_action=action_val,
            guardrail_warnings=valid_warnings
        )

        return merge_risk_assessments(heuristic_res, gemini_res)
    except Exception as e:
        logger.warning(f"Gemini second opinion evaluation failed, enforcing monotonic heuristic baseline: {e}")
        return merge_risk_assessments(heuristic_res, error_note=f"Gemini evaluation error ({e}); deterministic baseline enforced")

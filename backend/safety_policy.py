"""
Aura Mail AI - Mail Safety Policy Model & Enforcement Engine
Implements fail-closed safety modes (DRAFT_ONLY vs MANUAL_SEND_ONLY),
execution context trust boundaries, and permanent no-send invariants.
"""

import logging
from enum import Enum
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field

logger = logging.getLogger("aura.safety_policy")

class MailSafetyMode(str, Enum):
    """
    Explicit backend mail safety modes:
    - DRAFT_ONLY (default, fail-closed): Analysis, drafting, UI pre-filling, and clipboard copying allowed; all app sends blocked.
    - MANUAL_SEND_ONLY: Transmit email only after explicit interactive human send action. Background send still strictly forbidden.
    """
    DRAFT_ONLY = "DRAFT_ONLY"
    MANUAL_SEND_ONLY = "MANUAL_SEND_ONLY"


class ExecutionContext(str, Enum):
    """Execution context hierarchy representing the originator of a mail action."""
    DAEMON = "DAEMON"
    BACKGROUND_RADAR = "BACKGROUND_RADAR"
    SCHEDULED_JOB = "SCHEDULED_JOB"
    AI_AGENT = "AI_AGENT"
    OUTLOOK_INTERACTIVE_USER = "OUTLOOK_INTERACTIVE_USER"
    DASHBOARD_INTERACTIVE_USER = "DASHBOARD_INTERACTIVE_USER"
    UNAUTHENTICATED_API = "UNAUTHENTICATED_API"


# Background contexts where SEND is permanently forbidden by invariant
BACKGROUND_CONTEXTS = {
    ExecutionContext.DAEMON,
    ExecutionContext.BACKGROUND_RADAR,
    ExecutionContext.SCHEDULED_JOB,
    ExecutionContext.AI_AGENT,
    ExecutionContext.UNAUTHENTICATED_API
}

INTERACTIVE_HUMAN_CONTEXTS = {
    ExecutionContext.OUTLOOK_INTERACTIVE_USER,
    ExecutionContext.DASHBOARD_INTERACTIVE_USER
}


class PolicyEvaluationResult(BaseModel):
    """Structured decision output from the Mail Safety Policy Engine."""
    allowed: bool
    safety_mode: MailSafetyMode
    context: ExecutionContext
    action: str
    reason: str
    is_send_blocked: bool = False


def resolve_safety_mode(raw_value: Any) -> MailSafetyMode:
    """
    Fail-closed resolution of Mail Safety Mode.
    Guarantees that missing, malformed, unknown, or corrupted values
    ALWAYS resolve to DRAFT_ONLY. Never falls forward to MANUAL_SEND_ONLY.
    """
    if not raw_value or not isinstance(raw_value, str):
        return MailSafetyMode.DRAFT_ONLY

    normalized = raw_value.strip().upper()
    
    # Handle legacy alias mapping: SAFE_REVIEW -> DRAFT_ONLY
    if normalized in ["DRAFT_ONLY", "SAFE_REVIEW", "DRAFT"]:
        return MailSafetyMode.DRAFT_ONLY
    
    if normalized == "MANUAL_SEND_ONLY":
        return MailSafetyMode.MANUAL_SEND_ONLY

    # Any unknown or unhandled string fails closed to DRAFT_ONLY
    logger.warning(f"Unrecognized safety mode '{raw_value}' failed closed to DRAFT_ONLY.")
    return MailSafetyMode.DRAFT_ONLY


def get_active_safety_mode() -> MailSafetyMode:
    """
    Retrieves the current Mail Safety Mode from backend settings.
    Enforces fail-closed resolution on configuration read errors.
    """
    try:
        from backend.config import load_settings
        settings = load_settings()
        user_prof = settings.get("user_profile", {})
        raw_mode = user_prof.get("safety_mode", settings.get("safety_mode"))
        return resolve_safety_mode(raw_mode)
    except Exception as e:
        logger.error(f"Failed to read safety mode from configuration ({e}); failing closed to DRAFT_ONLY.")
        return MailSafetyMode.DRAFT_ONLY


def set_safety_mode(new_mode: MailSafetyMode, human_actor_context: ExecutionContext) -> MailSafetyMode:
    """
    Updates the Mail Safety Mode in trusted backend configuration.
    Enforces trust boundary: only interactive human contexts may update policy.
    Autonomous/background contexts cannot modify safety configuration.
    """
    if human_actor_context not in INTERACTIVE_HUMAN_CONTEXTS:
        raise PermissionError(
            f"Trust Boundary Violation: Execution context '{human_actor_context.value}' "
            "is not authorized to modify Mail Safety Policy."
        )

    resolved = resolve_safety_mode(new_mode.value if isinstance(new_mode, MailSafetyMode) else new_mode)
    
    from backend.config import load_settings, save_settings
    settings = load_settings()
    if "user_profile" not in settings:
        settings["user_profile"] = {}
    settings["user_profile"]["safety_mode"] = resolved.value
    settings["safety_mode"] = resolved.value
    save_settings(settings)
    
    logger.info(f"Mail Safety Policy updated to {resolved.value} by {human_actor_context.value}.")
    return resolved


def evaluate_mail_action(
    action: str,
    context: ExecutionContext,
    safety_mode: Optional[MailSafetyMode] = None
) -> PolicyEvaluationResult:
    """
    Core policy decision engine implementing the Acceptance Matrix:

    Execution Context              | DRAFT_ONLY                  | MANUAL_SEND_ONLY
    -------------------------------|-----------------------------|-----------------------------
    Daemon                         | Draft only                  | Draft only
    Background radar               | Draft only                  | Draft only
    Scheduled job                  | Draft only                  | Draft only
    AI/agent invocation            | Draft only                  | Draft only
    Outlook interactive user       | Draft/review                | Explicit human send permitted
    Aura dashboard interactive     | Send blocked                | Explicit human send permitted
    Unauthenticated/direct API     | Blocked                     | Blocked
    """
    mode = safety_mode if safety_mode is not None else get_active_safety_mode()
    action_normalized = action.strip().upper()

    is_send_operation = action_normalized in {
        "SEND", "SEND_REPLY", "SEND_EMAIL", "DISPATCH_EMAIL", "FORWARD_EMAIL"
    }

    # Non-send operations (Drafting, Triage, Calendar Booking, Analysis) are always permitted
    if not is_send_operation:
        return PolicyEvaluationResult(
            allowed=True,
            safety_mode=mode,
            context=context,
            action=action,
            reason=f"Action '{action}' is a staging/analysis operation and is permitted under {mode.value} policy.",
            is_send_blocked=False
        )

    # Permanent Invariant: Background execution CAN NEVER send
    if context in BACKGROUND_CONTEXTS:
        return PolicyEvaluationResult(
            allowed=False,
            safety_mode=mode,
            context=context,
            action=action,
            reason=(
                f"BACKGROUND EXECUTION -> SEND FORBIDDEN: Execution context '{context.value}' "
                "is strictly prohibited from transmitting email regardless of safety mode."
            ),
            is_send_blocked=True
        )

    # Interactive Human Contexts: Evaluated based on active safety mode
    if context in INTERACTIVE_HUMAN_CONTEXTS:
        if mode == MailSafetyMode.DRAFT_ONLY:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=mode,
                context=context,
                action=action,
                reason=(
                    f"Policy Enforcement: Active safety mode is DRAFT_ONLY. "
                    "Direct send operations are disabled; stage as draft for manual review."
                ),
                is_send_blocked=True
            )
        elif mode == MailSafetyMode.MANUAL_SEND_ONLY:
            return PolicyEvaluationResult(
                allowed=True,
                safety_mode=mode,
                context=context,
                action=action,
                reason=(
                    f"Explicit interactive human send permitted under MANUAL_SEND_ONLY policy "
                    f"from context '{context.value}'."
                ),
                is_send_blocked=False
            )

    # Any other unclassified or unauthenticated context is denied
    return PolicyEvaluationResult(
        allowed=False,
        safety_mode=mode,
        context=context,
        action=action,
        reason=f"Access Denied: Unrecognized execution context '{context}'. Send operation blocked.",
        is_send_blocked=True
    )

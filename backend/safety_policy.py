"""
Aura Mail AI - Mail Safety Policy Model & Enforcement Engine (Phase 3 Native-Send Remediation).
Implements fail-closed safety modes (DRAFT_ONLY vs MANUAL_SEND_ONLY),
explicit action classifications with fail-closed unknown action denial,
and the permanent architectural invariant:
ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN.
Aura prepares and stages drafts; final transmission occurs exclusively through native mail clients.
"""

import logging
from enum import Enum
from typing import Optional, Any, Dict, Union, Set
from pydantic import BaseModel, Field

logger = logging.getLogger("aura.safety_policy")


class MailSafetyMode(str, Enum):
    """
    Explicit backend mail safety modes:
    - DRAFT_ONLY (default, fail-closed): Analysis, drafting, UI pre-filling, and draft staging allowed; all app sends blocked.
    - MANUAL_SEND_ONLY: Prepares and stages drafts in cloud mailbox / native compose surface for user review and native client transmission. Aura direct send is forbidden.
    """
    DRAFT_ONLY = "DRAFT_ONLY"
    MANUAL_SEND_ONLY = "MANUAL_SEND_ONLY"


class ExecutionContext(str, Enum):
    """Execution context hierarchy representing the originator of a mail action (used for logging and diagnostics)."""
    DAEMON = "DAEMON"
    BACKGROUND_RADAR = "BACKGROUND_RADAR"
    SCHEDULED_JOB = "SCHEDULED_JOB"
    AI_AGENT = "AI_AGENT"
    OUTLOOK_INTERACTIVE_USER = "OUTLOOK_INTERACTIVE_USER"
    DASHBOARD_INTERACTIVE_USER = "DASHBOARD_INTERACTIVE_USER"
    UNAUTHENTICATED_API = "UNAUTHENTICATED_API"


class MailAction(str, Enum):
    """
    Explicit mail operations classified into safe staging vs transmission actions.
    Any action outside this explicit taxonomy fails closed.
    """
    # Safe Staging & Analysis Operations (Non-Transmission)
    CREATE_DRAFT = "CREATE_DRAFT"
    GENERATE_DRAFT = "GENERATE_DRAFT"
    ANALYZE = "ANALYZE"
    TRIAGE = "TRIAGE"
    CALENDAR_AVAILABILITY = "CALENDAR_AVAILABILITY"
    READ_EMAIL = "READ_EMAIL"
    STAGE_RESPONSE = "STAGE_RESPONSE"

    # Transmission / Sending Operations (Permanently Forbidden from Aura Execution)
    SEND_EMAIL = "SEND_EMAIL"
    SEND_REPLY = "SEND_REPLY"
    FORWARD_EMAIL = "FORWARD_EMAIL"
    TRANSMIT_MAIL = "TRANSMIT_MAIL"
    SEND_MESSAGE = "SEND_MESSAGE"
    DELIVER_EMAIL = "DELIVER_EMAIL"
    SMTP_SEND = "SMTP_SEND"
    DISPATCH_EMAIL = "DISPATCH_EMAIL"
    SEND = "SEND"


# Explicit Classification Sets
SAFE_STAGING_ACTIONS: Set[MailAction] = {
    MailAction.CREATE_DRAFT,
    MailAction.GENERATE_DRAFT,
    MailAction.ANALYZE,
    MailAction.TRIAGE,
    MailAction.CALENDAR_AVAILABILITY,
    MailAction.READ_EMAIL,
    MailAction.STAGE_RESPONSE,
}

TRANSMISSION_ACTIONS: Set[MailAction] = {
    MailAction.SEND_EMAIL,
    MailAction.SEND_REPLY,
    MailAction.FORWARD_EMAIL,
    MailAction.TRANSMIT_MAIL,
    MailAction.SEND_MESSAGE,
    MailAction.DELIVER_EMAIL,
    MailAction.SMTP_SEND,
    MailAction.DISPATCH_EMAIL,
    MailAction.SEND,
}

# Background contexts where SEND is permanently forbidden by invariant
BACKGROUND_CONTEXTS: Set[ExecutionContext] = {
    ExecutionContext.DAEMON,
    ExecutionContext.BACKGROUND_RADAR,
    ExecutionContext.SCHEDULED_JOB,
    ExecutionContext.AI_AGENT,
    ExecutionContext.UNAUTHENTICATED_API
}

INTERACTIVE_HUMAN_CONTEXTS: Set[ExecutionContext] = {
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


def resolve_mail_action(raw_action: Any) -> Optional[MailAction]:
    """
    Strict resolution of requested mail action against the explicit MailAction taxonomy.
    Returns None for any unclassified or unknown action string so the engine can fail closed.
    """
    if isinstance(raw_action, MailAction):
        return raw_action

    if isinstance(raw_action, str):
        normalized = raw_action.strip().upper()
        if normalized in MailAction.__members__:
            return MailAction[normalized]
        for action in MailAction:
            if action.value == normalized:
                return action

    return None


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


def set_safety_mode(new_mode: Union[MailSafetyMode, str], human_actor_context: ExecutionContext) -> MailSafetyMode:
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
    action: Union[MailAction, str],
    context: ExecutionContext = ExecutionContext.UNAUTHENTICATED_API,
    safety_mode: Optional[MailSafetyMode] = None,
) -> PolicyEvaluationResult:
    """
    Core policy decision engine implementing the Zero-Transmission Invariant:

    Execution Context              | DRAFT_ONLY                  | MANUAL_SEND_ONLY
    -------------------------------|-----------------------------|-----------------------------
    Daemon                         | Draft only                  | Draft only
    Background radar               | Draft only                  | Draft only
    Scheduled job                  | Draft only                  | Draft only
    AI/agent invocation            | Draft only                  | Draft only
    Outlook interactive user       | Draft/review                | Draft staged; Native Send required
    Aura dashboard interactive     | Draft/review                | Draft staged; Native Send required
    Unauthenticated/direct API     | Blocked                     | Blocked

    PERMANENT INVARIANT:
    ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN
    Aura prepares and stages drafts; human transmits exclusively through the native mail client.
    """
    mode = safety_mode if safety_mode is not None else get_active_safety_mode()
    resolved_action = resolve_mail_action(action)
    action_str = resolved_action.value if resolved_action else str(action)

    # 1. FAIL CLOSED: Unknown / unclassified actions are strictly denied
    if resolved_action is None:
        return PolicyEvaluationResult(
            allowed=False,
            safety_mode=mode,
            context=context,
            action=action_str,
            reason=f"Policy Enforcement (Fail-Closed): Unrecognized or unclassified action '{action}' is denied by default.",
            is_send_blocked=False
        )

    # 2. Known Safe Staging/Analysis Operations: Permitted across all contexts
    if resolved_action in SAFE_STAGING_ACTIONS:
        return PolicyEvaluationResult(
            allowed=True,
            safety_mode=mode,
            context=context,
            action=action_str,
            reason=f"Action '{action_str}' is a recognized staging/analysis operation and is permitted under {mode.value} policy.",
            is_send_blocked=False
        )

    # 3. Transmission Operations: Unconditionally DENIED across all modes and execution contexts
    if resolved_action in TRANSMISSION_ACTIONS:
        if context in BACKGROUND_CONTEXTS:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=mode,
                context=context,
                action=action_str,
                reason=(
                    f"BACKGROUND EXECUTION -> SEND FORBIDDEN: Execution context '{context.value}' "
                    "is strictly prohibited from transmitting email."
                ),
                is_send_blocked=True
            )

        if mode == MailSafetyMode.DRAFT_ONLY:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=mode,
                context=context,
                action=action_str,
                reason=(
                    "Policy Enforcement (DRAFT_ONLY): Active safety mode is DRAFT_ONLY. "
                    "Direct mail transmission is disabled; stage as draft for manual review."
                ),
                is_send_blocked=True
            )

        # MANUAL_SEND_ONLY or any other mode: Aura direct transmission is permanently forbidden
        return PolicyEvaluationResult(
            allowed=False,
            safety_mode=mode,
            context=context,
            action=action_str,
            reason=(
                "AURA DIRECT TRANSMISSION FORBIDDEN: Aura does not directly transmit outbound mail. "
                "Outbound mail is prepared and staged in your cloud Drafts folder for review and native client transmission."
            ),
            is_send_blocked=True
        )

    # Fallback fail-closed
    return PolicyEvaluationResult(
        allowed=False,
        safety_mode=mode,
        context=context,
        action=action_str,
        reason=f"Access Denied: Action '{action_str}' is denied by default.",
        is_send_blocked=True
    )

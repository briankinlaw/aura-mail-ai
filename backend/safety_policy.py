"""
Aura Mail AI - Mail Safety Policy Model & Enforcement Engine (Phase 1 & Phase 3 Remediation).
Implements fail-closed safety modes (DRAFT_ONLY vs MANUAL_SEND_ONLY),
explicit action classifications with fail-closed unknown action denial,
discrete interactive human send authorization tickets, cryptographic payload binding,
and permanent background execution no-send invariants.
"""

import logging
import threading
import time
import secrets
import hashlib
import json
from enum import Enum
from typing import Optional, Any, Dict, Union, Set
from pydantic import BaseModel, Field

logger = logging.getLogger("aura.safety_policy")


class MailSafetyMode(str, Enum):
    """
    Explicit backend mail safety modes:
    - DRAFT_ONLY (default, fail-closed): Analysis, drafting, UI pre-filling, and clipboard copying allowed; all app sends blocked.
    - MANUAL_SEND_ONLY: Transmit email only after independently verifiable, explicit, interactive human authorization. Background send still strictly forbidden.
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

    # Transmission / Sending Operations
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


class SendAuthorizationTicket(BaseModel):
    """
    Discrete, short-lived, single-use send authorization credential.
    Bound to a specific account, message, outbound payload digest, and operation.
    """
    ticket_id: str
    account_id: str
    message_id: str
    operation: str = "SEND_REPLY"
    payload_digest: str
    created_at: float
    expires_at: float
    consumed: bool = False


# Thread-safe in-memory authorization registry
_AUTH_LOCK = threading.Lock()
_AUTHORIZATION_REGISTRY: Dict[str, SendAuthorizationTicket] = {}
DEFAULT_TICKET_TTL_SECONDS: float = 120.0  # 2 minutes


def clear_authorization_registry() -> None:
    """Clears the ephemeral authorization registry (used in test setup/teardown)."""
    with _AUTH_LOCK:
        _AUTHORIZATION_REGISTRY.clear()


def compute_outbound_payload_digest(
    account_id: str,
    message_id: str,
    to_email: str,
    subject: str,
    reply_body: str,
    resume_filename: Optional[str] = None,
) -> str:
    """
    Computes a canonical SHA-256 digest of the outbound mail payload to guarantee content integrity
    and prevent Time-of-Check to Time-of-Use (TOCTOU) mutations between human approval and send.
    """
    canonical_dict = {
        "account_id": (account_id or "").strip().lower(),
        "message_id": (message_id or "").strip(),
        "operation": "SEND_REPLY",
        "reply_body": (reply_body or "").strip(),
        "resume_filename": (resume_filename or "").strip() if resume_filename else None,
        "subject": (subject or "").strip(),
        "to_email": (to_email or "").strip().lower(),
    }
    serialized = json.dumps(canonical_dict, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def issue_send_authorization(
    account_id: str,
    message_id: str,
    to_email: str,
    subject: str,
    reply_body: str,
    resume_filename: Optional[str] = None,
    ttl_seconds: float = DEFAULT_TICKET_TTL_SECONDS,
    originating_context: ExecutionContext = ExecutionContext.UNAUTHENTICATED_API,
) -> SendAuthorizationTicket:
    """
    Issues a discrete, short-lived, single-use send authorization ticket for an explicit
    interactive human send action.

    TRUST BOUNDARIES ENFORCED:
    1. Active safety mode MUST be MANUAL_SEND_ONLY (DRAFT_ONLY strictly forbids issuance).
    2. Originating context MUST be an INTERACTIVE_HUMAN_CONTEXT (BACKGROUND_CONTEXTS strictly forbidden).
    3. Cryptographically unpredictable nonce (256-bit entropy via secrets.token_urlsafe).
    4. Exact payload digest binding (preventing recipient, subject, body, or attachment tampering).
    """
    active_mode = get_active_safety_mode()
    if active_mode != MailSafetyMode.MANUAL_SEND_ONLY:
        raise PermissionError(
            f"Send Authorization Denied: Active safety mode is {active_mode.value}. "
            "Send authorization tickets cannot be issued when policy is DRAFT_ONLY."
        )

    if originating_context not in INTERACTIVE_HUMAN_CONTEXTS:
        raise PermissionError(
            f"Send Authorization Denied: Execution context '{originating_context.value}' "
            "is not authorized to request send authorization. Background execution cannot authorize mail sends."
        )

    digest = compute_outbound_payload_digest(
        account_id=account_id,
        message_id=message_id,
        to_email=to_email,
        subject=subject,
        reply_body=reply_body,
        resume_filename=resume_filename,
    )

    ticket_id = f"sat_{secrets.token_urlsafe(32)}"
    now = time.time()
    ticket = SendAuthorizationTicket(
        ticket_id=ticket_id,
        account_id=(account_id or "").strip().lower(),
        message_id=(message_id or "").strip(),
        operation="SEND_REPLY",
        payload_digest=digest,
        created_at=now,
        expires_at=now + ttl_seconds,
        consumed=False
    )

    with _AUTH_LOCK:
        # Purge expired entries
        expired = [k for k, v in _AUTHORIZATION_REGISTRY.items() if v.expires_at < now]
        for k in expired:
            _AUTHORIZATION_REGISTRY.pop(k, None)
        _AUTHORIZATION_REGISTRY[ticket_id] = ticket

    logger.info(f"Issued SendAuthorizationTicket '{ticket_id}' for message '{message_id}', account '{account_id}'.")
    return ticket


def validate_and_consume_send_authorization(
    account_id: str,
    message_id: str,
    to_email: str,
    subject: str,
    reply_body: str,
    resume_filename: Optional[str] = None,
    authorization: Optional[Union[SendAuthorizationTicket, str]] = None,
) -> PolicyEvaluationResult:
    """
    Validates and atomically consumes a SendAuthorizationTicket for a SEND_REPLY operation.

    ENFORCEMENT RULES:
    1. Active safety mode must be MANUAL_SEND_ONLY (DRAFT_ONLY unconditionally denies).
    2. Authorization ticket must be provided, non-empty, and recognized in registry.
    3. Ticket must not be expired.
    4. Ticket must not have been already consumed (replay prevention).
    5. Ticket account_id and message_id must match exactly.
    6. Operation must be SEND_REPLY.
    7. Payload digest must match canonical hash of current outbound arguments (content integrity).
    8. Atomically marks ticket as consumed.
    """
    try:
        active_mode = get_active_safety_mode()

        # 1. DRAFT_ONLY Invariant: Absolutely no transmission permitted
        if active_mode != MailSafetyMode.MANUAL_SEND_ONLY:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=active_mode,
                context=ExecutionContext.UNAUTHENTICATED_API,
                action="SEND_REPLY",
                reason=f"Policy Enforcement (DRAFT_ONLY): Active safety mode is {active_mode.value}. Transmission is strictly forbidden.",
                is_send_blocked=True
            )

        # 2. Authorization ticket presence check
        if not authorization:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=active_mode,
                context=ExecutionContext.UNAUTHENTICATED_API,
                action="SEND_REPLY",
                reason="Discrete Send Authorization Required: No authorization ticket provided for mail transmission.",
                is_send_blocked=True
            )

        ticket_id = authorization.ticket_id if isinstance(authorization, SendAuthorizationTicket) else str(authorization).strip()
        if not ticket_id:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=active_mode,
                context=ExecutionContext.UNAUTHENTICATED_API,
                action="SEND_REPLY",
                reason="Discrete Send Authorization Required: Empty authorization ticket.",
                is_send_blocked=True
            )

        now = time.time()
        current_digest = compute_outbound_payload_digest(
            account_id=account_id,
            message_id=message_id,
            to_email=to_email,
            subject=subject,
            reply_body=reply_body,
            resume_filename=resume_filename,
        )

        with _AUTH_LOCK:
            stored_ticket = _AUTHORIZATION_REGISTRY.get(ticket_id)
            if not stored_ticket:
                return PolicyEvaluationResult(
                    allowed=False,
                    safety_mode=active_mode,
                    context=ExecutionContext.UNAUTHENTICATED_API,
                    action="SEND_REPLY",
                    reason=f"Discrete Send Authorization Invalid: Ticket '{ticket_id}' not found, unrecognized, or purged.",
                    is_send_blocked=True
                )

            if stored_ticket.consumed:
                return PolicyEvaluationResult(
                    allowed=False,
                    safety_mode=active_mode,
                    context=ExecutionContext.UNAUTHENTICATED_API,
                    action="SEND_REPLY",
                    reason=f"Discrete Send Authorization Replay Detected: Ticket '{ticket_id}' has already been consumed.",
                    is_send_blocked=True
                )

            if stored_ticket.expires_at < now:
                _AUTHORIZATION_REGISTRY.pop(ticket_id, None)
                return PolicyEvaluationResult(
                    allowed=False,
                    safety_mode=active_mode,
                    context=ExecutionContext.UNAUTHENTICATED_API,
                    action="SEND_REPLY",
                    reason=f"Discrete Send Authorization Expired: Ticket '{ticket_id}' has expired.",
                    is_send_blocked=True
                )

            norm_account = (account_id or "").strip().lower()
            if stored_ticket.account_id != norm_account:
                return PolicyEvaluationResult(
                    allowed=False,
                    safety_mode=active_mode,
                    context=ExecutionContext.UNAUTHENTICATED_API,
                    action="SEND_REPLY",
                    reason=f"Discrete Send Authorization Account Mismatch: Ticket issued for '{stored_ticket.account_id}', requested for '{norm_account}'.",
                    is_send_blocked=True
                )

            norm_message = (message_id or "").strip()
            if stored_ticket.message_id != norm_message:
                return PolicyEvaluationResult(
                    allowed=False,
                    safety_mode=active_mode,
                    context=ExecutionContext.UNAUTHENTICATED_API,
                    action="SEND_REPLY",
                    reason=f"Discrete Send Authorization Message Mismatch: Ticket issued for '{stored_ticket.message_id}', requested for '{norm_message}'.",
                    is_send_blocked=True
                )

            if stored_ticket.payload_digest != current_digest:
                return PolicyEvaluationResult(
                    allowed=False,
                    safety_mode=active_mode,
                    context=ExecutionContext.UNAUTHENTICATED_API,
                    action="SEND_REPLY",
                    reason="Discrete Send Authorization Content Integrity Violation: Outbound payload (recipient, subject, body, or attachment) has been mutated since authorization was granted.",
                    is_send_blocked=True
                )

            # Atomic single-use consumption
            stored_ticket.consumed = True

        logger.info(f"SendAuthorizationTicket '{ticket_id}' validated and consumed successfully for message '{message_id}'.")
        return PolicyEvaluationResult(
            allowed=True,
            safety_mode=active_mode,
            context=ExecutionContext.DASHBOARD_INTERACTIVE_USER,
            action="SEND_REPLY",
            reason=f"Discrete Send Authorization verified and consumed for ticket '{ticket_id}'.",
            is_send_blocked=False
        )
    except Exception as ex:
        logger.error(f"Unexpected error validating authorization ticket: {ex}")
        return PolicyEvaluationResult(
            allowed=False,
            safety_mode=get_active_safety_mode(),
            context=ExecutionContext.UNAUTHENTICATED_API,
            action="SEND_REPLY",
            reason=f"Discrete Send Authorization Exception (Fail-Closed): {str(ex)}",
            is_send_blocked=True
        )


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
    context: ExecutionContext,
    safety_mode: Optional[MailSafetyMode] = None,
    authorization: Optional[Union[SendAuthorizationTicket, str]] = None,
) -> PolicyEvaluationResult:
    """
    Core policy decision engine implementing the Acceptance Matrix:

    Execution Context              | DRAFT_ONLY                  | MANUAL_SEND_ONLY
    -------------------------------|-----------------------------|-----------------------------
    Daemon                         | Draft only                  | Draft only
    Background radar               | Draft only                  | Draft only
    Scheduled job                  | Draft only                  | Draft only
    AI/agent invocation            | Draft only                  | Draft only
    Outlook interactive user       | Draft/review                | Explicit human send authorization required
    Aura dashboard interactive     | Send blocked                | Explicit human send authorization required
    Unauthenticated/direct API     | Blocked                     | Blocked

    FAIL-CLOSED GUARANTEE:
    Unrecognized or unclassified actions are strictly DENIED by default.
    Context enums alone NEVER grant transmission permission without discrete send authorization.
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

    # 3. Transmission Operations:
    if resolved_action in TRANSMISSION_ACTIONS:
        # Permanent Invariant: Background execution CAN NEVER send
        if context in BACKGROUND_CONTEXTS:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=mode,
                context=context,
                action=action_str,
                reason=(
                    f"BACKGROUND EXECUTION -> SEND FORBIDDEN: Execution context '{context.value}' "
                    "is strictly prohibited from transmitting email regardless of safety mode."
                ),
                is_send_blocked=True
            )

        # In DRAFT_ONLY mode, send is absolutely blocked for all callers
        if mode == MailSafetyMode.DRAFT_ONLY:
            return PolicyEvaluationResult(
                allowed=False,
                safety_mode=mode,
                context=context,
                action=action_str,
                reason=(
                    "Policy Enforcement: Active safety mode is DRAFT_ONLY. "
                    "Direct send operations are disabled; stage as draft for manual review."
                ),
                is_send_blocked=True
            )

        # Under MANUAL_SEND_ONLY mode, transmission REQUIRES discrete authorization.
        # Context enum alone is metadata, not proof.
        if mode == MailSafetyMode.MANUAL_SEND_ONLY:
            if not authorization:
                return PolicyEvaluationResult(
                    allowed=False,
                    safety_mode=mode,
                    context=context,
                    action=action_str,
                    reason=(
                        "Discrete Send Authorization Required: A caller-supplied execution context alone "
                        "is not proof of human authorization. A valid SendAuthorizationTicket is required."
                    ),
                    is_send_blocked=True
                )

            # If authorization is provided, return allowed (actual consumption handled by validate_and_consume)
            return PolicyEvaluationResult(
                allowed=True,
                safety_mode=mode,
                context=context,
                action=action_str,
                reason=f"Interactive human send authorized under MANUAL_SEND_ONLY with ticket '{authorization}'.",
                is_send_blocked=False
            )

        # Unauthenticated / unauthorized contexts are strictly blocked
        return PolicyEvaluationResult(
            allowed=False,
            safety_mode=mode,
            context=context,
            action=action_str,
            reason=f"Access Denied: Execution context '{context.value}' is not authorized for transmission.",
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

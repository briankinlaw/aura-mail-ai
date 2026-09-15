"""
Calendar Availability Broker Service
Calculates Free-Busy availability, filters working hours, enforces buffers,
and outputs clean, truthful booking options with explicit verification state.
"""

from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional
import zoneinfo
import logging

from backend.calendar_broker.models import (
    CalendarVerificationStatus,
    CalendarProviderOutcome,
    TimeSlot,
    TrustedCalendarEvidence,
    BookingWindowOption,
    FreeBusyRequest,
    FreeBusyResponse,
    CalendarAvailabilityResult,
)

logger = logging.getLogger("calendar_broker.availability")


def calculate_optimal_booking_windows(
    arg1: Any = None,
    arg2: Any = None,
    trusted_evidence: Optional[TrustedCalendarEvidence] = None,
    *,
    busy_slots: Optional[List[TimeSlot]] = None,
    calendar_checked: Optional[bool] = None,
    verification_status: Optional[Any] = None,
) -> FreeBusyResponse:
    """
    Calculates non-conflicting booking windows within preferred working hours.
    Enforces strict Information-Integrity and Provenance rules:
    - Verified states (CALENDAR_VERIFIED_CLEAR, CALENDAR_VERIFIED_WITH_CONFLICTS)
      require authoritative TrustedCalendarEvidence with outcome == SUCCESS.
    - Caller-supplied booleans (e.g. calendar_checked=True), status overrides
      (e.g. verification_status=CALENDAR_VERIFIED_CLEAR), or unverified slot lists
      CANNOT establish verification authority.
    - In the absence of TrustedCalendarEvidence, the status strictly defaults to
      CALENDAR_NOT_CHECKED with is_verified=False, producing truthful proposed copy.
    """
    # 1. Resolve request and evidence from arguments
    req: FreeBusyRequest
    evidence: Optional[TrustedCalendarEvidence] = None
    unverified_busy_slots: List[TimeSlot] = []

    if isinstance(arg1, FreeBusyRequest):
        req = arg1
        if isinstance(arg2, TrustedCalendarEvidence):
            evidence = arg2
        elif isinstance(arg2, list):
            unverified_busy_slots = [s if isinstance(s, TimeSlot) else TimeSlot(**s) for s in arg2]
    elif isinstance(arg2, FreeBusyRequest):
        req = arg2
        if isinstance(arg1, TrustedCalendarEvidence):
            evidence = arg1
        elif isinstance(arg1, list):
            unverified_busy_slots = [s if isinstance(s, TimeSlot) else TimeSlot(**s) for s in arg1]
    else:
        req = FreeBusyRequest(
            start_date=datetime.now().strftime("%Y-%m-%d"),
            end_date=(datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            timezone="America/Chicago",
        )

    if trusted_evidence is not None and isinstance(trusted_evidence, TrustedCalendarEvidence):
        evidence = trusted_evidence

    if busy_slots is not None and not unverified_busy_slots:
        unverified_busy_slots = [s if isinstance(s, TimeSlot) else TimeSlot(**s) for s in busy_slots]

    # 2. Determine verification status strictly based on TrustedCalendarEvidence
    resolved_status: CalendarVerificationStatus
    is_verified: bool = False
    effective_busy_slots: List[TimeSlot] = []

    if evidence is None or not isinstance(evidence, TrustedCalendarEvidence):
        # Untrusted request or caller without provider provenance -> CALENDAR_NOT_CHECKED
        resolved_status = CalendarVerificationStatus.CALENDAR_NOT_CHECKED
        is_verified = False
        effective_busy_slots = unverified_busy_slots
    else:
        # Trusted provider evidence present
        if evidence.outcome == CalendarProviderOutcome.ERROR:
            resolved_status = CalendarVerificationStatus.CALENDAR_ERROR
            is_verified = False
            effective_busy_slots = []
        elif evidence.outcome == CalendarProviderOutcome.UNAVAILABLE:
            resolved_status = CalendarVerificationStatus.CALENDAR_UNAVAILABLE
            is_verified = False
            effective_busy_slots = []
        elif evidence.outcome == CalendarProviderOutcome.SUCCESS:
            effective_busy_slots = evidence.busy_slots or []
            resolved_status = CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR
            is_verified = True
        else:
            resolved_status = CalendarVerificationStatus.CALENDAR_ERROR
            is_verified = False
            effective_busy_slots = []

    try:
        tz = zoneinfo.ZoneInfo(req.timezone)
    except Exception:
        tz = zoneinfo.ZoneInfo("America/Chicago")

    start_dt = datetime.strptime(req.start_date, "%Y-%m-%d").replace(tzinfo=tz)
    end_dt = datetime.strptime(req.end_date, "%Y-%m-%d").replace(tzinfo=tz)

    candidate_windows: List[BookingWindowOption] = []
    conflict_count = 0
    current_day = start_dt

    while current_day <= end_dt:
        # Skip weekends (Saturday=5, Sunday=6)
        if current_day.weekday() < 5:
            work_start = current_day.replace(hour=req.preferred_hours_start, minute=0, second=0, microsecond=0)
            work_end = current_day.replace(hour=req.preferred_hours_end, minute=0, second=0, microsecond=0)

            # Generate potential candidate blocks
            slot_cursor = work_start
            slot_delta = timedelta(minutes=req.meeting_duration_minutes)
            buffer_delta = timedelta(minutes=req.buffer_minutes)

            while slot_cursor + slot_delta <= work_end:
                slot_end = slot_cursor + slot_delta

                # Check conflicts with busy slots (including pre-event and post-event buffers)
                has_conflict = False
                for busy in effective_busy_slots:
                    b_start = busy.start_time.replace(tzinfo=tz) if busy.start_time.tzinfo is None else busy.start_time.astimezone(tz)
                    b_end = busy.end_time.replace(tzinfo=tz) if busy.end_time.tzinfo is None else busy.end_time.astimezone(tz)
                    busy_start_buffered = b_start - buffer_delta
                    busy_end_buffered = b_end + buffer_delta

                    # Overlap check with buffers
                    if not (slot_end <= busy_start_buffered or slot_cursor >= busy_end_buffered):
                        has_conflict = True
                        conflict_count += 1
                        break

                if not has_conflict:
                    display_str = (
                        f"{slot_cursor.strftime('%A, %b %d')}: "
                        f"{slot_cursor.strftime('%I:%M %p').lstrip('0')} – "
                        f"{slot_end.strftime('%I:%M %p').lstrip('0')} "
                        f"({req.timezone.split('/')[-1]})"
                    )
                    candidate_windows.append(
                        BookingWindowOption(
                            formatted_display=display_str,
                            iso_start=slot_cursor.isoformat(),
                            iso_end=slot_end.isoformat(),
                            duration_minutes=req.meeting_duration_minutes,
                            timezone=req.timezone
                        )
                    )

                slot_cursor += slot_delta + buffer_delta

        current_day += timedelta(days=1)

    # If trusted evidence was successful, distinguish CLEAR vs WITH_CONFLICTS
    if is_verified and evidence is not None and evidence.outcome == CalendarProviderOutcome.SUCCESS:
        if conflict_count > 0 or len(effective_busy_slots) > 0:
            resolved_status = CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS
        else:
            resolved_status = CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR

    # Pick top 3-4 diverse options across different days if possible
    selected_options: List[BookingWindowOption] = []
    seen_days = set()
    for opt in candidate_windows:
        day_key = opt.iso_start[:10]
        if day_key not in seen_days or len(selected_options) < 4:
            selected_options.append(opt)
            seen_days.add(day_key)
        if len(selected_options) >= 5:
            break

    if not selected_options and candidate_windows:
        selected_options = candidate_windows[:3]

    summary_text = format_availability_text(selected_options, verification_status=resolved_status)

    return FreeBusyResponse(
        available_windows=selected_options,
        busy_slots_count=len(effective_busy_slots),
        conflict_count=conflict_count,
        timezone=req.timezone,
        formatted_summary=summary_text,
        verification_status=resolved_status,
        is_verified=is_verified,
    )


def format_availability_text(
    options: List[BookingWindowOption],
    verification_status: CalendarVerificationStatus = CalendarVerificationStatus.CALENDAR_NOT_CHECKED
) -> str:
    """
    Formats availability options into executive bullet points for email drafts.
    Guarantees that unverified availability uses proposed/pending language,
    and only verified clear/conflict states assert confirmed availability.
    """
    if verification_status in (
        CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR,
        CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS,
    ):
        if not options:
            return "My calendar is currently fully booked during business hours for the requested window. Please feel free to suggest an alternative time."

        lines = ["Here are a few times I am currently available for a brief conversation:"]
        for opt in options[:3]:
            lines.append(f"• {opt.formatted_display}")
        lines.append("\nIf none of these work, please feel free to send across a calendar invite or suggest an alternative.")
        return "\n".join(lines)
    else:
        # Unverified states: CALENDAR_NOT_CHECKED, CALENDAR_UNAVAILABLE, CALENDAR_ERROR
        if not options:
            return "I can be generally flexible next week during US business hours (pending calendar verification). Please feel free to suggest a time that works best for you."

        lines = ["Here are some proposed times for a brief conversation (pending calendar verification):"]
        for opt in options[:3]:
            lines.append(f"• {opt.formatted_display}")
        lines.append("\nThese windows are pending calendar verification. If none of these work, please feel free to suggest an alternative time.")
        return "\n".join(lines)

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
    TimeSlot,
    BookingWindowOption,
    FreeBusyRequest,
    FreeBusyResponse,
    CalendarAvailabilityResult,
)

logger = logging.getLogger("calendar_broker.availability")


def calculate_optimal_booking_windows(
    busy_slots: Optional[List[TimeSlot]],
    request: FreeBusyRequest,
    calendar_checked: bool = False,
    verification_status: Optional[CalendarVerificationStatus] = None,
) -> FreeBusyResponse:
    """
    Calculates non-conflicting booking windows within preferred working hours.
    Explicitly tracks and enforces truthful CalendarVerificationStatus:
    - CALENDAR_NOT_CHECKED: When calendar was not queried. Output slots are proposed/tentative.
    - CALENDAR_UNAVAILABLE / CALENDAR_ERROR: When provider/query failed or unavailable.
    - CALENDAR_VERIFIED_CLEAR: When calendar was queried, succeeded, and has 0 conflicting events.
    - CALENDAR_VERIFIED_WITH_CONFLICTS: When calendar was queried, succeeded, and has conflicting events.
    """
    # 1. Determine truthful verification status
    resolved_status: CalendarVerificationStatus
    is_verified: bool = False

    # Check if request or caller explicitly provided status
    if verification_status is not None:
        resolved_status = verification_status
    elif request.verification_status is not None:
        resolved_status = request.verification_status
    elif busy_slots is None and not (calendar_checked or request.calendar_checked):
        resolved_status = CalendarVerificationStatus.CALENDAR_NOT_CHECKED
    elif not (calendar_checked or request.calendar_checked):
        resolved_status = CalendarVerificationStatus.CALENDAR_NOT_CHECKED
    else:
        # Calendar was queried (calendar_checked == True or request.calendar_checked == True)
        if busy_slots is None:
            resolved_status = CalendarVerificationStatus.CALENDAR_UNAVAILABLE
        else:
            resolved_status = CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR

    effective_busy_slots = busy_slots or []

    try:
        tz = zoneinfo.ZoneInfo(request.timezone)
    except Exception:
        tz = zoneinfo.ZoneInfo("America/Chicago")

    start_dt = datetime.strptime(request.start_date, "%Y-%m-%d").replace(tzinfo=tz)
    end_dt = datetime.strptime(request.end_date, "%Y-%m-%d").replace(tzinfo=tz)

    candidate_windows: List[BookingWindowOption] = []
    conflict_count = 0
    current_day = start_dt

    while current_day <= end_dt:
        # Skip weekends (Saturday=5, Sunday=6)
        if current_day.weekday() < 5:
            work_start = current_day.replace(hour=request.preferred_hours_start, minute=0, second=0, microsecond=0)
            work_end = current_day.replace(hour=request.preferred_hours_end, minute=0, second=0, microsecond=0)

            # Generate potential candidate blocks
            slot_cursor = work_start
            slot_delta = timedelta(minutes=request.meeting_duration_minutes)
            buffer_delta = timedelta(minutes=request.buffer_minutes)

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
                        f"({request.timezone.split('/')[-1]})"
                    )
                    candidate_windows.append(
                        BookingWindowOption(
                            formatted_display=display_str,
                            iso_start=slot_cursor.isoformat(),
                            iso_end=slot_end.isoformat(),
                            duration_minutes=request.meeting_duration_minutes,
                            timezone=request.timezone
                        )
                    )

                slot_cursor += slot_delta + buffer_delta

        current_day += timedelta(days=1)

    # If calendar was checked and no explicit override, distinguish CLEAR vs WITH_CONFLICTS
    if (calendar_checked or request.calendar_checked) and verification_status is None and request.verification_status is None:
        if conflict_count > 0 or len(effective_busy_slots) > 0:
            resolved_status = CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS
        else:
            resolved_status = CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR

    if resolved_status in (
        CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR,
        CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS,
    ):
        is_verified = True
    else:
        is_verified = False

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
        timezone=request.timezone,
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

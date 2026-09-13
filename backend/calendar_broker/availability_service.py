"""
Calendar Availability Broker Service
Calculates Free-Busy availability, filters working hours, enforces buffers, and outputs clean booking options.
"""

from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional
import zoneinfo
import logging

from backend.calendar_broker.models import (
    TimeSlot,
    BookingWindowOption,
    FreeBusyRequest,
    FreeBusyResponse
)

logger = logging.getLogger("calendar_broker.availability")

def calculate_optimal_booking_windows(
    busy_slots: List[TimeSlot],
    request: FreeBusyRequest
) -> FreeBusyResponse:
    """Calculates non-conflicting booking windows within preferred working hours."""
    try:
        tz = zoneinfo.ZoneInfo(request.timezone)
    except Exception:
        tz = zoneinfo.ZoneInfo("America/Chicago")

    start_dt = datetime.strptime(request.start_date, "%Y-%m-%d").replace(tzinfo=tz)
    end_dt = datetime.strptime(request.end_date, "%Y-%m-%d").replace(tzinfo=tz)

    candidate_windows: List[BookingWindowOption] = []
    current_day = start_dt

    while current_day <= end_dt:
        # Skip weekends (Saturday=5, Sunday=6)
        if current_day.weekday() < 5:
            work_start = current_day.replace(hour=request.preferred_hours_start, minute=0, second=0, microsecond=0)
            work_end = current_day.replace(hour=request.preferred_hours_end, minute=0, second=0, microsecond=0)

            # Generate potential 30-min candidate blocks
            slot_cursor = work_start
            slot_delta = timedelta(minutes=request.meeting_duration_minutes)
            buffer_delta = timedelta(minutes=request.buffer_minutes)

            while slot_cursor + slot_delta <= work_end:
                slot_end = slot_cursor + slot_delta
                
                # Check conflicts with busy slots
                has_conflict = False
                for busy in busy_slots:
                    b_start = busy.start_time.replace(tzinfo=tz) if busy.start_time.tzinfo is None else busy.start_time.astimezone(tz)
                    b_end = busy.end_time.replace(tzinfo=tz) if busy.end_time.tzinfo is None else busy.end_time.astimezone(tz)
                    busy_start_buffered = b_start - buffer_delta
                    busy_end_buffered = b_end + buffer_delta

                    if not (slot_end <= busy_start_buffered or slot_cursor >= busy_end_buffered):
                        has_conflict = True
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

    summary_text = format_availability_text(selected_options)

    return FreeBusyResponse(
        available_windows=selected_options,
        busy_slots_count=len(busy_slots),
        timezone=request.timezone,
        formatted_summary=summary_text
    )

def format_availability_text(options: List[BookingWindowOption]) -> str:
    """Formats availability options into executive bullet points for email drafts."""
    if not options:
        return "I am generally flexible next week during US business hours. Please feel free to suggest a time that works best for you."
    
    lines = ["Here are a few times I am currently available for a brief conversation:"]
    for opt in options[:3]:
        lines.append(f"• {opt.formatted_display}")
    lines.append("\nIf none of these work, please feel free to send across a calendar invite or suggest an alternative.")
    return "\n".join(lines)

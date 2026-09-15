"""
Calendar Availability Broker Capability Package
Provides timezone normalization, Free-Busy slot aggregation, buffer calculation, and optimal booking window generation.
"""

from backend.calendar_broker.models import (
    CalendarVerificationStatus,
    TimeSlot,
    FreeBusyRequest,
    FreeBusyResponse,
    BookingWindowOption,
    CalendarAvailabilityResult,
)
from backend.calendar_broker.availability_service import (
    calculate_optimal_booking_windows,
    format_availability_text,
)

__all__ = [
    "CalendarVerificationStatus",
    "TimeSlot",
    "FreeBusyRequest",
    "FreeBusyResponse",
    "BookingWindowOption",
    "CalendarAvailabilityResult",
    "calculate_optimal_booking_windows",
    "format_availability_text",
]

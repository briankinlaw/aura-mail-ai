"""
Calendar Availability Broker Capability Package
Provides timezone normalization, Free-Busy slot aggregation, buffer calculation, and optimal booking window generation.
"""

from backend.calendar_broker.models import (
    TimeSlot,
    FreeBusyRequest,
    FreeBusyResponse,
    BookingWindowOption
)
from backend.calendar_broker.availability_service import (
    calculate_optimal_booking_windows,
    format_availability_text
)

__all__ = [
    "TimeSlot",
    "FreeBusyRequest",
    "FreeBusyResponse",
    "BookingWindowOption",
    "calculate_optimal_booking_windows",
    "format_availability_text"
]

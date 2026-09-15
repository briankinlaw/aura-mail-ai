"""
Calendar Broker Models
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class CalendarVerificationStatus(str, Enum):
    """
    Truthful calendar availability verification state model.
    Distinguishes unverified/proposed availability from confirmed/verified availability.
    """
    CALENDAR_NOT_CHECKED = "CALENDAR_NOT_CHECKED"
    CALENDAR_VERIFIED_CLEAR = "CALENDAR_VERIFIED_CLEAR"
    CALENDAR_VERIFIED_WITH_CONFLICTS = "CALENDAR_VERIFIED_WITH_CONFLICTS"
    CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"
    CALENDAR_ERROR = "CALENDAR_ERROR"


class TimeSlot(BaseModel):
    start_time: datetime
    end_time: datetime
    timezone: str = "America/Chicago"
    is_busy: bool = False
    title: Optional[str] = None


class BookingWindowOption(BaseModel):
    formatted_display: str = Field(description="E.g. Tuesday, Sep 15: 1:00 PM – 2:30 PM CST")
    iso_start: str
    iso_end: str
    duration_minutes: int = 30
    timezone: str = "America/Chicago"


class FreeBusyRequest(BaseModel):
    start_date: str = Field(description="ISO Date (YYYY-MM-DD)")
    end_date: str = Field(description="ISO Date (YYYY-MM-DD)")
    timezone: str = "America/Chicago"
    meeting_duration_minutes: int = 30
    buffer_minutes: int = 15
    preferred_hours_start: int = 9  # 9 AM
    preferred_hours_end: int = 17   # 5 PM
    calendar_checked: bool = False
    verification_status: Optional[CalendarVerificationStatus] = None
    busy_slots: Optional[List[TimeSlot]] = None


class FreeBusyResponse(BaseModel):
    available_windows: List[BookingWindowOption]
    busy_slots_count: int = 0
    conflict_count: int = 0
    timezone: str
    formatted_summary: str
    verification_status: CalendarVerificationStatus = CalendarVerificationStatus.CALENDAR_NOT_CHECKED
    is_verified: bool = False


class CalendarAvailabilityResult(BaseModel):
    status: CalendarVerificationStatus = CalendarVerificationStatus.CALENDAR_NOT_CHECKED
    is_verified: bool = False
    available_windows: List[BookingWindowOption] = []
    busy_slots_count: int = 0
    conflict_count: int = 0
    formatted_summary: str = ""
    timezone: str = "America/Chicago"

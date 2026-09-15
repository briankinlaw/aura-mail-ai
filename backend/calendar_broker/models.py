"""
Calendar Broker Models
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


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


class CalendarProviderOutcome(str, Enum):
    """
    Outcome of an authoritative calendar provider operation.
    """
    SUCCESS = "SUCCESS"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class TimeSlot(BaseModel):
    start_time: datetime
    end_time: datetime
    timezone: str = "America/Chicago"
    is_busy: bool = False
    title: Optional[str] = None


class TrustedCalendarEvidence(BaseModel):
    """
    Authoritative provider query evidence representing trusted calendar provenance.
    Can only be minted by trusted application/provider layers upon real query execution.
    """
    outcome: CalendarProviderOutcome = CalendarProviderOutcome.SUCCESS
    busy_slots: List[TimeSlot] = Field(default_factory=list)
    provider_name: Optional[str] = None
    queried_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_error: Optional[str] = None


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

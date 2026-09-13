"""
Calendar Broker Models
"""

from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

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

class FreeBusyResponse(BaseModel):
    available_windows: List[BookingWindowOption]
    busy_slots_count: int
    timezone: str
    formatted_summary: str

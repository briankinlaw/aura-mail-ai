"""
Unit Tests for Opportunity Radar and Calendar Availability Broker Capabilities
"""

import unittest
from datetime import datetime, timedelta
import zoneinfo
from backend.models import EmailMessage, EmailCategory, UserProfile, ReplyDraftRequest
from backend.radar.triage_service import classify_email_radar, calculate_opportunity_fit_score, extract_recruiter_details
from backend.radar.scribe_service import generate_executive_reply, compose_grounded_response
from backend.calendar_broker.models import TimeSlot, FreeBusyRequest, BookingWindowOption
from backend.calendar_broker.availability_service import calculate_optimal_booking_windows, format_availability_text

class TestRadarAndCalendar(unittest.TestCase):
    def test_radar_fit_score(self):
        score_data = calculate_opportunity_fit_score(
            role_title="Principal Solutions Architect",
            body_text="Looking for a leader with Google Cloud, BigQuery, and AI Governance experience. Comp: $250k-$280k.",
            required_skills=["Google Cloud", "BigQuery", "AI Governance"]
        )
        self.assertGreaterEqual(score_data["fit_score"], 80)
        self.assertEqual(score_data["fit_tier"], "HIGH")
        self.assertGreaterEqual(len(score_data["alignment_reasons"]), 3)

    def test_radar_triage_recruiter_details(self):
        msg = EmailMessage(
            id="test-1",
            account_id="acc-1",
            sender_name="Sarah Jenkins",
            sender_email="sjenkins@toprecruiting.com",
            subject="Opportunity: Principal Cloud & AI Architect at Global Corp",
            body_text="Hi Brian, We are hiring for a Principal Cloud & AI Architect with GCP and BigQuery experience. Salary is $240k - $270k.",
            received_at="2026-09-13 10:00",
            preview="Hi Brian, We are hiring...",
            folder="Inbox"
        )
        details = extract_recruiter_details(msg)
        self.assertIn("Architect", details.role_title)
        self.assertIn("Global Corp", details.company_name)
        self.assertIsNotNone(details.salary_range)

    def test_radar_scribe_grounded_response(self):
        profile = UserProfile(
            full_name="Brian Kinlaw",
            current_title="Strategic Advisor, Data & AI / Senior Solutions Architect",
            summary_bio="Enterprise Cloud & AI Leader",
            core_skills=["Google Cloud", "BigQuery", "AI Governance"]
        )
        reply = compose_grounded_response(
            recruiter_name="Sarah",
            company_name="Global Corp",
            role_title="Principal Cloud Architect",
            required_skills=["Google Cloud", "BigQuery"],
            selected_resume="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
            user_profile=profile
        )
        self.assertIn("Sarah", reply)
        self.assertIn("Principal Cloud Architect", reply)
        self.assertIn("Global Corp", reply)
        self.assertIn("$100M+", reply)
        self.assertIn("$8M", reply)
        self.assertIn("Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx", reply)

    def test_calendar_broker_availability_windows(self):
        tz = zoneinfo.ZoneInfo("America/Chicago")
        busy_slots = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 10, 0, tzinfo=tz),
                end_time=datetime(2026, 9, 21, 11, 0, tzinfo=tz),
                timezone="America/Chicago",
                is_busy=True,
                title="Executive Review"
            )
        ]
        req = FreeBusyRequest(
            start_date="2026-09-21",
            end_date="2026-09-23",
            timezone="America/Chicago",
            meeting_duration_minutes=30,
            buffer_minutes=15,
            preferred_hours_start=9,
            preferred_hours_end=17,
            calendar_checked=True
        )
        res = calculate_optimal_booking_windows(busy_slots, req, calendar_checked=True)
        self.assertGreater(len(res.available_windows), 0)
        self.assertEqual(res.busy_slots_count, 1)
        self.assertEqual(res.verification_status, "CALENDAR_VERIFIED_WITH_CONFLICTS")
        self.assertTrue(res.is_verified)
        self.assertIn("Here are a few times I am currently available", res.formatted_summary)


# ==============================================================================
# PHASE 7: CALENDAR TRUTHFULNESS & INFORMATION INTEGRITY REGRESSION SUITE
# ==============================================================================

from backend.calendar_broker.models import CalendarVerificationStatus


class TestPhase7CalendarTruthfulness(unittest.TestCase):
    """
    Direct deterministic regression tests for Phase 7 calendar availability semantics.
    Enforces that unverified or empty collections never constitute evidence of availability.
    """

    def setUp(self):
        self.tz = zoneinfo.ZoneInfo("America/Chicago")
        self.base_req = FreeBusyRequest(
            start_date="2026-09-21",  # Monday
            end_date="2026-09-25",    # Friday
            timezone="America/Chicago",
            meeting_duration_minutes=30,
            buffer_minutes=15,
            preferred_hours_start=9,
            preferred_hours_end=17
        )

    def test_phase7_1_calendar_unavailable(self):
        """
        1. CALENDAR UNAVAILABLE:
        Proves that an unavailable calendar provider cannot produce CALENDAR_VERIFIED_CLEAR
        or confirmed availability language.
        """
        res = calculate_optimal_booking_windows(
            busy_slots=None,
            request=self.base_req,
            verification_status=CalendarVerificationStatus.CALENDAR_UNAVAILABLE
        )
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_UNAVAILABLE)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)

    def test_phase7_2_calendar_not_checked(self):
        """
        2. CALENDAR NOT CHECKED:
        Proves that no calendar query means CALENDAR_NOT_CHECKED rather than verified clear,
        even if the associated event collection is empty [].
        """
        res = calculate_optimal_booking_windows(
            busy_slots=[],
            request=self.base_req,
            calendar_checked=False
        )
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_NOT_CHECKED)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("proposed times", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)

    def test_phase7_3_verified_empty(self):
        """
        3. VERIFIED EMPTY:
        Proves that successful calendar check + zero conflicting events produces
        CALENDAR_VERIFIED_CLEAR and confirmed availability language.
        """
        res = calculate_optimal_booking_windows(
            busy_slots=[],
            request=self.base_req,
            calendar_checked=True
        )
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR)
        self.assertTrue(res.is_verified)
        self.assertEqual(res.busy_slots_count, 0)
        self.assertEqual(res.conflict_count, 0)
        self.assertIn("I am currently available", res.formatted_summary)
        self.assertNotIn("pending calendar verification", res.formatted_summary)

    def test_phase7_4_conflicting_event(self):
        """
        4. CONFLICTING EVENT:
        Proves that a successfully retrieved conflicting event produces
        CALENDAR_VERIFIED_WITH_CONFLICTS and excludes the conflicting window.
        """
        # Busy slot: Monday Sep 21 09:00 - 10:00 CST
        busy = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 9, 0, tzinfo=self.tz),
                end_time=datetime(2026, 9, 21, 10, 0, tzinfo=self.tz),
                timezone="America/Chicago",
                is_busy=True
            )
        ]
        res = calculate_optimal_booking_windows(
            busy_slots=busy,
            request=self.base_req,
            calendar_checked=True
        )
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS)
        self.assertTrue(res.is_verified)
        self.assertGreater(res.conflict_count, 0)
        # Verify 9:00 AM window on Monday Sep 21 is NOT in available windows
        for win in res.available_windows:
            if "Sep 21" in win.formatted_display:
                self.assertNotIn("9:00 AM", win.formatted_display)
                self.assertNotIn("9:30 AM", win.formatted_display)

    def test_phase7_5_pre_event_buffer(self):
        """
        5. PRE-EVENT BUFFER:
        Proves that candidate window violating pre-event buffer (15 min before busy slot)
        is excluded from availability.
        """
        # Busy slot: Monday Sep 21 10:00 - 11:00 CST
        # 15 min buffer before means 09:45 - 10:00 is blocked
        # A 30 min candidate from 09:30 - 10:00 overlaps the buffer and must be excluded.
        busy = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 10, 0, tzinfo=self.tz),
                end_time=datetime(2026, 9, 21, 11, 0, tzinfo=self.tz),
                timezone="America/Chicago",
                is_busy=True
            )
        ]
        res = calculate_optimal_booking_windows(
            busy_slots=busy,
            request=self.base_req,
            calendar_checked=True
        )
        for win in res.available_windows:
            if "Sep 21" in win.formatted_display:
                # 9:30 AM to 10:00 AM violates 15m pre-event buffer (ends at 10:00, busy starts at 10:00)
                self.assertNotIn("9:30 AM – 10:00 AM", win.formatted_display)

    def test_phase7_6_post_event_buffer(self):
        """
        6. POST-EVENT BUFFER:
        Proves that candidate window violating post-event buffer (15 min after busy slot)
        is excluded from availability.
        """
        # Busy slot: Monday Sep 21 10:00 - 11:00 CST
        # 15 min buffer after means 11:00 - 11:15 is blocked
        # A 30 min candidate starting at 11:00 (11:00 - 11:30) overlaps the buffer and must be excluded.
        busy = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 10, 0, tzinfo=self.tz),
                end_time=datetime(2026, 9, 21, 11, 0, tzinfo=self.tz),
                timezone="America/Chicago",
                is_busy=True
            )
        ]
        res = calculate_optimal_booking_windows(
            busy_slots=busy,
            request=self.base_req,
            calendar_checked=True
        )
        for win in res.available_windows:
            if "Sep 21" in win.formatted_display:
                # 11:00 AM to 11:30 AM violates post-event buffer
                self.assertNotIn("11:00 AM – 11:30 AM", win.formatted_display)

    def test_phase7_7_working_hour_boundary(self):
        """
        7. WORKING-HOUR BOUNDARY:
        Proves candidate generation strictly respects configured working-hour boundaries
        (9 AM to 5 PM) and never proposes slots outside these hours.
        """
        res = calculate_optimal_booking_windows(
            busy_slots=[],
            request=self.base_req,
            calendar_checked=True
        )
        for win in res.available_windows:
            start_hour = datetime.fromisoformat(win.iso_start).hour
            end_hour = datetime.fromisoformat(win.iso_end).hour
            end_minute = datetime.fromisoformat(win.iso_end).minute
            self.assertGreaterEqual(start_hour, 9)
            self.assertTrue(end_hour < 17 or (end_hour == 17 and end_minute == 0))

    def test_phase7_8_weekend_exclusion(self):
        """
        8. WEEKEND EXCLUSION:
        Proves weekend-exclusion rules remain enforced (no Saturday or Sunday candidate slots).
        """
        weekend_req = FreeBusyRequest(
            start_date="2026-09-19",  # Saturday
            end_date="2026-09-20",    # Sunday
            timezone="America/Chicago",
            meeting_duration_minutes=30,
            buffer_minutes=15,
            preferred_hours_start=9,
            preferred_hours_end=17
        )
        res = calculate_optimal_booking_windows(
            busy_slots=[],
            request=weekend_req,
            calendar_checked=True
        )
        self.assertEqual(len(res.available_windows), 0)

    def test_phase7_9_unverified_generated_communication(self):
        """
        9. UNVERIFIED GENERATED COMMUNICATION:
        Proves communication generated from CALENDAR_NOT_CHECKED does not assert confirmed
        availability and uses proposed/pending semantics.
        """
        res = calculate_optimal_booking_windows(
            busy_slots=[],
            request=self.base_req,
            calendar_checked=False
        )
        summary = res.formatted_summary
        self.assertNotIn("I am currently available", summary)
        self.assertNotIn("These times work for me", summary)
        self.assertNotIn("My calendar is open", summary)
        self.assertIn("proposed times", summary)
        self.assertIn("pending calendar verification", summary)

    def test_phase7_10_error_state_cannot_become_verified_clear(self):
        """
        10. ERROR STATE CANNOT BECOME VERIFIED CLEAR:
        Proves that forcing a provider error produces CALENDAR_ERROR and cannot produce
        confirmed availability wording downstream.
        """
        res = calculate_optimal_booking_windows(
            busy_slots=None,
            request=self.base_req,
            verification_status=CalendarVerificationStatus.CALENDAR_ERROR
        )
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_ERROR)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)


if __name__ == "__main__":
    unittest.main()

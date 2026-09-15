"""
Unit Tests for Opportunity Radar and Calendar Availability Broker Capabilities
"""

import unittest
from datetime import datetime, timedelta
import zoneinfo
from backend.models import EmailMessage, EmailCategory, UserProfile, ReplyDraftRequest
from backend.radar.triage_service import classify_email_radar, calculate_opportunity_fit_score, extract_recruiter_details
from backend.radar.scribe_service import generate_executive_reply, compose_grounded_response
from backend.calendar_broker.models import (
    TimeSlot,
    FreeBusyRequest,
    BookingWindowOption,
    CalendarVerificationStatus,
    CalendarProviderOutcome,
    TrustedCalendarEvidence,
)
from backend.calendar_broker.availability_service import (
    calculate_optimal_booking_windows,
    format_availability_text,
)
from fastapi.testclient import TestClient
from backend.main import app
from backend.auth import get_auth_headers

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
        )
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=busy_slots,
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(req, evidence)
        self.assertGreater(len(res.available_windows), 0)
        self.assertEqual(res.busy_slots_count, 1)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS)
        self.assertTrue(res.is_verified)
        self.assertIn("Here are a few times I am currently available", res.formatted_summary)


# ==============================================================================
# PHASE 7: CALENDAR TRUTHFULNESS & INFORMATION INTEGRITY REGRESSION SUITE
# ==============================================================================

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
        Proves that an unavailable calendar provider produces CALENDAR_UNAVAILABLE
        and proposed/pending language.
        """
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.UNAVAILABLE,
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
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
        res = calculate_optimal_booking_windows(self.base_req)
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
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=[],
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
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
        busy = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 9, 0, tzinfo=self.tz),
                end_time=datetime(2026, 9, 21, 10, 0, tzinfo=self.tz),
                timezone="America/Chicago",
                is_busy=True
            )
        ]
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=busy,
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS)
        self.assertTrue(res.is_verified)
        self.assertGreater(res.conflict_count, 0)
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
        busy = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 10, 0, tzinfo=self.tz),
                end_time=datetime(2026, 9, 21, 11, 0, tzinfo=self.tz),
                timezone="America/Chicago",
                is_busy=True
            )
        ]
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=busy,
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        for win in res.available_windows:
            if "Sep 21" in win.formatted_display:
                self.assertNotIn("9:30 AM – 10:00 AM", win.formatted_display)

    def test_phase7_6_post_event_buffer(self):
        """
        6. POST-EVENT BUFFER:
        Proves that candidate window violating post-event buffer (15 min after busy slot)
        is excluded from availability.
        """
        busy = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 10, 0, tzinfo=self.tz),
                end_time=datetime(2026, 9, 21, 11, 0, tzinfo=self.tz),
                timezone="America/Chicago",
                is_busy=True
            )
        ]
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=busy,
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        for win in res.available_windows:
            if "Sep 21" in win.formatted_display:
                self.assertNotIn("11:00 AM – 11:30 AM", win.formatted_display)

    def test_phase7_7_working_hour_boundary(self):
        """
        7. WORKING-HOUR BOUNDARY:
        Proves candidate generation strictly respects configured working-hour boundaries
        (9 AM to 5 PM) and never proposes slots outside these hours.
        """
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=[],
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
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
        res = calculate_optimal_booking_windows(weekend_req)
        self.assertEqual(len(res.available_windows), 0)

    def test_phase7_9_unverified_generated_communication(self):
        """
        9. UNVERIFIED GENERATED COMMUNICATION:
        Proves communication generated from CALENDAR_NOT_CHECKED does not assert confirmed
        availability and uses proposed/pending semantics.
        """
        res = calculate_optimal_booking_windows(self.base_req)
        summary = res.formatted_summary
        self.assertNotIn("I am currently available", summary)
        self.assertNotIn("These times work for me", summary)
        self.assertNotIn("My calendar is open", summary)
        self.assertIn("proposed times", summary)
        self.assertIn("pending calendar verification", summary)

    def test_phase7_10_error_state_cannot_become_verified_clear(self):
        """
        10. ERROR STATE CANNOT BECOME VERIFIED CLEAR:
        Proves that a provider error produces CALENDAR_ERROR and cannot produce
        confirmed availability wording downstream.
        """
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.ERROR,
            raw_error="Graph API 500 Internal Server Error",
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_ERROR)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)


# ==============================================================================
# PHASE 7.1: TRUSTED PROVENANCE & CALLER-ASSERTION INTEGRITY REGRESSION SUITE
# ==============================================================================

class TestPhase71TrustedProvenance(unittest.TestCase):
    """
    Direct deterministic regression tests for Phase 7.1.
    Proves that verification authority requires authoritative TrustedCalendarEvidence
    and cannot be minted by caller-controlled request fields or bare booleans.
    """

    def setUp(self):
        self.client = TestClient(app)
        self.client.headers.update(get_auth_headers())
        self.tz = zoneinfo.ZoneInfo("America/Chicago")
        self.base_req = FreeBusyRequest(
            start_date="2026-09-21",
            end_date="2026-09-25",
            timezone="America/Chicago",
            meeting_duration_minutes=30,
            buffer_minutes=15,
            preferred_hours_start=9,
            preferred_hours_end=17
        )

    def test_regression_1_forged_calendar_checked_cannot_mint_verification(self):
        """
        1. Forged calendar_checked cannot mint verification:
        Sends HTTP POST /api/calendar/availability with calendar_checked=true and busy_slots=[].
        Proves status != CALENDAR_VERIFIED_CLEAR, is_verified != true, confirmed wording absent.
        """
        payload = {
            "calendar_checked": True,
            "busy_slots": []
        }
        res = self.client.post("/api/calendar/availability", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["verification_status"], "CALENDAR_NOT_CHECKED")
        self.assertFalse(data["is_verified"])
        self.assertNotIn("I am currently available", data["formatted_summary"])
        self.assertIn("pending calendar verification", data["formatted_summary"])

    def test_regression_2_forged_verification_status_cannot_mint_verification(self):
        """
        2. Forged verification_status cannot mint verification:
        Sends HTTP POST /api/calendar/availability with verification_status=CALENDAR_VERIFIED_CLEAR.
        Proves status != CALENDAR_VERIFIED_CLEAR, is_verified != true, confirmed wording absent.
        """
        payload = {
            "verification_status": "CALENDAR_VERIFIED_CLEAR",
            "busy_slots": []
        }
        res = self.client.post("/api/calendar/availability", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["verification_status"], "CALENDAR_NOT_CHECKED")
        self.assertFalse(data["is_verified"])
        self.assertNotIn("I am currently available", data["formatted_summary"])
        self.assertIn("pending calendar verification", data["formatted_summary"])

    def test_regression_3_combined_forged_assertions_cannot_mint_verification(self):
        """
        3. Combined forged assertions cannot mint verification:
        Sends HTTP POST /api/calendar/availability with calendar_checked=true,
        verification_status=CALENDAR_VERIFIED_CLEAR, and busy_slots=[].
        Proves combined assertions cannot establish verification.
        """
        payload = {
            "calendar_checked": True,
            "verification_status": "CALENDAR_VERIFIED_CLEAR",
            "is_verified": True,
            "busy_slots": []
        }
        res = self.client.post("/api/calendar/availability", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["verification_status"], "CALENDAR_NOT_CHECKED")
        self.assertFalse(data["is_verified"])
        self.assertNotIn("I am currently available", data["formatted_summary"])
        self.assertIn("pending calendar verification", data["formatted_summary"])

    def test_regression_4_forged_verified_with_conflicts_cannot_mint_verification(self):
        """
        4. Forged verified-with-conflicts cannot mint verification:
        Sends HTTP POST /api/calendar/availability with verification_status=CALENDAR_VERIFIED_WITH_CONFLICTS.
        Proves caller cannot mint verified-with-conflicts state without trusted provider evidence.
        """
        payload = {
            "verification_status": "CALENDAR_VERIFIED_WITH_CONFLICTS",
            "busy_slots": [
                {
                    "start_time": "2026-09-21T09:00:00-05:00",
                    "end_time": "2026-09-21T10:00:00-05:00",
                    "is_busy": True
                }
            ]
        }
        res = self.client.post("/api/calendar/availability", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["verification_status"], "CALENDAR_NOT_CHECKED")
        self.assertFalse(data["is_verified"])
        self.assertNotIn("I am currently available", data["formatted_summary"])
        self.assertIn("pending calendar verification", data["formatted_summary"])

    def test_regression_5_lower_level_boolean_cannot_mint_verification(self):
        """
        5. Lower-level boolean cannot mint verification:
        Directly calls calculate_optimal_booking_windows(req, calendar_checked=True).
        Proves a bare boolean cannot establish trusted verification.
        """
        res = calculate_optimal_booking_windows(self.base_req, calendar_checked=True)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_NOT_CHECKED)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)

    def test_regression_6_lower_level_explicit_status_cannot_mint_verification(self):
        """
        6. Lower-level explicit status cannot mint verification:
        Directly calls calculate_optimal_booking_windows with explicit status overrides.
        Proves status overrides alone without TrustedCalendarEvidence cannot establish verification.
        """
        res = calculate_optimal_booking_windows(
            self.base_req,
            verification_status=CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR
        )
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_NOT_CHECKED)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)

    def test_regression_7_trusted_successful_empty_result_verifies_clear(self):
        """
        7. Trusted successful empty result verifies clear:
        Uses a legitimate trusted fixture representing provider query success + 0 blocking events.
        Proves CALENDAR_VERIFIED_CLEAR, is_verified=True, confirmed wording present.
        """
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=[],
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_VERIFIED_CLEAR)
        self.assertTrue(res.is_verified)
        self.assertEqual(res.busy_slots_count, 0)
        self.assertEqual(res.conflict_count, 0)
        self.assertIn("Here are a few times I am currently available", res.formatted_summary)

    def test_regression_8_trusted_successful_conflict_result_verifies_conflicts(self):
        """
        8. Trusted successful conflict result verifies conflicts:
        Uses trusted provider evidence containing a conflicting event.
        Proves CALENDAR_VERIFIED_WITH_CONFLICTS, is_verified=True, and correct conflict filtering.
        """
        busy = [
            TimeSlot(
                start_time=datetime(2026, 9, 21, 9, 0, tzinfo=self.tz),
                end_time=datetime(2026, 9, 21, 10, 0, tzinfo=self.tz),
                timezone="America/Chicago",
                is_busy=True
            )
        ]
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=busy,
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_VERIFIED_WITH_CONFLICTS)
        self.assertTrue(res.is_verified)
        self.assertGreater(res.conflict_count, 0)
        self.assertIn("Here are a few times I am currently available", res.formatted_summary)

    def test_regression_9_trusted_provider_error_cannot_verify_clear(self):
        """
        9. Trusted provider error cannot verify clear:
        Forces a provider error through trusted evidence object.
        Proves CALENDAR_ERROR and is_verified=False.
        """
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.ERROR,
            raw_error="HTTP 503 Service Unavailable",
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_ERROR)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)

    def test_regression_10_trusted_provider_unavailable_cannot_verify_clear(self):
        """
        10. Trusted provider unavailable cannot verify clear:
        Tests unavailable provider state through trusted evidence object.
        Proves CALENDAR_UNAVAILABLE, is_verified=False, pending wording.
        """
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.UNAVAILABLE,
            provider_name="google_calendar"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        self.assertEqual(res.verification_status, CalendarVerificationStatus.CALENDAR_UNAVAILABLE)
        self.assertFalse(res.is_verified)
        self.assertNotIn("I am currently available", res.formatted_summary)
        self.assertIn("pending calendar verification", res.formatted_summary)

    def test_regression_11_unverified_generated_communication_remains_proposed(self):
        """
        11. Unverified generated communication remains proposed:
        Exercises the generated communication path when calendar is unverified.
        Proves proposed/pending semantics and absence of confirmed availability claims.
        """
        res = calculate_optimal_booking_windows(self.base_req)
        formatted = format_availability_text(res.available_windows, verification_status=res.verification_status)
        self.assertNotIn("Here are a few times I am currently available", formatted)
        self.assertIn("Here are some proposed times for a brief conversation (pending calendar verification):", formatted)
        self.assertIn("These windows are pending calendar verification", formatted)

    def test_regression_12_verified_communication_requires_trusted_provenance(self):
        """
        12. Verified communication requires trusted provenance:
        Generates communication from legitimate trusted verified-clear result.
        Proves confirmed availability wording is emitted.
        """
        evidence = TrustedCalendarEvidence(
            outcome=CalendarProviderOutcome.SUCCESS,
            busy_slots=[],
            provider_name="microsoft_graph"
        )
        res = calculate_optimal_booking_windows(self.base_req, evidence)
        formatted = format_availability_text(res.available_windows, verification_status=res.verification_status)
        self.assertIn("Here are a few times I am currently available for a brief conversation:", formatted)
        self.assertNotIn("pending calendar verification", formatted)


if __name__ == "__main__":
    unittest.main()

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
            preferred_hours_end=17
        )
        res = calculate_optimal_booking_windows(busy_slots, req)
        self.assertGreater(len(res.available_windows), 0)
        self.assertEqual(res.busy_slots_count, 1)
        self.assertIn("Here are a few times", res.formatted_summary)

if __name__ == "__main__":
    unittest.main()

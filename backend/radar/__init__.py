"""
Opportunity Radar & Scribe Capability Package
Provides inbound message triage, anti-phishing/noise filtering, opportunity fit scoring, and CCS-grounded response generation.
"""

from backend.radar.triage_service import (
    classify_email_radar,
    extract_recruiter_details,
    calculate_opportunity_fit_score
)
from backend.radar.scribe_service import (
    generate_executive_reply,
    compose_grounded_response
)

__all__ = [
    "classify_email_radar",
    "extract_recruiter_details",
    "calculate_opportunity_fit_score",
    "generate_executive_reply",
    "compose_grounded_response"
]

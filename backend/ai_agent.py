"""
AI Agent & Executive Assistant Module (Unified Facade)
Re-exports capabilities from backend.radar and backend.calendar_broker for seamless integration.
"""

import logging
from typing import Optional

from backend.models import (
    EmailMessage,
    ClassificationResult,
    EmailCategory,
    RecruiterDetails,
    UserProfile,
    ReplyDraftRequest
)

# Delegated to Opportunity Radar Capability Package
from backend.radar.triage_service import (
    classify_email_radar as classify_email,
    extract_recruiter_details as _extract_recruiter_details_heuristic,
    calculate_opportunity_fit_score,
    get_gemini_client,
    _classify_heuristics
)

from backend.radar.scribe_service import (
    generate_executive_reply as generate_personalized_reply,
    compose_grounded_response
)

# Delegated to Calendar Broker Capability Package
from backend.calendar_broker.availability_service import (
    calculate_optimal_booking_windows,
    format_availability_text
)

__all__ = [
    "classify_email",
    "generate_personalized_reply",
    "_extract_recruiter_details_heuristic",
    "calculate_opportunity_fit_score",
    "get_gemini_client",
    "compose_grounded_response",
    "calculate_optimal_booking_windows",
    "format_availability_text"
]

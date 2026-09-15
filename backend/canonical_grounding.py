"""
Canonical Career Grounding & Contextual Claim Validation Engine (CCS v2.1 — Phase 5.3)
Implements authoritative deterministic schema-driven affirmative tuple matching for career-sensitive claims.

SECURITY & INFORMATION-INTEGRITY INVARIANTS:
1. Complete Fact-Tuple Verification: A career claim is grounded ONLY when one authoritative structured
   record affirmatively validates EVERY material dimension (value, precision, metric, outcome, attribution,
   employer/scope, and chronology).
2. Schema-Driven Matcher: No fact is authorized by numeric value alone or absence of forbidden terms.
   All declared required dimensions must be affirmatively satisfied.
3. Separation of Held Titles vs Target Titles: First-person assertions of holding a title validate ONLY
   against HELD_EMPLOYMENT_TITLE or an approved display alias bound to that specific employment record
   via exact normalized alias matching. Substring containment is strictly forbidden.
4. Structural Employer Binding: Every employer-bound quantitative claim must have its required canonical
   employer bound directly in the local claim proposition. Conflicting or non-canonical organizations
   in employer/scope positions fail closed without relying on finite company denylists.
5. Generic Multi-Tenure Chronology: All chronology assertions are evaluated generically against structured
   CanonicalEmploymentRecord instances, selecting among multi-tenure records using title, dates, and status.
6. Negation and Disclaimer Detection: Accomplishment claims governed by negation, disclaimers, or reported-speech
   fail closed as UNSUPPORTED or INDETERMINATE (never grounded).
7. Positive Career Assertion Detection & Indeterminate Handling: Text containing likely career, payroll,
   or employment assertions that cannot be reliably parsed/resolved must return INDETERMINATE/VALIDATION_FAILED
   (is_grounded=False). Only genuine claim-free prose returns NO_CAREER_CLAIMS.
8. Fail-Closed on Malformed Input: Non-string, empty, whitespace, or raw serialized objects fail closed.
9. Zero Transmission Authority: Grounding validation is strictly an information-integrity boundary;
   it never grants or invokes email transmission authority.
"""

import re
import os
import math
import hashlib
import logging
import time
import uuid
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple, Union
from enum import Enum
from pydantic import BaseModel, Field

logger = logging.getLogger("canonical_grounding")

CANONICAL_LEDGER_SCHEMA_VERSION = "2.1.0"
RECORD_SCHEMA_VERSION = 2


class InvalidationPersistenceError(RuntimeError):
    """
    Raised when draft or claim invalidation fails to persist to disk.
    Indicates that the affected draft identity has been placed into fail-closed quarantine.
    """
    def __init__(self, target_id: str, message: str):
        super().__init__(message)
        self.target_id = target_id


class RecoveryStrategy(str, Enum):
    RESET_ALL_PROVENANCE = "RESET_ALL_PROVENANCE"


class RecoveryExecutionContext(str, Enum):
    LOCAL_ADMIN_MAINTENANCE = "LOCAL_ADMIN_MAINTENANCE"


class RecoveryAuthorizationError(PermissionError):
    """Raised when administrative recovery authorization is missing, invalid, or unauthorized."""
    pass


@dataclass(frozen=True)
class AdministrativeRecoveryContext:
    """
    Immutable typed context object required to authorize administrative recovery.
    Must be invoked only within LOCAL_ADMIN_MAINTENANCE execution context with valid local auth evidence.
    """
    actor: str
    execution_context: RecoveryExecutionContext
    explicitly_confirmed: bool
    authorization_evidence: str



class GroundingStatus(str, Enum):
    GROUNDED = "GROUNDED"
    UNVERIFIED = "UNVERIFIED"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    INDETERMINATE = "INDETERMINATE"
    STALE_PROVENANCE = "STALE_PROVENANCE"
    INVALIDATED = "INVALIDATED"
    NO_CAREER_CLAIMS_DETECTED = "NO_CAREER_CLAIMS_DETECTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    MIXED_REVIEW_REQUIRED = "MIXED_REVIEW_REQUIRED"

    # Backward compatibility aliases
    UNGROUNDED = "UNVERIFIED"
    NO_CAREER_CLAIMS = "NO_CAREER_CLAIMS_DETECTED"


class ClaimCategory(str, Enum):
    MONETARY = "MONETARY"
    PERCENTAGE = "PERCENTAGE"
    EMPLOYER = "EMPLOYER"
    TITLE = "TITLE"
    DATE_TENURE = "DATE_TENURE"
    PORTFOLIO = "PORTFOLIO"
    PIPELINE = "PIPELINE"
    HEADCOUNT = "HEADCOUNT"
    PERFORMANCE_IMPROVEMENT = "PERFORMANCE_IMPROVEMENT"
    QUALIFIER = "QUALIFIER"
    CHRONOLOGY = "CHRONOLOGY"


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    UNVERIFIED = "UNVERIFIED"
    MISATTRIBUTED = "MISATTRIBUTED"
    DISALLOWED_QUALIFIER = "DISALLOWED_QUALIFIER"
    INSUFFICIENT_PRECISION = "INSUFFICIENT_PRECISION"
    INDETERMINATE = "INDETERMINATE"
    STALE_PROVENANCE = "STALE_PROVENANCE"
    INVALIDATED = "INVALIDATED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class TitleCategory(str, Enum):
    HELD_EMPLOYMENT_TITLE = "HELD_EMPLOYMENT_TITLE"
    APPROVED_DISPLAY_ALIAS = "APPROVED_DISPLAY_ALIAS"
    PROFESSIONAL_POSITIONING_DESCRIPTOR = "PROFESSIONAL_POSITIONING_DESCRIPTOR"
    TARGET_ROLE_TITLE = "TARGET_ROLE_TITLE"


class PrecisionPolicy(str, Enum):
    EXACT_REQUIRED = "EXACT_REQUIRED"         # Must not have '+' modifier
    PLUS_REQUIRED = "PLUS_REQUIRED"           # Strictly requires '+' modifier (e.g. $100M+, $2M+)
    PLUS_PERMITTED = "PLUS_PERMITTED"


class ScopePolicy(str, Enum):
    CAREER_WIDE_REQUIRED = "CAREER_WIDE_REQUIRED"       # Career-wide, single employer forbidden
    EMPLOYER_BOUND_REQUIRED = "EMPLOYER_BOUND_REQUIRED" # Must match designated canonical employer
    EMPLOYER_OPTIONAL = "EMPLOYER_OPTIONAL"


class SupportedClaim(BaseModel):
    fact_id: str
    category: ClaimCategory
    extracted_text: str
    canonical_reference: str
    confidence: float = 1.0


class UnsupportedClaim(BaseModel):
    category: ClaimCategory
    extracted_text: str
    reason: str
    status: ClaimStatus = ClaimStatus.UNSUPPORTED


class GroundingValidationResult(BaseModel):
    is_grounded: bool = False
    status: GroundingStatus = GroundingStatus.VALIDATION_FAILED
    requires_human_review: bool = True
    supported_claims: List[SupportedClaim] = Field(default_factory=list)
    unsupported_claims: List[UnsupportedClaim] = Field(default_factory=list)
    verified_fact_ids: List[str] = Field(default_factory=list)
    validation_summary: str = ""


# ---------------------------------------------------------------------------
# Authoritative Structured Employment Ledger (CCS v2.1 — Section 5)
# ---------------------------------------------------------------------------

class CanonicalEmploymentRecord(BaseModel):
    employer_key: str
    employer_canonical: str
    employer_aliases: List[str]
    held_titles: List[str]
    approved_display_aliases: List[str] = Field(default_factory=list)
    engagement_type: str  # "DIRECT_EMPLOYMENT", "CONTRACT_ADVISORY"
    start_year: int
    start_month: Optional[int] = None
    end_year: Optional[int] = None
    end_month: Optional[int] = None
    is_current: bool = False


CANONICAL_EMPLOYMENT_RECORDS: Dict[str, CanonicalEmploymentRecord] = {
    "mavencode_advisory": CanonicalEmploymentRecord(
        employer_key="mavencode_advisory",
        employer_canonical="MavenCode",
        employer_aliases=["mavencode", "maven code"],
        held_titles=[
            "strategic advisor, data & ai",
            "strategic advisor",
            "data & ai strategic advisor",
            "advisor, data & ai"
        ],
        approved_display_aliases=["strategic advisor", "advisor"],
        engagement_type="CONTRACT_ADVISORY",
        start_year=2026,
        start_month=9,
        end_year=None,
        end_month=None,
        is_current=True
    ),
    "mavencode_director": CanonicalEmploymentRecord(
        employer_key="mavencode_director",
        employer_canonical="MavenCode",
        employer_aliases=["mavencode", "maven code"],
        held_titles=[
            "director, data analytics & ai strategy / principal solutions architect",
            "director, data analytics & ai strategy",
            "principal solutions architect"
        ],
        approved_display_aliases=[
            "director of data analytics & ai strategy",
            "director of data analytics",
            "principal solutions architect"
        ],
        engagement_type="DIRECT_EMPLOYMENT",
        start_year=2024,
        start_month=10,
        end_year=2026,
        end_month=2,
        is_current=False
    ),
    "promevo": CanonicalEmploymentRecord(
        employer_key="promevo",
        employer_canonical="Promevo",
        employer_aliases=["promevo"],
        held_titles=[
            "advisory solutions architect, data cloud & ai sme",
            "advisory solutions architect"
        ],
        approved_display_aliases=[
            "solutions architect",
            "data cloud & ai sme",
            "cloud & ai sme"
        ],
        engagement_type="DIRECT_EMPLOYMENT",
        start_year=2026,
        start_month=3,
        end_year=2026,
        end_month=8,
        is_current=False
    ),
    "cdw": CanonicalEmploymentRecord(
        employer_key="cdw",
        employer_canonical="CDW",
        employer_aliases=["cdw", "cdw cloud", "cdw corporation"],
        held_titles=[
            "senior solutions architect — digital data & analytics strategist",
            "senior solutions architect"
        ],
        approved_display_aliases=[
            "solutions architect",
            "digital data & analytics strategist"
        ],
        engagement_type="DIRECT_EMPLOYMENT",
        start_year=2023,
        start_month=11,
        end_year=2024,
        end_month=10,
        is_current=False
    ),
    "pythian": CanonicalEmploymentRecord(
        employer_key="pythian",
        employer_canonical="Pythian",
        employer_aliases=["pythian", "pythian services"],
        held_titles=[
            "principal cloud solutions architect — gcp pde",
            "principal cloud solutions architect"
        ],
        approved_display_aliases=[
            "cloud solutions architect",
            "gcp pde architect"
        ],
        engagement_type="DIRECT_EMPLOYMENT",
        start_year=2021,
        start_month=11,
        end_year=2023,
        end_month=5,
        is_current=False
    ),
    "google": CanonicalEmploymentRecord(
        employer_key="google",
        employer_canonical="Google",
        employer_aliases=["google", "google cloud", "alphabet"],
        held_titles=[
            "cloud customer engineer — data & ai solutions",
            "cloud customer engineer"
        ],
        approved_display_aliases=[
            "data cloud customer engineer",
            "customer engineer"
        ],
        engagement_type="DIRECT_EMPLOYMENT",
        start_year=2019,
        start_month=10,
        end_year=2021,
        end_month=11,
        is_current=False
    ),
    "dxc": CanonicalEmploymentRecord(
        employer_key="dxc",
        employer_canonical="DXC Technology",
        employer_aliases=["dxc", "dxc technology", "dxc tech", "computer sciences corporation", "csc"],
        held_titles=[
            "principal solution architect — otco analytics & ai lead",
            "principal solution architect",
            "principal solutions architect"
        ],
        approved_display_aliases=[
            "solution architect",
            "analytics & ai lead"
        ],
        engagement_type="DIRECT_EMPLOYMENT",
        start_year=2015,
        start_month=3,
        end_year=2019,
        end_month=10,
        is_current=False
    ),
    "ibm": CanonicalEmploymentRecord(
        employer_key="ibm",
        employer_canonical="IBM",
        employer_aliases=["ibm", "ibm software group", "international business machines"],
        held_titles=[
            "watson analytics solution architect — big data paas sme",
            "watson analytics solution architect"
        ],
        approved_display_aliases=[
            "solution architect",
            "analytics solution architect"
        ],
        engagement_type="DIRECT_EMPLOYMENT",
        start_year=2002,
        start_month=1,
        end_year=2015,
        end_month=3,
        is_current=False
    )
}

# Explicit Title Categorization
POSITIONING_DESCRIPTORS = {
    "ai & data governance leader",
    "enterprise cloud, data & ai solutions architecture advisor",
    "technology strategist",
    "trusted advisor",
    "enterprise architect",
    "cloud architect",
    "data platform architect"
}

TARGET_ROLE_TITLES = {
    "field cto",
    "chief technology officer",
    "cto",
    "practice director",
    "practice leader",
    "interim head of ai",
    "head of ai",
    "technical program manager",
    "principal technical program manager",
    "tpm",
    "vice president of engineering",
    "vp of engineering",
    "vp of sales",
    "chief executive officer",
    "ceo",
    "chief financial officer",
    "cfo",
    "director of data governance",
    "presales advisory lead"
}

APPROVED_PAST_EMPLOYERS = {r.employer_canonical for r in CANONICAL_EMPLOYMENT_RECORDS.values()}
APPROVED_TITLES = set()
for r in CANONICAL_EMPLOYMENT_RECORDS.values():
    APPROVED_TITLES.update(r.held_titles)
    APPROVED_TITLES.update(r.approved_display_aliases)

AUTHORITATIVE_CAREER_TITLES = APPROVED_TITLES


# ---------------------------------------------------------------------------
# Quantitative Canonical Fact Schema & Registry
# ---------------------------------------------------------------------------

class CanonicalFactDefinition(BaseModel):
    fact_id: str
    category: ClaimCategory
    canonical_text: str
    normalized_value: float
    display_value: str
    precision_policy: PrecisionPolicy
    required_metric_aliases: List[str]
    forbidden_metric_aliases: List[str] = Field(default_factory=list)
    required_attribution_aliases: List[str]
    forbidden_attribution_aliases: List[str] = Field(default_factory=list)
    scope_policy: ScopePolicy
    required_employer: Optional[str] = None
    allowed_employer_aliases: List[str] = Field(default_factory=list)
    required_scope_aliases: List[str] = Field(default_factory=list)
    conflicting_scope_aliases: List[str] = Field(default_factory=list)


CANONICAL_FACT_REGISTRY: Dict[str, CanonicalFactDefinition] = {
    "FACT_GOOGLE_REVENUE": CanonicalFactDefinition(
        fact_id="FACT_GOOGLE_REVENUE",
        category=ClaimCategory.MONETARY,
        canonical_text="Influenced $8M in new Google Cloud revenue at Google",
        normalized_value=8_000_000,
        display_value="$8M",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=[
            "google cloud revenue", "cloud revenue", "gcp revenue", "new google cloud revenue",
            "new revenue", "partner revenue", "arr", "sales revenue", "cloud arr", "revenue"
        ],
        forbidden_metric_aliases=["lottery", "crypto", "cryptocurrency", "salary", "bonus", "commission", "quota", "personal revenue", "winnings"],
        required_attribution_aliases=[
            "influenced", "influence", "influencing", "advised", "advisory", "assisted",
            "driven in advisory", "contributed to", "helped drive", "helped influence", "influenced and delivered"
        ],
        forbidden_attribution_aliases=[
            "stole", "steal", "stealing", "generated", "generate", "generating",
            "closed", "close", "closing", "sold", "sell", "selling",
            "booked", "book", "booking", "billed", "bill", "my revenue", "my personal revenue",
            "salary", "earned", "commission", "bonus", "quota"
        ],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="google",
        allowed_employer_aliases=["google", "google cloud", "gcp", "alphabet"]
    ),
    "FACT_CAREER_IMPACT": CanonicalFactDefinition(
        fact_id="FACT_CAREER_IMPACT",
        category=ClaimCategory.MONETARY,
        canonical_text="$100M+ enterprise revenue influenced and delivered across career",
        normalized_value=100_000_000,
        display_value="$100M+",
        precision_policy=PrecisionPolicy.PLUS_REQUIRED,
        required_metric_aliases=[
            "enterprise revenue", "enterprise value", "revenue", "value", "delivered revenue",
            "pipeline and revenue", "enterprise impact", "value delivered", "total revenue"
        ],
        forbidden_metric_aliases=["lottery", "crypto", "cryptocurrency", "salary", "bonus", "commission", "contracts won", "winnings"],
        required_attribution_aliases=[
            "influenced", "delivered", "influenced and delivered", "delivered and influenced",
            "contributed to delivering", "helped deliver", "impact", "delivered across"
        ],
        forbidden_attribution_aliases=[
            "stole", "won", "booked", "personally booked", "salary", "earned", "quota", "commission"
        ],
        scope_policy=ScopePolicy.CAREER_WIDE_REQUIRED,
        required_scope_aliases=[
            "career", "across career", "over my career", "throughout my career",
            "total", "cross-functional", "enterprise-wide", "overall", "across my career"
        ],
        conflicting_scope_aliases=[
            "at promevo", "at amazon", "at meta", "at google", "at cdw", "at dxc", "at stripe", "at acme"
        ]
    ),
    "FACT_CDW_SERVICES": CanonicalFactDefinition(
        fact_id="FACT_CDW_SERVICES",
        category=ClaimCategory.MONETARY,
        canonical_text="Closed $2.1M in services at CDW",
        normalized_value=2_100_000,
        display_value="$2.1M",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["services", "professional services", "consulting services", "solutions", "services closed"],
        forbidden_metric_aliases=["salary", "annual revenue", "compensation", "bonus", "crypto", "lottery", "winnings"],
        required_attribution_aliases=["closed", "close", "closing", "delivered", "services closed"],
        forbidden_attribution_aliases=["earned", "stole", "salary", "commission", "quota", "influenced annual revenue"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="cdw",
        allowed_employer_aliases=["cdw", "cdw cloud", "cdw corporation"]
    ),
    "FACT_CDW_REVENUE": CanonicalFactDefinition(
        fact_id="FACT_CDW_REVENUE",
        category=ClaimCategory.MONETARY,
        canonical_text="Influenced $4M in annual revenue at CDW",
        normalized_value=4_000_000,
        display_value="$4M",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["annual revenue", "annualized revenue", "revenue", "cloud revenue"],
        forbidden_metric_aliases=["cryptocurrency", "crypto", "lottery", "salary", "services", "quota", "winnings"],
        required_attribution_aliases=["influenced", "influence", "influencing", "driven", "advised", "assisted"],
        forbidden_attribution_aliases=["generated", "generate", "closed", "close", "sold", "stole", "salary", "earned", "quota", "portfolio", "services"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="cdw",
        allowed_employer_aliases=["cdw", "cdw cloud", "cdw corporation"]
    ),
    "FACT_PROMEVO_PIPELINE": CanonicalFactDefinition(
        fact_id="FACT_PROMEVO_PIPELINE",
        category=ClaimCategory.PIPELINE,
        canonical_text="Pipeline contribution estimated $2M+ at Promevo",
        normalized_value=2_000_000,
        display_value="$2M+",
        precision_policy=PrecisionPolicy.PLUS_REQUIRED,
        required_metric_aliases=["pipeline", "pipeline contribution", "estimated pipeline", "presales pipeline", "deal pipeline"],
        forbidden_metric_aliases=["closed revenue", "salary", "crypto", "lottery", "winnings"],
        required_attribution_aliases=["contributed to", "contributed", "estimated", "influenced", "built", "drove", "delivered"],
        forbidden_attribution_aliases=["closed", "closed revenue", "salary", "earned", "stole", "quota"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="promevo",
        allowed_employer_aliases=["promevo"]
    ),
    "FACT_DXC_PORTFOLIO": CanonicalFactDefinition(
        fact_id="FACT_DXC_PORTFOLIO",
        category=ClaimCategory.PORTFOLIO,
        canonical_text="$22M portfolio with shared GTM P&L responsibility at DXC",
        normalized_value=22_000_000,
        display_value="$22M",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["portfolio", "analytics and ai portfolio", "gtm p&l", "p&l", "business unit portfolio"],
        forbidden_metric_aliases=["personal quota", "quota", "sales quota", "salary", "earned", "sales target", "lottery", "crypto", "winnings"],
        required_attribution_aliases=["led", "oversaw", "managed", "shared responsibility", "responsibility", "oversight", "portfolio"],
        forbidden_attribution_aliases=["carried a sales quota", "carried a $22m sales quota", "personally generated", "quota", "salary", "earned", "closed"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="dxc",
        allowed_employer_aliases=["dxc", "dxc technology", "dxc tech"]
    ),
    "FACT_PROMEVO_POC_CONVERSION": CanonicalFactDefinition(
        fact_id="FACT_PROMEVO_POC_CONVERSION",
        category=ClaimCategory.PERCENTAGE,
        canonical_text="23% POC-to-production conversion rate at Promevo",
        normalized_value=23.0,
        display_value="23%",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["poc", "conversion", "poc-to-production", "production conversion", "pilot conversion", "win rate"],
        forbidden_metric_aliases=["customer satisfaction", "csat", "revenue", "cost", "headcount", "margin", "uptime", "latency", "turnaround", "lottery"],
        required_attribution_aliases=["achieved", "conversion", "rate", "grew", "delivered", "resulted in", "improved", "drove"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="promevo",
        allowed_employer_aliases=["promevo"]
    ),
    "FACT_PROMEVO_SCOPING_TURNAROUND": CanonicalFactDefinition(
        fact_id="FACT_PROMEVO_SCOPING_TURNAROUND",
        category=ClaimCategory.PERCENTAGE,
        canonical_text="40% reduced scoping turnaround at Promevo",
        normalized_value=40.0,
        display_value="40%",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["scoping", "turnaround", "reduced scoping", "scoping time", "scoping turnaround"],
        forbidden_metric_aliases=["headcount", "cost", "revenue", "margin", "customer satisfaction", "csat", "uptime", "conversion", "lottery"],
        required_attribution_aliases=["reduced", "reduction", "turnaround", "achieved", "delivered"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="promevo",
        allowed_employer_aliases=["promevo"]
    ),
    "FACT_PROMEVO_SALES_CYCLES": CanonicalFactDefinition(
        fact_id="FACT_PROMEVO_SALES_CYCLES",
        category=ClaimCategory.PERCENTAGE,
        canonical_text="20% shorter sales cycles at Promevo",
        normalized_value=20.0,
        display_value="20%",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["sales cycle", "sales cycles", "shorter cycle", "cycle reduction", "deal cycle", "sales duration"],
        forbidden_metric_aliases=["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "uptime", "lottery"],
        required_attribution_aliases=["shorter", "reduced", "reduction", "shortened", "faster"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="promevo",
        allowed_employer_aliases=["promevo"]
    ),
    "FACT_PROMEVO_LEGACY_COMPLEXITY": CanonicalFactDefinition(
        fact_id="FACT_PROMEVO_LEGACY_COMPLEXITY",
        category=ClaimCategory.PERCENTAGE,
        canonical_text="25% reduction in legacy architecture complexity at Promevo",
        normalized_value=25.0,
        display_value="25%",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["legacy", "complexity", "architecture complexity", "legacy architecture", "technical debt", "simplification"],
        forbidden_metric_aliases=["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "sales cycle"],
        required_attribution_aliases=["reduction", "reduced", "simplification", "simplified"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="promevo",
        allowed_employer_aliases=["promevo"]
    ),
    "FACT_PROMEVO_TIME_TO_VALUE": CanonicalFactDefinition(
        fact_id="FACT_PROMEVO_TIME_TO_VALUE",
        category=ClaimCategory.PERCENTAGE,
        canonical_text="33% faster time-to-value at Promevo",
        normalized_value=33.0,
        display_value="33%",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["time-to-value", "time to value", "faster delivery", "deployment time", "implementation time", "value delivery"],
        forbidden_metric_aliases=["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "complexity"],
        required_attribution_aliases=["faster", "accelerated", "time-to-value", "speed"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="promevo",
        allowed_employer_aliases=["promevo"]
    ),
    "FACT_PROMEVO_EFFICIENCY_ROADMAP": CanonicalFactDefinition(
        fact_id="FACT_PROMEVO_EFFICIENCY_ROADMAP",
        category=ClaimCategory.PERCENTAGE,
        canonical_text="30% targeted presales efficiency improvement at Promevo",
        normalized_value=30.0,
        display_value="30%",
        precision_policy=PrecisionPolicy.EXACT_REQUIRED,
        required_metric_aliases=["efficiency", "presales efficiency", "efficiency roadmap", "roadmap improvement", "presales roadmap", "efficiency target"],
        forbidden_metric_aliases=["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "sales cycle"],
        required_attribution_aliases=["target", "targeting", "improvement", "roadmap", "improved"],
        scope_policy=ScopePolicy.EMPLOYER_BOUND_REQUIRED,
        required_employer="promevo",
        allowed_employer_aliases=["promevo"]
    )
}


# ---------------------------------------------------------------------------
# Approved Deterministic Claim Templates (Phase 5.5 — Section 6)
# ---------------------------------------------------------------------------

class CanonicalClaimTemplate(BaseModel):
    template_id: str
    template_version: str = "2.0.0"
    fact_id: str
    employment_record_id: Optional[str] = None
    category: ClaimCategory
    style_variant: str  # "concise", "resume_bullet", "conversational"
    rendered_text: str
    description: str


CANONICAL_CLAIM_TEMPLATES: Dict[str, CanonicalClaimTemplate] = {
    # 1. Google Revenue
    "TPL_GOOGLE_REVENUE_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_GOOGLE_REVENUE_CONCISE",
        fact_id="FACT_GOOGLE_REVENUE",
        category=ClaimCategory.MONETARY,
        style_variant="concise",
        rendered_text="At Google, I influenced $8M in new Google Cloud revenue.",
        description="Concise sentence stating $8M new Google Cloud revenue influenced at Google."
    ),
    "TPL_GOOGLE_REVENUE_RESUME": CanonicalClaimTemplate(
        template_id="TPL_GOOGLE_REVENUE_RESUME",
        fact_id="FACT_GOOGLE_REVENUE",
        category=ClaimCategory.MONETARY,
        style_variant="resume_bullet",
        rendered_text="Influenced $8M in new Google Cloud revenue across enterprise customer engagements at Google.",
        description="Résumé-style achievement for Google Cloud revenue."
    ),
    "TPL_GOOGLE_REVENUE_CONVERSATIONAL": CanonicalClaimTemplate(
        template_id="TPL_GOOGLE_REVENUE_CONVERSATIONAL",
        fact_id="FACT_GOOGLE_REVENUE",
        category=ClaimCategory.MONETARY,
        style_variant="conversational",
        rendered_text="During my tenure at Google, I influenced $8M in new Google Cloud revenue.",
        description="Conversational professional statement for Google Cloud revenue."
    ),

    # 2. Career Enterprise Revenue
    "TPL_CAREER_ENTERPRISE_REVENUE_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_CAREER_ENTERPRISE_REVENUE_CONCISE",
        fact_id="FACT_CAREER_IMPACT",
        category=ClaimCategory.MONETARY,
        style_variant="concise",
        rendered_text="Across my career, I influenced and delivered $100M+ in enterprise revenue.",
        description="Concise sentence for $100M+ career enterprise revenue."
    ),
    "TPL_CAREER_ENTERPRISE_REVENUE_RESUME": CanonicalClaimTemplate(
        template_id="TPL_CAREER_ENTERPRISE_REVENUE_RESUME",
        fact_id="FACT_CAREER_IMPACT",
        category=ClaimCategory.MONETARY,
        style_variant="resume_bullet",
        rendered_text="Influenced and delivered $100M+ in enterprise revenue across 20+ years of technical architecture leadership.",
        description="Résumé-style achievement for career revenue impact."
    ),
    "TPL_CAREER_ENTERPRISE_REVENUE_CONVERSATIONAL": CanonicalClaimTemplate(
        template_id="TPL_CAREER_ENTERPRISE_REVENUE_CONVERSATIONAL",
        fact_id="FACT_CAREER_IMPACT",
        category=ClaimCategory.MONETARY,
        style_variant="conversational",
        rendered_text="Over my career, I have influenced and delivered $100M+ in enterprise revenue.",
        description="Conversational phrasing for career revenue impact."
    ),

    # 3. CDW Services
    "TPL_CDW_SERVICES_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_CDW_SERVICES_CONCISE",
        fact_id="FACT_CDW_SERVICES",
        category=ClaimCategory.MONETARY,
        style_variant="concise",
        rendered_text="At CDW, I closed $2.1M in professional services.",
        description="Concise sentence for $2.1M services closed at CDW."
    ),
    "TPL_CDW_SERVICES_RESUME": CanonicalClaimTemplate(
        template_id="TPL_CDW_SERVICES_RESUME",
        fact_id="FACT_CDW_SERVICES",
        category=ClaimCategory.MONETARY,
        style_variant="resume_bullet",
        rendered_text="Closed $2.1M in professional services engagements at CDW.",
        description="Résumé-style achievement for CDW services."
    ),
    "TPL_CDW_SERVICES_CONVERSATIONAL": CanonicalClaimTemplate(
        template_id="TPL_CDW_SERVICES_CONVERSATIONAL",
        fact_id="FACT_CDW_SERVICES",
        category=ClaimCategory.MONETARY,
        style_variant="conversational",
        rendered_text="While at CDW, I closed $2.1M in professional services.",
        description="Conversational statement for CDW services."
    ),

    # 4. CDW Annual Revenue
    "TPL_CDW_REVENUE_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_CDW_REVENUE_CONCISE",
        fact_id="FACT_CDW_REVENUE",
        category=ClaimCategory.MONETARY,
        style_variant="concise",
        rendered_text="At CDW, I influenced $4M in annual revenue.",
        description="Concise sentence for $4M annual revenue influenced at CDW."
    ),
    "TPL_CDW_REVENUE_RESUME": CanonicalClaimTemplate(
        template_id="TPL_CDW_REVENUE_RESUME",
        fact_id="FACT_CDW_REVENUE",
        category=ClaimCategory.MONETARY,
        style_variant="resume_bullet",
        rendered_text="Influenced $4M in annual revenue through digital data and analytics solutions at CDW.",
        description="Résumé-style achievement for CDW revenue."
    ),
    "TPL_CDW_REVENUE_CONVERSATIONAL": CanonicalClaimTemplate(
        template_id="TPL_CDW_REVENUE_CONVERSATIONAL",
        fact_id="FACT_CDW_REVENUE",
        category=ClaimCategory.MONETARY,
        style_variant="conversational",
        rendered_text="During my time at CDW, I influenced $4M in annual revenue.",
        description="Conversational phrasing for CDW annual revenue."
    ),

    # 5. Promevo Pipeline
    "TPL_PROMEVO_PIPELINE_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_PIPELINE_CONCISE",
        fact_id="FACT_PROMEVO_PIPELINE",
        category=ClaimCategory.PIPELINE,
        style_variant="concise",
        rendered_text="At Promevo, I contributed to an estimated $2M+ pipeline.",
        description="Concise sentence for Promevo $2M+ pipeline contribution."
    ),
    "TPL_PROMEVO_PIPELINE_RESUME": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_PIPELINE_RESUME",
        fact_id="FACT_PROMEVO_PIPELINE",
        category=ClaimCategory.PIPELINE,
        style_variant="resume_bullet",
        rendered_text="Contributed to an estimated $2M+ presales pipeline at Promevo.",
        description="Résumé-style achievement for Promevo pipeline."
    ),
    "TPL_PROMEVO_PIPELINE_CONVERSATIONAL": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_PIPELINE_CONVERSATIONAL",
        fact_id="FACT_PROMEVO_PIPELINE",
        category=ClaimCategory.PIPELINE,
        style_variant="conversational",
        rendered_text="While at Promevo, I contributed to an estimated $2M+ pipeline.",
        description="Conversational statement for Promevo pipeline."
    ),

    # 6. DXC Portfolio
    "TPL_DXC_PORTFOLIO_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_DXC_PORTFOLIO_CONCISE",
        fact_id="FACT_DXC_PORTFOLIO",
        category=ClaimCategory.PORTFOLIO,
        style_variant="concise",
        rendered_text="At DXC Technology, I led a $22M analytics and AI portfolio.",
        description="Concise sentence for DXC $22M portfolio leadership."
    ),
    "TPL_DXC_PORTFOLIO_RESUME": CanonicalClaimTemplate(
        template_id="TPL_DXC_PORTFOLIO_RESUME",
        fact_id="FACT_DXC_PORTFOLIO",
        category=ClaimCategory.PORTFOLIO,
        style_variant="resume_bullet",
        rendered_text="Led a $22M analytics and AI portfolio with shared GTM P&L responsibility at DXC Technology.",
        description="Résumé-style achievement for DXC portfolio."
    ),
    "TPL_DXC_PORTFOLIO_CONVERSATIONAL": CanonicalClaimTemplate(
        template_id="TPL_DXC_PORTFOLIO_CONVERSATIONAL",
        fact_id="FACT_DXC_PORTFOLIO",
        category=ClaimCategory.PORTFOLIO,
        style_variant="conversational",
        rendered_text="During my time at DXC Technology, I managed a $22M analytics and AI portfolio.",
        description="Conversational statement for DXC portfolio."
    ),

    # 7. Percentage Facts
    "TPL_PROMEVO_POC_CONVERSION_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_POC_CONVERSION_CONCISE",
        fact_id="FACT_PROMEVO_POC_CONVERSION",
        category=ClaimCategory.PERCENTAGE,
        style_variant="concise",
        rendered_text="At Promevo, I achieved a 23% POC-to-production conversion rate.",
        description="23% POC conversion rate at Promevo."
    ),
    "TPL_PROMEVO_SCOPING_TURNAROUND_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_SCOPING_TURNAROUND_CONCISE",
        fact_id="FACT_PROMEVO_SCOPING_TURNAROUND",
        category=ClaimCategory.PERCENTAGE,
        style_variant="concise",
        rendered_text="At Promevo, I delivered a 40% reduced scoping turnaround.",
        description="40% reduced scoping turnaround at Promevo."
    ),
    "TPL_PROMEVO_SALES_CYCLES_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_SALES_CYCLES_CONCISE",
        fact_id="FACT_PROMEVO_SALES_CYCLES",
        category=ClaimCategory.PERCENTAGE,
        style_variant="concise",
        rendered_text="At Promevo, I achieved 20% shorter sales cycles.",
        description="20% shorter sales cycles at Promevo."
    ),
    "TPL_PROMEVO_LEGACY_COMPLEXITY_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_LEGACY_COMPLEXITY_CONCISE",
        fact_id="FACT_PROMEVO_LEGACY_COMPLEXITY",
        category=ClaimCategory.PERCENTAGE,
        style_variant="concise",
        rendered_text="At Promevo, I drove a 25% reduction in legacy architecture complexity.",
        description="25% reduction in legacy complexity at Promevo."
    ),
    "TPL_PROMEVO_TIME_TO_VALUE_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_TIME_TO_VALUE_CONCISE",
        fact_id="FACT_PROMEVO_TIME_TO_VALUE",
        category=ClaimCategory.PERCENTAGE,
        style_variant="concise",
        rendered_text="At Promevo, I achieved 33% faster time-to-value.",
        description="33% faster time-to-value at Promevo."
    ),
    "TPL_PROMEVO_EFFICIENCY_ROADMAP_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_PROMEVO_EFFICIENCY_ROADMAP_CONCISE",
        fact_id="FACT_PROMEVO_EFFICIENCY_ROADMAP",
        category=ClaimCategory.PERCENTAGE,
        style_variant="concise",
        rendered_text="At Promevo, I delivered a 30% targeted presales efficiency improvement.",
        description="30% targeted presales efficiency at Promevo."
    ),

    # 8. Employment Ledger Facts
    "TPL_EMP_MAVENCODE_ADVISORY_CONCISE": CanonicalClaimTemplate(
        template_id="TPL_EMP_MAVENCODE_ADVISORY_CONCISE",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_MAVENCODE_ADVISORY",
        employment_record_id="mavencode_advisory",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I currently serve as Strategic Advisor at MavenCode.",
        description="Current MavenCode advisory role."
    ),
    "TPL_EMP_MAVENCODE_ADVISORY_FULL": CanonicalClaimTemplate(
        template_id="TPL_EMP_MAVENCODE_ADVISORY_FULL",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_MAVENCODE_ADVISORY",
        employment_record_id="mavencode_advisory",
        category=ClaimCategory.EMPLOYER,
        style_variant="conversational",
        rendered_text="I currently serve as Strategic Advisor, Data & AI at MavenCode.",
        description="Current MavenCode Strategic Advisor, Data & AI role."
    ),
    "TPL_EMP_MAVENCODE_DIRECTOR": CanonicalClaimTemplate(
        template_id="TPL_EMP_MAVENCODE_DIRECTOR",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_MAVENCODE_DIRECTOR",
        employment_record_id="mavencode_director",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I served as Director, Data Analytics & AI Strategy at MavenCode from 2024 to 2026.",
        description="Former Director tenure at MavenCode."
    ),
    "TPL_EMP_PROMEVO": CanonicalClaimTemplate(
        template_id="TPL_EMP_PROMEVO",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_PROMEVO",
        employment_record_id="promevo",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I served as Advisory Solutions Architect at Promevo in 2026.",
        description="Promevo Advisory Solutions Architect tenure."
    ),
    "TPL_EMP_CDW": CanonicalClaimTemplate(
        template_id="TPL_EMP_CDW",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_CDW",
        employment_record_id="cdw",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I served as Senior Solutions Architect at CDW from 2023 to 2024.",
        description="CDW Senior Solutions Architect tenure."
    ),
    "TPL_EMP_PYTHIAN": CanonicalClaimTemplate(
        template_id="TPL_EMP_PYTHIAN",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_PYTHIAN",
        employment_record_id="pythian",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I served as Principal Cloud Solutions Architect at Pythian from 2021 to 2023.",
        description="Pythian Principal Cloud Solutions Architect tenure."
    ),
    "TPL_EMP_GOOGLE": CanonicalClaimTemplate(
        template_id="TPL_EMP_GOOGLE",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_GOOGLE",
        employment_record_id="google",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I served as Cloud Customer Engineer at Google from 2019 to 2021.",
        description="Google Cloud Customer Engineer tenure."
    ),
    "TPL_EMP_DXC": CanonicalClaimTemplate(
        template_id="TPL_EMP_DXC",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_DXC",
        employment_record_id="dxc",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I served at DXC Technology from 2015 to 2019.",
        description="DXC Technology tenure."
    ),
    "TPL_EMP_IBM": CanonicalClaimTemplate(
        template_id="TPL_EMP_IBM",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_IBM",
        employment_record_id="ibm",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I served at IBM from 2002 to 2015.",
        description="IBM tenure."
    ),
    "TPL_EMP_IBM_WATSON": CanonicalClaimTemplate(
        template_id="TPL_EMP_IBM_WATSON",
        template_version="2.0.0",
        fact_id="FACT_EMPLOYMENT_IBM_WATSON",
        employment_record_id="ibm",
        category=ClaimCategory.EMPLOYER,
        style_variant="concise",
        rendered_text="I held a key role at IBM Watson from 2007 to 2015 within my IBM tenure.",
        description="IBM Watson role."
    )
}


# ---------------------------------------------------------------------------
# Authoritative Version & Content Digest Enforcement (Phase 5.5.1)
# ---------------------------------------------------------------------------

def compute_sha256(data: str) -> str:
    """Computes deterministic SHA-256 hexadecimal digest of input UTF-8 string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def get_active_fact_digest(fact_id: str) -> str:
    """Computes authoritative content digest for a canonical fact or employment fact."""
    if fact_id in CANONICAL_FACT_REGISTRY:
        f = CANONICAL_FACT_REGISTRY[fact_id]
        payload = (
            f"{f.fact_id}|{f.category.value}|{f.canonical_text}|{f.normalized_value}|"
            f"{f.display_value}|{f.precision_policy.value}|"
            f"{','.join(sorted(f.required_metric_aliases))}|"
            f"{','.join(sorted(f.required_attribution_aliases))}|"
            f"{f.scope_policy.value}|{f.required_employer or ''}"
        )
        return compute_sha256(payload)
    elif fact_id.startswith("FACT_EMPLOYMENT_"):
        emp_key = "ibm" if fact_id == "FACT_EMPLOYMENT_IBM_WATSON" else fact_id.replace("FACT_EMPLOYMENT_", "").lower()
        if emp_key in CANONICAL_EMPLOYMENT_RECORDS:
            return get_active_employment_record_digest(emp_key)
    return ""


def get_active_employment_record_digest(emp_key: Optional[str]) -> str:
    """Computes authoritative content digest for a CanonicalEmploymentRecord."""
    if not emp_key or emp_key not in CANONICAL_EMPLOYMENT_RECORDS:
        return ""
    r = CANONICAL_EMPLOYMENT_RECORDS[emp_key]
    payload = (
        f"{r.employer_key}|{r.employer_canonical}|{','.join(sorted(r.held_titles))}|"
        f"{','.join(sorted(r.approved_display_aliases))}|{r.engagement_type}|"
        f"{r.start_year}|{r.start_month or 0}|{r.end_year or 0}|{r.end_month or 0}|{r.is_current}"
    )
    return compute_sha256(payload)


def get_active_template_digest(template_id: str) -> str:
    """Computes authoritative content digest for a CanonicalClaimTemplate."""
    if template_id not in CANONICAL_CLAIM_TEMPLATES:
        return ""
    t = CANONICAL_CLAIM_TEMPLATES[template_id]
    payload = (
        f"{t.template_id}|{t.template_version}|{t.fact_id}|{t.employment_record_id or ''}|"
        f"{t.category.value}|{t.style_variant}|{t.rendered_text}"
    )
    return compute_sha256(payload)


def get_active_ledger_digest() -> str:
    """Computes aggregate authoritative digest covering entire canonical ledger."""
    emp_digests = [f"{k}:{get_active_employment_record_digest(k)}" for k in sorted(CANONICAL_EMPLOYMENT_RECORDS.keys())]
    fact_digests = [f"{k}:{get_active_fact_digest(k)}" for k in sorted(CANONICAL_FACT_REGISTRY.keys())]
    tpl_digests = [f"{k}:{get_active_template_digest(k)}" for k in sorted(CANONICAL_CLAIM_TEMPLATES.keys())]
    payload = f"{CANONICAL_LEDGER_SCHEMA_VERSION}|{'#'.join(emp_digests)}|{'#'.join(fact_digests)}|{'#'.join(tpl_digests)}"
    return compute_sha256(payload)


# ---------------------------------------------------------------------------
# Server-Authoritative Provenance Store & Verification (Phase 5.5.1)
# ---------------------------------------------------------------------------

def is_valid_sha256(val: Any) -> bool:
    """Helper to validate SHA-256 64-character hexadecimal digest string."""
    return isinstance(val, str) and len(val) == 64 and all(c in "0123456789abcdefABCDEF" for c in val)


class ClaimBlockBinding(BaseModel):
    claim_instance_id: str
    draft_id: str
    block_id: str
    start_offset: int
    end_offset: int
    submitted_block_text: str

    def __init__(self, **data: Any):
        super().__init__(**data)
        if not isinstance(self.claim_instance_id, str) or not self.claim_instance_id.strip():
            raise ValueError("claim_instance_id must be a non-empty string")
        if not isinstance(self.draft_id, str) or not self.draft_id.strip():
            raise ValueError("draft_id must be a non-empty string")
        if not isinstance(self.block_id, str) or not self.block_id.strip():
            raise ValueError("block_id must be a non-empty string")
        if not isinstance(self.submitted_block_text, str) or not self.submitted_block_text.strip():
            raise ValueError("submitted_block_text must be a non-empty string")
        if type(self.start_offset) is not int or isinstance(self.start_offset, bool):
            raise ValueError("start_offset must be a non-boolean integer")
        if type(self.end_offset) is not int or isinstance(self.end_offset, bool):
            raise ValueError("end_offset must be a non-boolean integer")
        if self.start_offset < 0 or self.end_offset <= self.start_offset:
            raise ValueError(f"Invalid offset range [{self.start_offset}:{self.end_offset}]")


class ProvenanceRecord(BaseModel):
    claim_instance_id: str
    draft_id: str
    canonical_fact_id: str
    employment_record_id: Optional[str] = None
    template_id: str
    template_version: str
    template_digest: str
    ledger_version: str
    ledger_digest: str
    fact_version: str
    fact_digest: str
    employment_record_digest: Optional[str] = None
    rendering_parameters: Dict[str, Any] = Field(default_factory=dict)
    exact_rendered_text: str
    exact_rendered_hash: str
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 7 * 86400)
    is_invalidated: bool = False
    invalidation_reason: Optional[str] = None
    record_schema_version: int
    source: str = "SCRIBE_GENERATION"


class ProvenanceStore:
    """
    Thread-safe server-authoritative store for canonical claim provenance records.
    Persists records to disk with atomic file replace transactions to survive application
    restarts and prevent forged, detached, or orphaned claim IDs.
    """
    def __init__(self, storage_path: Optional[Union[str, Path]] = None):
        if storage_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.storage_path = data_dir / "provenance_records.json"
            self.state_path = data_dir / "provenance_store_state.json"
        else:
            self.storage_path = Path(storage_path)
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            if self.storage_path.name == "provenance_records.json":
                self.state_path = self.storage_path.parent / "provenance_store_state.json"
            else:
                self.state_path = self.storage_path.parent / f"{self.storage_path.stem}_state.json"
        self._lock = threading.RLock()
        self._records: Dict[str, ProvenanceRecord] = {}
        self._quarantined_draft_ids: Set[str] = set()
        self._is_available: bool = True
        self._load_error: Optional[str] = None
        self._unavailable_reason: Optional[str] = None
        self._invalidation_counter: int = 0
        self._load()

    def quarantine_draft(self, draft_id: Optional[str]):
        """Explicitly quarantines a draft ID, preventing future claim creation or verification."""
        with self._lock:
            if draft_id and isinstance(draft_id, str):
                did_clean = draft_id.strip()
                if did_clean:
                    self._quarantined_draft_ids.add(did_clean)
                    self._invalidation_counter += 1

    def is_draft_quarantined(self, draft_id: Optional[str]) -> bool:
        """Returns True if the draft ID has been quarantined."""
        with self._lock:
            if not draft_id or not isinstance(draft_id, str):
                return False
            return draft_id.strip() in self._quarantined_draft_ids


    def _fsync_parent_dir(self, path: Path):
        """
        Fsyncs the parent directory of a path on POSIX platforms.
        Fails closed on real I/O errors while ignoring unsupported filesystem errors.
        """
        if not hasattr(os, "O_RDONLY") or not hasattr(os, "fsync"):
            return
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, IOError) as err:
            import errno
            unsupported_errnos = {
                getattr(errno, "EINVAL", 22),
                getattr(errno, "ENOTSUP", 45),
                getattr(errno, "EOPNOTSUPP", 45),
            }
            if getattr(err, "errno", None) in unsupported_errnos:
                logger.debug(f"Parent directory fsync unsupported on this filesystem for {path.parent}: {err}")
                return
            logger.critical(f"FATAL: Supported parent directory fsync failed for {path.parent}: {err}")
            raise

    def disable_store(self, reason: Optional[str] = None, affected_draft_id: Optional[str] = None) -> bool:
        """
        Catastrophic kill-switch: sets in-memory availability to False and persists
        the disabled state marker durably to disk using an atomic replace pattern.
        """
        with self._lock:
            self._is_available = False
            reason_str = str(reason).strip() if reason else "Catastrophic error: provenance store disabled"
            self._unavailable_reason = f"DURABLY_DISABLED: {reason_str}"
            self._records = {}  # In-memory records flushed immediately

            if affected_draft_id:
                self._quarantined_draft_ids.add(str(affected_draft_id).strip())

            state_data = {
                "schema_version": 1,
                "state": "DISABLED",
                "reason": reason_str,
                "affected_draft_id": str(affected_draft_id).strip() if affected_draft_id else None,
                "disabled_at": time.time(),
                "recovery_required": True
            }

            temp_path = self.state_path.parent / f".tmp_{uuid.uuid4().hex}_{self.state_path.name}"
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(temp_path, self.state_path)
                self._fsync_parent_dir(self.state_path)

                if not self.state_path.exists():
                    raise RuntimeError("State marker file missing after atomic write")

                logger.critical(f"Provenance store durably disabled fail-closed: {reason_str}")
                return True
            except Exception as e:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                logger.critical(f"FATAL: Failed to persist durable store disable marker: {e}")
                raise RuntimeError(f"STORE_DISABLE_PERSISTENCE_FAILURE: {e}") from e

    def is_available(self) -> bool:
        """Returns True if the provenance store is active and operational."""
        with self._lock:
            return self._is_available

    def recover_store(
        self,
        strategy: RecoveryStrategy,
        recovery_context: AdministrativeRecoveryContext
    ) -> bool:
        """
        Explicit administrative recovery operation.
        Strictly requires RecoveryStrategy.RESET_ALL_PROVENANCE and a validated AdministrativeRecoveryContext.
        """
        with self._lock:
            # 1. Validate Strategy: Strict Enum Instance Enforcement (No raw strings, aliases, or defaults)
            if not isinstance(strategy, RecoveryStrategy) or strategy is not RecoveryStrategy.RESET_ALL_PROVENANCE:
                raise ValueError(f"Unsupported recovery strategy: '{strategy}'. Only RecoveryStrategy.RESET_ALL_PROVENANCE is permitted.")

            # 2. Validate Administrative Context Type
            if not isinstance(recovery_context, AdministrativeRecoveryContext):
                raise RecoveryAuthorizationError("recovery_context must be an AdministrativeRecoveryContext instance.")

            # 3. Validate Actor Identity
            if not recovery_context.actor or not isinstance(recovery_context.actor, str) or not recovery_context.actor.strip():
                raise RecoveryAuthorizationError("Administrative recovery requires a non-empty actor identity.")

            # 4. Validate Execution Context: Strict Enum Instance Enforcement (No raw strings)
            if not isinstance(recovery_context.execution_context, RecoveryExecutionContext) or recovery_context.execution_context is not RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE:
                raise RecoveryAuthorizationError(
                    f"Forbidden recovery execution context: '{recovery_context.execution_context}'. "
                    "Only RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE is authorized."
                )

            # 5. Validate Explicit Confirmation
            if recovery_context.explicitly_confirmed is not True or type(recovery_context.explicitly_confirmed) is not bool:
                raise RecoveryAuthorizationError("Administrative recovery requires explicitly_confirmed=True.")

            # 6. Validate Dedicated Administrative Recovery Token Authority (Single-Use, Purpose-Bound)
            from backend.auth import verify_and_consume_recovery_token
            if not verify_and_consume_recovery_token(recovery_context.authorization_evidence, recovery_context.actor):
                raise RecoveryAuthorizationError("Invalid, expired, or already consumed administrative recovery authorization evidence.")

            # 7. Validate Store Precondition: Recovery cannot be executed on a healthy, available store
            if self._is_available and not self.state_path.exists():
                raise RecoveryAuthorizationError(
                    "Store is currently healthy and available. "
                    "Recovery precondition failed: recovery is only permitted when the store is durably disabled or in an invalid state."
                )

            # 8. Execute Destructive RESET_ALL_PROVENANCE with full durability and fail-closed marker restoration
            temp_store_path = self.storage_path.parent / f".tmp_{uuid.uuid4().hex}_{self.storage_path.name}"
            try:
                # Step A: Durably write empty dictionary to temporary claim store
                with open(temp_store_path, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_store_path, self.storage_path)
                self._fsync_parent_dir(self.storage_path)

                # Step B: Reopen and verify stored value is exactly {}
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                    if parsed != {}:
                        raise RuntimeError("Failed to verify empty store after reset write")

                # Step C: Remove disabled state marker
                if self.state_path.exists():
                    os.remove(self.state_path)
                self._fsync_parent_dir(self.state_path)

                # Step D: Verify marker is absent
                if self.state_path.exists():
                    raise RuntimeError("Failed to remove disabled state marker")

                # Step E: Complete reload and revalidation of disk state
                self._load()
                if not self._is_available or len(self._records) != 0 or len(self._quarantined_draft_ids) != 0:
                    raise RuntimeError("Post-recovery reload verification failed: store is not clean and available.")

                self._invalidation_counter += 1
                logger.info(f"Provenance store successfully recovered via RESET_ALL_PROVENANCE by actor '{recovery_context.actor}'.")
                return True
            except Exception as e:
                # If failure occurs after marker removal (or during reload), restore disabled marker fail-closed
                if not self.state_path.exists():
                    try:
                        self.disable_store(f"Post-recovery failure: {e}")
                    except Exception as marker_err:
                        logger.critical(f"FATAL: Failed to recreate disabled state marker after recovery failure: {marker_err}")
                self._is_available = False
                self._unavailable_reason = f"Recovery failed: {e}"
                logger.critical(f"FATAL: Store recovery failed: {e}")
                raise RuntimeError(f"Administrative recovery failed: {e}") from e

    def enable_store(self):
        """Removed for security. Generic enable shortcuts are forbidden."""
        raise RuntimeError("enable_store() is removed for safety. Use recover_store(strategy, recovery_context).")

    def reset_store(self):
        """Removed for security. Generic reset shortcuts are forbidden."""
        raise RuntimeError("reset_store() is removed for safety. Use recover_store(strategy, recovery_context).")

    def get_invalidation_count(self) -> int:
        """Returns the monotonic invalidation counter."""
        with self._lock:
            return self._invalidation_counter

    def _load(self):
        with self._lock:
            # Step 1: Check separate durable state marker file first
            if self.state_path.exists():
                try:
                    with open(self.state_path, "r", encoding="utf-8") as f:
                        state_data = json.load(f)

                    # Strict schema validation
                    if not isinstance(state_data, dict):
                        raise ValueError("State marker root must be a JSON object")

                    allowed_keys = {"schema_version", "state", "reason", "affected_draft_id", "disabled_at", "recovery_required"}
                    if not set(state_data.keys()).issubset(allowed_keys):
                        raise ValueError("State marker contains unrecognized fields")

                    if "schema_version" not in state_data or type(state_data["schema_version"]) is not int or isinstance(state_data["schema_version"], bool) or state_data["schema_version"] != 1:
                        raise ValueError(f"State marker schema_version invalid or unsupported: {state_data.get('schema_version')}")

                    if "state" not in state_data or state_data.get("state") != "DISABLED":
                        raise ValueError(f"State marker state invalid: '{state_data.get('state')}'. Only 'DISABLED' is permitted.")

                    reason_val = state_data.get("reason")
                    if not isinstance(reason_val, str) or not reason_val.strip():
                        raise ValueError("State marker reason must be a non-empty string")

                    if "affected_draft_id" not in state_data:
                        raise ValueError("State marker missing affected_draft_id field")
                    aff_did = state_data.get("affected_draft_id")
                    if aff_did is not None and (not isinstance(aff_did, str) or not aff_did.strip()):
                        raise ValueError("State marker affected_draft_id must be a non-empty string or null")

                    if "disabled_at" not in state_data:
                        raise ValueError("State marker missing disabled_at")
                    d_at = state_data.get("disabled_at")
                    if not isinstance(d_at, (int, float)) or isinstance(d_at, bool) or not math.isfinite(d_at) or d_at <= 0:
                        raise ValueError(f"State marker disabled_at invalid: {d_at}")

                    if "recovery_required" not in state_data or state_data.get("recovery_required") is not True or not isinstance(state_data.get("recovery_required"), bool):
                        raise ValueError(f"State marker recovery_required must be Boolean true: {state_data.get('recovery_required')}")

                    # Valid DISABLED state marker: set store unavailable
                    self._is_available = False
                    self._unavailable_reason = f"DURABLY_DISABLED: {reason_val.strip()}"
                    self._load_error = None
                    self._quarantined_draft_ids.clear()
                    if aff_did:
                        self._quarantined_draft_ids.add(aff_did.strip())
                    logger.critical(f"Provenance store is DURABLY_DISABLED per state marker at {self.state_path}. Claims will not be loaded or exposed.")
                    return
                except Exception as e:
                    logger.critical(f"Provenance store state file at {self.state_path} is invalid/unreadable: {e}. Starting unavailable fail-closed.")
                    self._is_available = False
                    self._load_error = str(e)
                    self._unavailable_reason = f"STATE_FILE_INVALID: {e}"
                    return

            # Step 2: If state permits (no disabled state marker), load claim records
            self._records = {}
            self._quarantined_draft_ids = set()
            if self.storage_path.exists():
                try:
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if not isinstance(data, dict):
                            raise ValueError("Corrupt provenance store: root must be a JSON dictionary")
                        for cid, item in data.items():
                            if not isinstance(item, dict):
                                raise ValueError(f"Corrupt record for claim '{cid}': expected dict")
                            mandatory_keys = [
                                "claim_instance_id", "draft_id", "canonical_fact_id",
                                "template_id", "template_version", "template_digest",
                                "ledger_version", "ledger_digest", "fact_version",
                                "fact_digest", "exact_rendered_text", "exact_rendered_hash",
                                "record_schema_version"
                            ]
                            for mk in mandatory_keys:
                                if mk not in item or item[mk] is None or (isinstance(item[mk], str) and not item[mk].strip()):
                                    raise ValueError(f"Provenance record '{cid}' is missing mandatory security field '{mk}'")
                            self._records[cid] = ProvenanceRecord(**item)
                    self._is_available = True
                    self._load_error = None
                    self._unavailable_reason = None
                except Exception as e:
                    logger.error(f"Failed to load provenance records from {self.storage_path}: {e}")
                    self._is_available = False
                    self._load_error = str(e)
                    self._unavailable_reason = f"Startup load error: {e}"
            else:
                self._is_available = True
                self._load_error = None
                self._unavailable_reason = None

    def _persist_to_disk(self, candidate_records: Dict[str, ProvenanceRecord]):
        """
        Transactional atomic file replace pattern:
        serialize -> write temporary file in same directory -> flush -> fsync temp file
        -> atomic replace -> fsync parent directory where supported.
        """
        if not self._is_available:
            raise RuntimeError(f"Provenance store is unavailable: {self._unavailable_reason or self._load_error or 'Store disabled fail-closed'}")

        data = {cid: rec.model_dump() for cid, rec in candidate_records.items()}
        temp_path = self.storage_path.parent / f".tmp_{uuid.uuid4().hex}_{self.storage_path.name}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_path, self.storage_path)

            try:
                dir_fd = os.open(str(self.storage_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                pass
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Atomic persistence of provenance store failed: {e}") from e

    def create_claim_instance(
        self,
        fact_id: str,
        template_id: str,
        draft_id: str,
        custom_params: Optional[Dict[str, Any]] = None
    ) -> ProvenanceRecord:
        with self._lock:
            if not self._is_available:
                raise RuntimeError(f"Provenance store is unavailable: {self._unavailable_reason or self._load_error or 'Store disabled fail-closed'}")

            if not draft_id or not isinstance(draft_id, str) or not draft_id.strip():
                raise ValueError("draft_id is mandatory and must be a non-empty string for claim instance generation")
            draft_id_clean = draft_id.strip()

            if self.is_draft_quarantined(draft_id_clean):
                raise ValueError(f"Draft '{draft_id_clean}' is quarantined due to a prior invalidation persistence failure")

            if template_id not in CANONICAL_CLAIM_TEMPLATES:
                raise ValueError(f"Unknown template_id '{template_id}'")
            tpl = CANONICAL_CLAIM_TEMPLATES[template_id]
            if tpl.fact_id != fact_id:
                raise ValueError(f"Template '{template_id}' is incompatible with fact '{fact_id}' (expected {tpl.fact_id})")

            emp_rec_id = tpl.employment_record_id
            if not emp_rec_id and fact_id.startswith("FACT_EMPLOYMENT_"):
                if fact_id == "FACT_EMPLOYMENT_IBM_WATSON":
                    emp_rec_id = "ibm"
                else:
                    emp_key = fact_id.replace("FACT_EMPLOYMENT_", "").lower()
                    if emp_key in CANONICAL_EMPLOYMENT_RECORDS:
                        emp_rec_id = emp_key

            fact_digest = get_active_fact_digest(fact_id)
            emp_digest = get_active_employment_record_digest(emp_rec_id) if emp_rec_id else None
            tpl_digest = get_active_template_digest(template_id)
            ledger_digest = get_active_ledger_digest()

            claim_id = f"claim_inst_{uuid.uuid4().hex}"
            record = ProvenanceRecord(
                claim_instance_id=claim_id,
                draft_id=draft_id_clean,
                canonical_fact_id=fact_id,
                employment_record_id=emp_rec_id,
                template_id=template_id,
                template_version=tpl.template_version,
                template_digest=tpl_digest,
                ledger_version=CANONICAL_LEDGER_SCHEMA_VERSION,
                ledger_digest=ledger_digest,
                fact_version="1.0.0",
                fact_digest=fact_digest,
                employment_record_digest=emp_digest,
                rendering_parameters=custom_params or {},
                exact_rendered_text=tpl.rendered_text,
                exact_rendered_hash=compute_sha256(tpl.rendered_text),
                created_at=time.time(),
                expires_at=time.time() + 7 * 86400,
                is_invalidated=False,
                record_schema_version=RECORD_SCHEMA_VERSION,
                source="SCRIBE_GENERATION"
            )

            # Transactional persistence before updating in-memory state
            candidate = dict(self._records)
            candidate[claim_id] = record
            self._persist_to_disk(candidate)
            self._records[claim_id] = record
            return record

    def get_claim_instance(self, claim_instance_id: str) -> Optional[ProvenanceRecord]:
        with self._lock:
            if not self._is_available:
                return None
            rec = self._records.get(claim_instance_id)
            if not rec:
                return None
            if rec.draft_id in self._quarantined_draft_ids:
                return rec.model_copy(update={
                    "is_invalidated": True,
                    "invalidation_reason": "Draft quarantined due to invalidation persistence failure"
                })
            return rec

    def invalidate_claim_instance(self, claim_instance_id: str, reason: str = "Manual edit detected") -> bool:
        with self._lock:
            rec = self._records.get(claim_instance_id)
            if not rec:
                return False
            updated_rec = rec.model_copy(update={"is_invalidated": True, "invalidation_reason": reason})
            candidate = dict(self._records)
            candidate[claim_instance_id] = updated_rec
            try:
                self._persist_to_disk(candidate)
                self._records[claim_instance_id] = updated_rec
                self._invalidation_counter += 1
                return True
            except Exception as e:
                target_did = rec.draft_id or claim_instance_id
                if rec.draft_id:
                    self._quarantined_draft_ids.add(rec.draft_id)
                self._invalidation_counter += 1
                logger.error(f"Persistence failure during claim invalidation for {claim_instance_id}. Quarantined draft: {e}")
                raise InvalidationPersistenceError(target_did, f"Persistence failure during claim invalidation for {claim_instance_id}: {e}") from e

    def invalidate_draft_claims(self, draft_id: str, reason: str = "Draft edited") -> int:
        with self._lock:
            if not draft_id:
                return 0
            did_clean = draft_id.strip() if isinstance(draft_id, str) else str(draft_id)
            if not self._is_available:
                self._quarantined_draft_ids.add(did_clean)
                self._invalidation_counter += 1
                raise InvalidationPersistenceError(did_clean, f"Provenance store is unavailable; quarantined draft '{did_clean}'")
            count = 0
            candidate = dict(self._records)
            for cid, rec in self._records.items():
                if rec.draft_id == did_clean and not rec.is_invalidated:
                    candidate[cid] = rec.model_copy(update={"is_invalidated": True, "invalidation_reason": reason})
                    count += 1
            if count > 0:
                try:
                    self._persist_to_disk(candidate)
                    self._records = candidate
                    self._invalidation_counter += 1
                except Exception as e:
                    self._quarantined_draft_ids.add(did_clean)
                    self._invalidation_counter += 1
                    logger.error(f"Persistence failure during draft invalidation for {did_clean}. Quarantined draft authority: {e}")
                    raise InvalidationPersistenceError(did_clean, f"Persistence failure during draft invalidation for {did_clean}: {e}") from e
            return count



# Global Singleton Provenance Store
PROVENANCE_STORE = ProvenanceStore()


def canonicalize_binding_manifest(bindings: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    Projects a list of claim bindings (dicts or ClaimBlockBinding instances)
    to a canonical list of 6-field dictionaries in exact order:
    - claim_instance_id
    - draft_id
    - block_id
    - start_offset
    - end_offset
    - submitted_block_text
    Returns None if bindings is None, not a list, or if any element is malformed / invalid.
    """
    if bindings is None or not isinstance(bindings, list):
        return None
    canonical_list = []
    for b in bindings:
        if isinstance(b, ClaimBlockBinding):
            cid = b.claim_instance_id
            did = b.draft_id
            bid = b.block_id
            so = b.start_offset
            eo = b.end_offset
            sbt = b.submitted_block_text
        elif isinstance(b, dict):
            # Explicitly reject legacy aliases
            if any(k in b for k in ("claim_id", "start", "end", "text", "rendered_text")):
                return None
            cid = b.get("claim_instance_id")
            did = b.get("draft_id")
            bid = b.get("block_id")
            so = b.get("start_offset")
            eo = b.get("end_offset")
            sbt = b.get("submitted_block_text")
        else:
            return None

        if not cid or not isinstance(cid, str) or not cid.strip():
            return None
        if not did or not isinstance(did, str) or not did.strip():
            return None
        if not bid or not isinstance(bid, str) or not bid.strip():
            return None
        if not sbt or not isinstance(sbt, str) or not sbt.strip():
            return None
        if so is None or type(so) is not int or isinstance(so, bool) or so < 0:
            return None
        if eo is None or type(eo) is not int or isinstance(eo, bool) or eo <= so:
            return None

        canonical_list.append({
            "claim_instance_id": cid.strip(),
            "draft_id": did.strip(),
            "block_id": bid.strip(),
            "start_offset": so,
            "end_offset": eo,
            "submitted_block_text": sbt
        })
    return canonical_list


def compute_manifest_digest(bindings: Optional[List[Any]]) -> str:
    """
    Computes a deterministic SHA-256 digest over the canonical 6-field binding manifest.
    """
    canonical = canonicalize_binding_manifest(bindings)
    if canonical is None:
        return ""
    serialized = json.dumps(canonical, sort_keys=True)
    return compute_sha256(serialized)


@dataclass(frozen=True)
class RiskEvaluationSnapshot:
    """
    Immutable server-side snapshot of draft identity and grounding authority
    captured prior to asynchronous or potentially slow risk evaluation.
    Every field defined here represents authoritative state and is strictly
    enforced during post-evaluation revalidation.

    NOTE ON created_at:
    The created_at field is non-authoritative observational diagnostic metadata
    recording the snapshot capture timestamp. It is excluded from authoritative
    equality enforcement. The 15 authoritative dimensions enforced are:
    email_id, draft_id, draft_text, computed_draft_text_hash, cached_draft_text_hash,
    canonical_manifest, manifest_digest, is_grounded, grounding_status, draft_version,
    invalidation_count, is_quarantined, store_available, ledger_version, ledger_digest.
    """
    email_id: str
    draft_id: str
    draft_text: str
    computed_draft_text_hash: str
    cached_draft_text_hash: str
    canonical_manifest: Tuple[Dict[str, Any], ...]
    manifest_digest: str
    is_grounded: bool
    grounding_status: str
    draft_version: int
    invalidation_count: int
    is_quarantined: bool
    store_available: bool
    ledger_version: str
    ledger_digest: str
    created_at: float = field(default_factory=time.time)


def capture_risk_evaluation_snapshot(email_id: str, email_msg: Any) -> Optional[RiskEvaluationSnapshot]:
    """
    Captures an immutable snapshot of server-cached draft state prior to risk evaluation.
    Fails closed (returns None) if any authoritative field is missing, invalid, or divergent.
    """
    if not email_id or not isinstance(email_id, str) or not email_id.strip():
        return None
    if not email_msg or not hasattr(email_msg, "id") or email_msg.id != email_id:
        return None
    if not email_msg.draft_id or not isinstance(email_msg.draft_id, str) or not email_msg.draft_id.strip():
        return None

    draft_text = email_msg.draft_reply
    if draft_text is None or not isinstance(draft_text, str):
        return None

    if not email_msg.draft_text_hash or not isinstance(email_msg.draft_text_hash, str) or not email_msg.draft_text_hash.strip():
        return None

    # Independent computation and cross-verification of draft text hash
    computed_hash = compute_sha256(draft_text)
    if not computed_hash or email_msg.draft_text_hash != computed_hash:
        return None

    # Validate canonical manifest
    canonical_manifest = canonicalize_binding_manifest(email_msg.claim_bindings)
    if email_msg.is_grounded and canonical_manifest is None:
        return None
    if canonical_manifest is None:
        canonical_manifest = []

    manifest_digest = compute_manifest_digest(canonical_manifest)
    if not is_valid_sha256(manifest_digest) and len(canonical_manifest) > 0:
        return None

    # Check store and quarantine state
    if not PROVENANCE_STORE.is_available():
        return None
    if PROVENANCE_STORE.is_draft_quarantined(email_msg.draft_id):
        return None
    if getattr(email_msg, "invalidation_issued", False):
        return None

    ledger_version = CANONICAL_LEDGER_SCHEMA_VERSION
    ledger_digest = get_active_ledger_digest()
    if not ledger_version or not ledger_digest or not is_valid_sha256(ledger_digest):
        return None

    return RiskEvaluationSnapshot(
        email_id=email_id.strip(),
        draft_id=email_msg.draft_id.strip(),
        draft_text=draft_text,
        computed_draft_text_hash=computed_hash,
        cached_draft_text_hash=email_msg.draft_text_hash.strip(),
        canonical_manifest=tuple(canonical_manifest),
        manifest_digest=manifest_digest,
        is_grounded=bool(email_msg.is_grounded),
        grounding_status=str(email_msg.grounding_status or GroundingStatus.UNVERIFIED.value),
        draft_version=getattr(email_msg, "draft_version", 0),
        invalidation_count=PROVENANCE_STORE.get_invalidation_count(),
        is_quarantined=False,
        store_available=True,
        ledger_version=ledger_version,
        ledger_digest=ledger_digest
    )


def verify_risk_evaluation_snapshot(snapshot: RiskEvaluationSnapshot, email_msg: Any) -> Tuple[bool, str]:
    """
    Atomically re-validates every field of a pre-evaluation snapshot against current live state.
    Returns (is_valid, reason).
    """
    if not email_msg:
        return False, "Addressed email message was removed from cache."

    if getattr(email_msg, "id", None) != snapshot.email_id:
        return False, f"Email message ID changed: expected '{snapshot.email_id}', currently '{getattr(email_msg, 'id', None)}'."

    if not PROVENANCE_STORE.is_available():
        return False, "Provenance store became unavailable during risk evaluation."

    if PROVENANCE_STORE.is_draft_quarantined(snapshot.draft_id):
        return False, f"Draft '{snapshot.draft_id}' was quarantined during risk evaluation."

    if email_msg.draft_id != snapshot.draft_id:
        return False, f"Draft ID changed: expected '{snapshot.draft_id}', currently '{email_msg.draft_id}'."

    if getattr(email_msg, "draft_version", 0) != snapshot.draft_version:
        return False, f"Draft version changed from {snapshot.draft_version} to {getattr(email_msg, 'draft_version', 0)}."

    # Exact draft text verification
    current_draft_text = email_msg.draft_reply
    if current_draft_text is None or not isinstance(current_draft_text, str):
        return False, "Current draft text is missing or invalid."

    if current_draft_text != snapshot.draft_text:
        return False, "Draft text content changed during risk evaluation."

    # Independent recomputation of draft text hash
    computed_current_hash = compute_sha256(current_draft_text)
    if computed_current_hash != snapshot.computed_draft_text_hash:
        return False, f"Recomputed draft text hash mismatch: expected '{snapshot.computed_draft_text_hash}', computed '{computed_current_hash}'."

    if email_msg.draft_text_hash != snapshot.cached_draft_text_hash:
        return False, f"Cached draft text hash mismatch: expected '{snapshot.cached_draft_text_hash}', currently '{email_msg.draft_text_hash}'."

    if email_msg.draft_text_hash != computed_current_hash:
        return False, f"Cached draft text hash does not match recomputed draft text hash: '{email_msg.draft_text_hash}' vs '{computed_current_hash}'."

    # Canonical manifest verification
    current_canonical = canonicalize_binding_manifest(email_msg.claim_bindings)
    if current_canonical is None:
        current_canonical = []
    if tuple(current_canonical) != snapshot.canonical_manifest:
        return False, "Canonical claim manifest bindings changed during evaluation."

    current_manifest_digest = compute_manifest_digest(current_canonical)
    if current_manifest_digest != snapshot.manifest_digest:
        return False, "Canonical claim manifest digest changed during evaluation."

    # Grounding boolean and status verification
    if bool(email_msg.is_grounded) != snapshot.is_grounded:
        return False, f"Grounding boolean changed: expected {snapshot.is_grounded}, currently {email_msg.is_grounded}."

    current_grounding_status = str(email_msg.grounding_status or GroundingStatus.UNVERIFIED.value)
    if current_grounding_status != snapshot.grounding_status:
        return False, f"Grounding status changed: expected '{snapshot.grounding_status}', currently '{current_grounding_status}'."

    # Invalidation state verification
    if getattr(email_msg, "invalidation_issued", False):
        return False, "Draft invalidation was issued during evaluation."

    if PROVENANCE_STORE.get_invalidation_count() != snapshot.invalidation_count:
        return False, "Provenance store invalidation count changed during evaluation."

    # Canonical ledger version and digest verification
    if CANONICAL_LEDGER_SCHEMA_VERSION != snapshot.ledger_version:
        return False, f"Canonical ledger version changed: expected '{snapshot.ledger_version}', currently '{CANONICAL_LEDGER_SCHEMA_VERSION}'."

    current_ledger_digest = get_active_ledger_digest()
    if current_ledger_digest != snapshot.ledger_digest:
        return False, f"Canonical ledger digest changed: expected '{snapshot.ledger_digest}', currently '{current_ledger_digest}'."

    return True, "Snapshot verified and unchanged."



def generate_canonical_claim(
    fact_id: str,
    template_id: Optional[str] = None,
    style_variant: Optional[str] = None,
    draft_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Authoritative backend claim generator.
    Requires a non-empty draft_id. Loads active canonical fact and compatible template,
    renders deterministic text, creates and persists a server-side ProvenanceRecord,
    and returns opaque instance metadata.
    """
    if not fact_id:
        raise ValueError("canonical_fact_id is required")
    if not draft_id or not isinstance(draft_id, str) or not draft_id.strip():
        raise ValueError("draft_id is mandatory and must be a non-empty string for claim instance generation")

    # Find matching template
    if template_id:
        if template_id not in CANONICAL_CLAIM_TEMPLATES:
            raise ValueError(f"Unknown template_id: '{template_id}'")
        tpl = CANONICAL_CLAIM_TEMPLATES[template_id]
        if tpl.fact_id != fact_id:
            raise ValueError(f"Template '{template_id}' is for fact '{tpl.fact_id}', not '{fact_id}'")
    else:
        target_style = style_variant or "concise"
        matching = [
            t for t in CANONICAL_CLAIM_TEMPLATES.values()
            if t.fact_id == fact_id and (t.style_variant == target_style or target_style is None)
        ]
        if not matching:
            matching = [t for t in CANONICAL_CLAIM_TEMPLATES.values() if t.fact_id == fact_id]
        if not matching:
            raise ValueError(f"No approved templates registered for fact '{fact_id}'")
        tpl = matching[0]

    rec = PROVENANCE_STORE.create_claim_instance(
        fact_id=fact_id,
        template_id=tpl.template_id,
        draft_id=draft_id.strip()
    )

    return {
        "claim_instance_id": rec.claim_instance_id,
        "draft_id": rec.draft_id,
        "canonical_fact_id": rec.canonical_fact_id,
        "employment_record_id": rec.employment_record_id,
        "template_id": rec.template_id,
        "template_version": rec.template_version,
        "rendered_text": rec.exact_rendered_text,
        "status": GroundingStatus.GROUNDED.value,
        "created_at": rec.created_at
    }


def validate_claim_manifest(
    draft_text: str,
    claim_bindings: List[Union[ClaimBlockBinding, Dict[str, Any]]],
    draft_id: Optional[str] = None
) -> Tuple[bool, GroundingStatus, str, List[ClaimBlockBinding]]:
    """
    Authoritative, fail-closed validation of the full claim manifest.
    Enforces that:
    1. Every binding contains all six canonical fields explicitly:
       claim_instance_id, draft_id, block_id, start_offset, end_offset, submitted_block_text
    2. No fallback aliases (claim_id, start, end, text, rendered_text) or synthesized defaults.
    3. Request-level draft_id is mandatory, non-empty, and matches every binding draft_id.
    4. Offsets are strictly non-boolean integers with 0 <= start_offset < end_offset <= len(draft_text).
    5. Exact draft text slice matches submitted_block_text.
    6. claim_instance_id and block_id are unique across the manifest.
    7. No overlapping or nested ranges.
    """
    if draft_text is None or not isinstance(draft_text, str):
        return False, GroundingStatus.VALIDATION_FAILED, "draft_text must be a valid string", []

    if not claim_bindings:
        return True, GroundingStatus.NO_CAREER_CLAIMS_DETECTED, "No claim bindings in manifest", []

    if not PROVENANCE_STORE.is_available():
        return False, GroundingStatus.VALIDATION_FAILED, f"Provenance store is unavailable: {PROVENANCE_STORE._unavailable_reason or PROVENANCE_STORE._load_error or 'Store disabled fail-closed'}", []

    if not draft_id or not isinstance(draft_id, str) or not draft_id.strip():
        return False, GroundingStatus.VALIDATION_FAILED, "Request draft_id is mandatory and must be a non-empty string", []

    request_draft_id = draft_id.strip()
    if PROVENANCE_STORE.is_draft_quarantined(request_draft_id):
        return False, GroundingStatus.VALIDATION_FAILED, f"Draft '{request_draft_id}' is quarantined due to prior invalidation persistence failure", []

    text_len = len(draft_text)

    parsed_bindings: List[ClaimBlockBinding] = []
    seen_claim_ids = set()
    seen_block_ids = set()
    ranges: List[Tuple[int, int, str]] = []

    for i, b in enumerate(claim_bindings):
        if isinstance(b, ClaimBlockBinding):
            cid = b.claim_instance_id
            did = b.draft_id
            bid = b.block_id
            start = b.start_offset
            end = b.end_offset
            block_text = b.submitted_block_text
        elif isinstance(b, dict):
            # Check mandatory canonical keys explicitly
            canonical_keys = [
                "claim_instance_id", "draft_id", "block_id",
                "start_offset", "end_offset", "submitted_block_text"
            ]
            for k in canonical_keys:
                if k not in b:
                    return False, GroundingStatus.VALIDATION_FAILED, f"Binding at index {i} missing mandatory canonical field '{k}'", []

            cid = b["claim_instance_id"]
            did = b["draft_id"]
            bid = b["block_id"]
            start = b["start_offset"]
            end = b["end_offset"]
            block_text = b["submitted_block_text"]
        else:
            return False, GroundingStatus.VALIDATION_FAILED, f"Binding at index {i} is not a valid ClaimBlockBinding or dict", []

        # Validate string fields: must be str, non-empty, and not whitespace-only
        if not isinstance(cid, str) or not cid.strip():
            return False, GroundingStatus.VALIDATION_FAILED, f"Binding at index {i} has invalid claim_instance_id", []
        if not isinstance(did, str) or not did.strip():
            return False, GroundingStatus.VALIDATION_FAILED, f"Binding '{cid}' has invalid draft_id", []
        if not isinstance(bid, str) or not bid.strip():
            return False, GroundingStatus.VALIDATION_FAILED, f"Binding '{cid}' has invalid block_id", []
        if not isinstance(block_text, str) or not block_text.strip():
            return False, GroundingStatus.VALIDATION_FAILED, f"Binding '{cid}' has invalid submitted_block_text", []

        # Validate draft_id consistency
        if did.strip() != request_draft_id:
            return False, GroundingStatus.VALIDATION_FAILED, f"Binding '{cid}' draft_id '{did}' does not match request draft_id '{request_draft_id}'", []

        # Validate offset types: strict non-boolean int
        if type(start) is not int or isinstance(start, bool) or type(end) is not int or isinstance(end, bool):
            return False, GroundingStatus.VALIDATION_FAILED, f"Offsets for claim '{cid}' must be non-boolean integers", []

        # Validate bounds
        if start < 0 or end > text_len or start >= end:
            return False, GroundingStatus.VALIDATION_FAILED, f"Offset range [{start}:{end}] for claim '{cid}' is invalid for draft length {text_len}", []

        # Exact draft slice comparison
        draft_slice = draft_text[start:end]
        if draft_slice != block_text:
            return False, GroundingStatus.VALIDATION_FAILED, f"Draft text slice at [{start}:{end}] ('{draft_slice}') does not match submitted block text ('{block_text}')", []

        # Duplicate ID checks
        if cid in seen_claim_ids:
            return False, GroundingStatus.VALIDATION_FAILED, f"Duplicate claim_instance_id '{cid}' in manifest", []
        seen_claim_ids.add(cid)

        if bid in seen_block_ids:
            return False, GroundingStatus.VALIDATION_FAILED, f"Duplicate block_id '{bid}' in manifest", []
        seen_block_ids.add(bid)

        ranges.append((start, end, cid))
        parsed_bindings.append(ClaimBlockBinding(
            claim_instance_id=cid.strip(),
            draft_id=did.strip(),
            block_id=bid.strip(),
            start_offset=start,
            end_offset=end,
            submitted_block_text=block_text
        ))

    # Overlap / nested check
    sorted_ranges = sorted(ranges, key=lambda x: (x[0], x[1]))
    for j in range(len(sorted_ranges) - 1):
        s1, e1, id1 = sorted_ranges[j]
        s2, e2, id2 = sorted_ranges[j + 1]
        if s2 < e1:
            return False, GroundingStatus.VALIDATION_FAILED, f"Overlapping or nested claim block ranges detected between '{id1}' [{s1}:{e1}] and '{id2}' [{s2}:{e2}]", []

    return True, GroundingStatus.GROUNDED, "Claim manifest is well-formed", parsed_bindings


def verify_provenance_claim_binding(
    binding: ClaimBlockBinding,
    draft_text: str
) -> Tuple[bool, ClaimStatus, str, Optional[SupportedClaim]]:
    """
    Authoritative verification of a bound claim block against server-side provenance,
    active versions/digests, and deterministic regeneration.
    Strictly fail-closed on any missing or mismatched evidence.
    """
    if not PROVENANCE_STORE.is_available():
        return False, ClaimStatus.VALIDATION_FAILED, f"Provenance store is unavailable: {PROVENANCE_STORE._unavailable_reason or PROVENANCE_STORE._load_error or 'Store disabled fail-closed'}", None

    if draft_text is None or not isinstance(draft_text, str):
        return False, ClaimStatus.VALIDATION_FAILED, "Draft text must be a valid string", None

    if PROVENANCE_STORE.is_draft_quarantined(binding.draft_id):
        return False, ClaimStatus.INVALIDATED, f"Draft '{binding.draft_id}' is quarantined due to prior invalidation persistence failure", None

    cid = binding.claim_instance_id
    rec = PROVENANCE_STORE.get_claim_instance(cid)
    if not rec:
        return False, ClaimStatus.UNVERIFIED, f"Claim instance '{cid}' not found in server-side provenance registry (untrusted or fabricated ID)", None

    if rec.is_invalidated:
        return False, ClaimStatus.INVALIDATED, f"Claim instance '{cid}' was invalidated ({rec.invalidation_reason})", None

    if rec.expires_at and time.time() > rec.expires_at:
        return False, ClaimStatus.STALE_PROVENANCE, f"Claim instance '{cid}' has expired", None

    # Draft ID validation
    if not rec.draft_id or not isinstance(rec.draft_id, str) or not rec.draft_id.strip():
        return False, ClaimStatus.STALE_PROVENANCE, f"Provenance record '{cid}' lacks draft identity (legacy or malformed record)", None

    if binding.draft_id != rec.draft_id:
        return False, ClaimStatus.UNVERIFIED, f"Claim instance '{cid}' is bound to draft '{rec.draft_id}', not '{binding.draft_id}'", None

    # Schema & Version validation
    if rec.record_schema_version != RECORD_SCHEMA_VERSION:
        return False, ClaimStatus.STALE_PROVENANCE, f"Unsupported record schema version '{rec.record_schema_version}' (expected {RECORD_SCHEMA_VERSION})", None

    if rec.ledger_version != CANONICAL_LEDGER_SCHEMA_VERSION:
        return False, ClaimStatus.STALE_PROVENANCE, f"Ledger version mismatch: record '{rec.ledger_version}' vs active '{CANONICAL_LEDGER_SCHEMA_VERSION}'", None

    if not is_valid_sha256(rec.ledger_digest):
        return False, ClaimStatus.STALE_PROVENANCE, "Malformed or missing ledger_digest in provenance record", None

    current_ledger_digest = get_active_ledger_digest()
    if rec.ledger_digest != current_ledger_digest:
        return False, ClaimStatus.STALE_PROVENANCE, "Canonical ledger digest mismatch: active ledger has changed since claim generation", None

    # Template validation
    if not rec.template_id or rec.template_id not in CANONICAL_CLAIM_TEMPLATES:
        return False, ClaimStatus.STALE_PROVENANCE, f"Template '{rec.template_id}' is no longer active in template registry", None

    tpl = CANONICAL_CLAIM_TEMPLATES[rec.template_id]
    if tpl.fact_id != rec.canonical_fact_id:
        return False, ClaimStatus.STALE_PROVENANCE, f"Provenance record fact/template mismatch: '{rec.canonical_fact_id}' vs '{tpl.fact_id}'", None

    if rec.template_version != tpl.template_version:
        return False, ClaimStatus.STALE_PROVENANCE, f"Template version mismatch: record '{rec.template_version}' vs active '{tpl.template_version}'", None

    if not is_valid_sha256(rec.template_digest):
        return False, ClaimStatus.STALE_PROVENANCE, "Malformed or missing template_digest in provenance record", None

    current_tpl_digest = get_active_template_digest(rec.template_id)
    if rec.template_digest != current_tpl_digest:
        return False, ClaimStatus.STALE_PROVENANCE, f"Template '{rec.template_id}' digest mismatch: active template modified since claim generation", None

    # Fact & Employment Record validation
    if rec.fact_version != "1.0.0":
        return False, ClaimStatus.STALE_PROVENANCE, f"Fact version mismatch: record '{rec.fact_version}' (expected '1.0.0')", None

    if not is_valid_sha256(rec.fact_digest):
        return False, ClaimStatus.STALE_PROVENANCE, "Malformed or missing fact_digest in provenance record", None

    fact_id = rec.canonical_fact_id
    if fact_id in CANONICAL_FACT_REGISTRY:
        fact = CANONICAL_FACT_REGISTRY[fact_id]
        category = fact.category
        canonical_ref = fact.canonical_text
        current_fact_digest = get_active_fact_digest(fact_id)
        if rec.fact_digest != current_fact_digest:
            return False, ClaimStatus.STALE_PROVENANCE, f"Canonical fact '{fact_id}' content has changed since claim generation", None
    elif fact_id.startswith("FACT_EMPLOYMENT_"):
        emp_key = "ibm" if fact_id == "FACT_EMPLOYMENT_IBM_WATSON" else fact_id.replace("FACT_EMPLOYMENT_", "").lower()
        if emp_key not in CANONICAL_EMPLOYMENT_RECORDS:
            return False, ClaimStatus.STALE_PROVENANCE, f"Employment record '{emp_key}' no longer active in employment ledger", None
        category = ClaimCategory.EMPLOYER
        emp_rec = CANONICAL_EMPLOYMENT_RECORDS[emp_key]
        canonical_ref = f"{emp_rec.employer_canonical} ({emp_rec.start_year}–{emp_rec.end_year or 'present'})"
        current_fact_digest = get_active_fact_digest(fact_id)
        if rec.fact_digest != current_fact_digest:
            return False, ClaimStatus.STALE_PROVENANCE, f"Employment fact '{fact_id}' content has changed since claim generation", None
    else:
        return False, ClaimStatus.STALE_PROVENANCE, f"Canonical fact '{fact_id}' not found in active canonical registry", None

    # Employment record digest verification for employment-derived claims
    if rec.employment_record_id:
        if not is_valid_sha256(rec.employment_record_digest):
            return False, ClaimStatus.STALE_PROVENANCE, "Malformed or missing employment_record_digest in provenance record", None
        current_emp_digest = get_active_employment_record_digest(rec.employment_record_id)
        if rec.employment_record_digest != current_emp_digest:
            return False, ClaimStatus.STALE_PROVENANCE, f"Employment record '{rec.employment_record_id}' content has changed since claim generation", None

    # Exact deterministic regeneration and hash checks
    if not is_valid_sha256(rec.exact_rendered_hash):
        return False, ClaimStatus.STALE_PROVENANCE, "Malformed or missing exact_rendered_hash in provenance record", None

    expected_text = tpl.rendered_text
    if rec.exact_rendered_text != expected_text:
        return False, ClaimStatus.STALE_PROVENANCE, "Provenance record rendered text diverged from current template rendering", None

    if rec.exact_rendered_hash != compute_sha256(rec.exact_rendered_text):
        return False, ClaimStatus.STALE_PROVENANCE, "Provenance record hash mismatch with exact_rendered_text", None

    if rec.exact_rendered_hash != compute_sha256(expected_text):
        return False, ClaimStatus.STALE_PROVENANCE, "Provenance record hash mismatch with active template rendering", None

    if binding.submitted_block_text != expected_text:
        return False, ClaimStatus.UNVERIFIED, f"Submitted claim text diverged from deterministically regenerated canonical claim '{expected_text}' (edit detected)", None

    # Offset & Slice verification
    if not isinstance(binding.start_offset, int) or not isinstance(binding.end_offset, int) or isinstance(binding.start_offset, bool) or isinstance(binding.end_offset, bool):
        return False, ClaimStatus.VALIDATION_FAILED, "Binding offsets must be integers", None

    if binding.start_offset < 0 or binding.end_offset > len(draft_text) or binding.start_offset >= binding.end_offset:
        return False, ClaimStatus.VALIDATION_FAILED, f"Offset range [{binding.start_offset}:{binding.end_offset}] out of bounds for draft length {len(draft_text)}", None

    draft_slice = draft_text[binding.start_offset:binding.end_offset]
    if draft_slice != expected_text:
        return False, ClaimStatus.UNVERIFIED, f"Draft text at [{binding.start_offset}:{binding.end_offset}] does not match deterministically regenerated text", None

    supp = SupportedClaim(
        fact_id=fact_id,
        category=category,
        extracted_text=binding.submitted_block_text,
        canonical_reference=canonical_ref,
        confidence=1.0
    )
    return True, ClaimStatus.SUPPORTED, f"Authoritatively verified against canonical fact {fact_id} via template {tpl.template_id}", supp


def verify_provenance_claim(
    claim_instance_id: Optional[str] = None,
    submitted_text: Optional[str] = None,
    draft_id: Optional[str] = None,
    draft_text: Optional[str] = None,
    start_offset: Optional[int] = None,
    end_offset: Optional[int] = None,
    block_id: Optional[str] = None,
    *args,
    **kwargs
) -> Tuple[bool, ClaimStatus, str, Optional[SupportedClaim]]:
    """
    Authoritative verification compatibility wrapper for a provenance claim.
    Strictly requires all seven arguments explicitly:
    claim_instance_id, draft_id, block_id, draft_text, start_offset, end_offset, submitted_text.
    Delegates strictly to validate_claim_manifest and verify_provenance_claim_binding.
    Fails closed (VALIDATION_FAILED) if any parameter is missing, None, boolean, or malformed.
    """
    if args or kwargs:
        return False, ClaimStatus.VALIDATION_FAILED, "Unexpected extra arguments passed to verify_provenance_claim", None

    if not claim_instance_id or not isinstance(claim_instance_id, str) or not claim_instance_id.strip():
        return False, ClaimStatus.VALIDATION_FAILED, "Missing required binding context: Missing or malformed claim_instance_id (standalone verification disabled)", None

    if not draft_id or not isinstance(draft_id, str) or not draft_id.strip():
        return False, ClaimStatus.VALIDATION_FAILED, "Missing required binding context: Missing or malformed draft_id (standalone verification disabled)", None

    if not block_id or not isinstance(block_id, str) or not block_id.strip():
        return False, ClaimStatus.VALIDATION_FAILED, "Missing required binding context: Missing or malformed block_id (standalone verification disabled)", None

    if draft_text is None or not isinstance(draft_text, str):
        return False, ClaimStatus.VALIDATION_FAILED, "Missing required binding context: Missing or malformed draft_text (standalone verification disabled)", None

    if submitted_text is None or not isinstance(submitted_text, str) or not submitted_text.strip():
        return False, ClaimStatus.VALIDATION_FAILED, "Missing required binding context: Missing or malformed submitted_text (standalone verification disabled)", None

    if (
        start_offset is None or end_offset is None or
        type(start_offset) is not int or isinstance(start_offset, bool) or
        type(end_offset) is not int or isinstance(end_offset, bool)
    ):
        return False, ClaimStatus.VALIDATION_FAILED, "Missing required binding context: start_offset and end_offset must be non-boolean integers (standalone verification disabled)", None

    binding = {
        "claim_instance_id": claim_instance_id.strip(),
        "draft_id": draft_id.strip(),
        "block_id": block_id.strip(),
        "start_offset": start_offset,
        "end_offset": end_offset,
        "submitted_block_text": submitted_text
    }

    is_manifest_valid, m_status, m_reason, parsed_bindings = validate_claim_manifest(
        draft_text=draft_text,
        claim_bindings=[binding],
        draft_id=draft_id.strip()
    )
    if not is_manifest_valid or not parsed_bindings:
        return False, ClaimStatus.VALIDATION_FAILED, f"Manifest validation failed: {m_reason}", None

    return verify_provenance_claim_binding(parsed_bindings[0], draft_text)


def get_available_templates(fact_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns list of approved canonical claim templates."""
    results = []
    for t in CANONICAL_CLAIM_TEMPLATES.values():
        if fact_id is None or t.fact_id == fact_id:
            results.append({
                "template_id": t.template_id,
                "template_version": t.template_version,
                "fact_id": t.fact_id,
                "category": t.category.value,
                "style_variant": t.style_variant,
                "rendered_text": t.rendered_text,
                "description": t.description
            })
    return results

def normalize_title(title: str) -> str:
    """
    Deterministically normalizes a job title for exact canonical comparison.
    Standardizes:
    - lowercase
    - Unicode dashes (—, –, -) and slashes -> spaced
    - '&' vs 'and' -> standardized to '&'
    - punctuation stripped
    - excess whitespace collapsed and trimmed
    - leading articles ('a', 'an', 'the') and temporal adverbs ('currently', 'formerly', 'previously') stripped
    """
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r'[—–\-/]', ' ', t)
    t = re.sub(r'\band\b', '&', t)
    t = re.sub(r'[,.:;()\'"]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'^(?:currently|formerly|previously|now)\s+', '', t).strip()
    t = re.sub(r'^(?:a|an|the)\s+', '', t).strip()
    return t


def normalize_employer(name: str) -> str:
    """
    Deterministically normalizes an employer name for exact alias comparison.
    Standardizes:
    - lowercase
    - punctuation stripped
    - excess whitespace collapsed and trimmed
    """
    if not name:
        return ""
    n = name.lower().strip()
    n = re.sub(r'[,.:;\'"–—\-]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def get_normalized_titles_for_record(rec: CanonicalEmploymentRecord) -> Set[str]:
    """Returns the set of exact normalized held titles and approved display aliases for a record."""
    titles = set()
    for ht in rec.held_titles:
        titles.add(normalize_title(ht))
    for ada in rec.approved_display_aliases:
        titles.add(normalize_title(ada))
    return titles


# ---------------------------------------------------------------------------
# Polarity, Negation, Uncertainty, Hearsay & Disclaimer Detection (Section 5 & 10)
# ---------------------------------------------------------------------------

NEGATION_PATTERNS = [
    r'\b(?:did\s+not|didn[\'’]t|have\s+not|haven[\'’]t|was\s+not|wasn[\'’]t|is\s+not|isn[\'’]t|do\s+not|don[\'’]t|cannot|can[\'’]t|could\s+not|couldn[\'’]t|would\s+not|wouldn[\'’]t|will\s+not|won[\'’]t|should\s+not|shouldn[\'’]t|never|not)\s+(?:honestly\s+|really\s+|actually\s+)?(?:claim|state|say|believe|influence|influencing|influenced|close|closing|closed|deliver|delivering|delivered|achieve|achieving|achieved|lead|leading|led|manage|managing|managed|reduce|reducing|reduced|improve|improving|improved|generate|generating|generated|book|booking|booked|earn|earning|earned|work|working|worked|serve|serving|served)\b',
    r'\b(?:cannot|can[\'’]t|do\s+not|don[\'’]t|will\s+not|won[\'’]t|should\s+not|shouldn[\'’]t|would\s+not|wouldn[\'’]t)\s+(?:honestly\s+|really\s+|actually\s+)?(?:claim|say|state|believe)\b',
    r'\b(?:don[\'’]t|do\s+not)\s+believe\s+(?:i|that\s+i)?\b',
    r'\b(?:cannot|can[\'’]t)\s+(?:honestly\s+)?say\s+(?:i|that\s+i)?\b',
    r'\b(?:cannot|can[\'’]t)\s+claim\s+(?:that\s+i|i)?\b',
    r'\b(?:would\s+not|wouldn[\'’]t)\s+say\s+(?:i|that\s+i)?\b',
    r'\bno\s+longer\s+claim\b',
    r'\bnever\s+(?:achieved|influenced|closed|delivered|led|managed|reduced|improved|worked|served)\b'
]

UNCERTAINTY_AND_HEARSAY_PATTERNS = [
    r'\b(?:doubt|doubtful)\s+(?:that\s+i|i)\b',
    r'\b(?:may\s+have|might\s+have|could\s+have)\s+(?:influenced|achieved|delivered|closed|generated|led|managed|reduced|improved)\b',
    r'\b(?:allegedly|supposedly|reportedly)\b',
    r'\b(?:it\s+was\s+alleged\s+that|alleged\s+that)\b',
    r'\bsomeone\s+(?:claimed|stated|said|reported)\s+(?:that\s+i|i)?\b',
    r'\b(?:was\s+said|said)\s+to\s+have\s+(?:influenced|achieved|delivered|closed|generated|led|managed|reduced|improved)\b',
    r'\b(?:rumored\s+to\s+have|claimed\s+to\s+have)\b'
]

DISCLAIMER_PATTERNS = [
    r'\bfalsely\s+(?:claimed|stated|asserted|reported|said)\b',
    r'\binaccurate\s+to\s+say\b',
    r'\bincorrect\s+to\s+say\b',
    r'\buntrue\s+to\s+say\b',
    r'\bshould\s+not\s+say\b',
    r'\b(?:draft|r[ée]sum[ée]|resume|document)\s+(?:incorrectly|mistakenly|falsely|erroneously)\s+(?:says|states|claims|mentions)\b',
    r'\b(?:mistakenly|erroneously)\s+(?:states|claims|says|asserts)\b',
    r'\bdeny\s+that\b',
    r'\bdenies\s+that\b',
    r'\bdenied\s+that\b',
    r'\bdid\s+i\s+(?:really|actually)\b',
    r'\buntrue\s+that\b',
    r'\bnot\s+true\s+that\b',
    r'\bfabricated\s+that\b',
    r'\bit\s+is\s+a\s+mistake\s+to\s+say\b',
    r'\bit\s+is\s+false\s+that\b'
]


def check_negation_or_disclaimer(text: str) -> Tuple[bool, str]:
    """
    Detects negation, disclaimer, modal uncertainty, hearsay, questioning, or non-affirmative
    polarity context governing a claim. Returns (is_non_affirmative, matched_reason).
    """
    text_lower = text.lower()
    for pat in NEGATION_PATTERNS:
        m = re.search(pat, text_lower)
        if m:
            return True, f"negation ('{m.group(0)}')"
    for pat in UNCERTAINTY_AND_HEARSAY_PATTERNS:
        m = re.search(pat, text_lower)
        if m:
            return True, f"uncertainty/hearsay ('{m.group(0)}')"
    for pat in DISCLAIMER_PATTERNS:
        m = re.search(pat, text_lower)
        if m:
            return True, f"disclaimer ('{m.group(0)}')"
    return False, ""


# ---------------------------------------------------------------------------
# Text Extraction, Clause Segmentation & Organization Extraction Helpers
# ---------------------------------------------------------------------------

COMMON_NON_ORGS = {
    "the", "a", "an", "this", "that", "all", "our", "my", "your", "their", "many", "several",
    "various", "multiple", "both", "we", "i", "he", "she", "they", "scale", "shared", "least",
    "first", "most", "high", "enterprise", "concept", "production", "work", "time", "clients",
    "teams", "annual", "new", "cloud", "services", "solutions", "quarter", "year", "career",
    "total", "practice", "strategy", "architecture", "data", "ai", "gtm", "p&l", "poc",
    "time-to-value", "turnaround", "presales", "conversion", "sales", "cycles", "complexity",
    "legacy", "efficiency", "roadmap", "rate", "responsibilities", "responsibility", "deal",
    "pipeline", "role", "position", "opportunity", "opening", "background", "experience",
    "across", "during", "while", "before", "after", "throughout", "over", "revenue", "portfolio",
    "bookings", "outcome", "outcomes", "value", "growth", "in enterprise", "enterprise revenue",
    "poc-to-production", "scoping turnaround", "sales cycles", "legacy architecture",
    "time to value", "poc to production"
}


def parse_monetary_value(raw_val: str, unit: Optional[str] = None) -> float:
    """Safely parses monetary string into numeric float."""
    try:
        clean_num = float(raw_val.replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0

    unit_clean = (unit or "").lower().strip()
    if "m" in unit_clean or "million" in unit_clean:
        return clean_num * 1_000_000
    elif "b" in unit_clean or "billion" in unit_clean:
        return clean_num * 1_000_000_000
    elif "k" in unit_clean or "thousand" in unit_clean:
        return clean_num * 1_000
    return clean_num


def is_opportunity_or_target_role_reference(text: str, match_text: str = "") -> bool:
    """
    Distinguishes incoming opportunity or recipient references from affirmative first-person employment claims.
    E.g. 'I am interested in the role at Amazon' -> True (Opportunity reference)
    E.g. 'During my time at Amazon, I was CTO' -> False (Affirmative employment assertion)
    """
    s_lower = text.lower()

    # Affirmative past/current employment markers override opportunity language
    affirmative_employment_markers = [
        "when i was at", "during my time at", "during my tenure at", "during my years at",
        "during my time with", "during my tenure with", "during my years with",
        "my role at", "my position at", "my work as an employee at", "as an employee at",
        "i worked at", "i worked for", "i served at", "i was at", "i have been at",
        "i was with", "i have been with", "held a role", "held a role at", "holding the role of",
        "i was chief", "i was vp", "i was vice president", "i was head of", "i was director",
        "former ", "while working at", "while working for", "while employed by", "while employed at",
        "i generated", "i booked", "i closed", "i managed", "i earned", "i led engineering",
        "spent five years", "spent 5 years", "spent several years", "spent 3 years", "spent three years",
        "am employed by", "was employed by", "remain employed at", "still work for", "still work at",
        "i joined ", "hired me in", "my employer at the time", "my employer was", "formerly worked for",
        "before joining", "on my payroll", "on their payroll", "paycheck came from", "on apple's payroll",
        "on contoso's payroll", "on netflix's payroll", "on pythian's payroll", "on cdw's payroll"
    ]
    if any(m in s_lower for m in affirmative_employment_markers):
        return False

    # Target opportunity reference markers
    opportunity_markers = [
        "regarding the", "regarding your", "reaching out regarding", "thank you for reaching out",
        "interested in the", "excited about the", "discuss the", "discussing the",
        "opportunity at", "opening at", "position at", "role at", "goals at",
        "aligns with", "align with", "suit your schedule", "introductory conversation",
        "role aligns", "opportunity aligns", "position aligns", "forward to speaking",
        "is hiring for", "recruiter from"
    ]
    return any(m in s_lower for m in opportunity_markers)


def get_clause_and_sentence(text: str, start: int, end: int) -> Tuple[str, str]:
    """
    Returns (clause_text, sentence_text) around the given span [start, end].
    Sentence is delimited by '. ' or '.\n' or newline or end of string (ignoring decimal numbers).
    Clause isolates the immediate local proposition around [start, end], bounded by semicolons,
    conjunctions, newlines, or introductory opportunity phrases.
    """
    # Find sentence start
    sent_start = 0
    for m in re.finditer(r'(?:\.\s+|\n+)', text[:start]):
        sent_start = m.end()

    # Find sentence end
    sent_end = len(text)
    m = re.search(r'(?:\.\s+|\n+|\.$)', text[end:])
    if m:
        sent_end = end + m.start() + (1 if text[end + m.start()] == '.' else 0)

    sentence = text[sent_start:sent_end].strip()

    # Isolate proposition/clause within sentence
    c_start = sent_start
    c_end = sent_end

    # 1. Look for introductory opportunity clause before match (e.g. 'Regarding the role at CDW, ')
    intro_match = re.search(r'^(?:regarding\s+the\s+[a-z\s]+at\s+[A-Za-z0-9&.,\'-]+|in\s+response\s+to\s+[a-z\s]+at\s+[A-Za-z0-9&.,\'-]+|thank\s+you\s+for\s+reaching\s+out\s+regarding\s+[a-z\s]+at\s+[A-Za-z0-9&.,\'-]+)[,;]\s*', sentence, re.IGNORECASE)
    if intro_match and (sent_start + intro_match.end() <= start):
        c_start = max(c_start, sent_start + intro_match.end())

    # 2. General proposition delimiters
    clause_delims_left = [";", "\n", " and ", " including ", " while ", " whereas ", " although ", " but ", ", and ", ", but ", ", while ", "• ", " - ", "— "]
    for delim in clause_delims_left:
        pos = text.rfind(delim, c_start, start)
        if pos != -1:
            c_start = max(c_start, pos + len(delim))

    clause_delims_right = [";", "\n", " and ", " including ", " while ", " whereas ", " although ", " but ", ", and ", ", but ", ", while ", "• ", " - ", "— "]
    for delim in clause_delims_right:
        pos = text.find(delim, end, c_end)
        if pos != -1:
            c_end = min(c_end, pos)

    clause = text[c_start:c_end].strip()
    if not clause:
        clause = sentence
    return clause, sentence


def extract_governing_organizations(clause_text: str) -> List[str]:
    """
    Extracts all organization/scope entity mentions occupying an employer or attribution
    scope position within a local clause/proposition.
    Recognizes:
    - at / for / with / while at / during tenure at / on behalf of / for clients at / within / through / as part of <ORG>
    - <ORG>'s revenue / portfolio / pipeline / team / conversion / scoping
    - <ORG> revenue / portfolio / pipeline (noun modifier)
    - <ORG> achieved / delivered / closed / reduced / improved
    - revenue / pipeline / portfolio for / at / of <ORG>
    """
    orgs = []

    # Pattern 1: Prepositional scope relationships with lookahead boundary to prevent multi-org bleed
    p1 = re.compile(
        r'\b(?:at|for|with|while\s+at|during\s+my\s+tenure\s+at|during\s+my\s+time\s+(?:at|with)|on\s+behalf\s+of|for\s+clients\s+at|within|through|as\s+part\s+of|while\s+employed\s+(?:at|by|with))\s+([A-Za-z0-9&.\'-]+(?:\s+[A-Za-z0-9&.\'-]+){0,3}?)(?=[.,;:\n]|\s+(?:at|for|with|on\s+behalf\s+of|while|where|as|and|including|in\s+\d{4}|to|from|by|into|after|before)\b|$)',
        re.IGNORECASE
    )
    for m in p1.finditer(clause_text):
        raw_cand = m.group(1).strip()
        clean_cand = re.sub(r'[,.:;\'"]', '', raw_cand).strip()
        clean_lower = clean_cand.lower()
        if clean_lower not in COMMON_NON_ORGS and len(clean_lower) > 1 and len(clean_lower.split()) <= 4:
            if not any(stop in clean_lower for stop in ["the role", "the position", "the opportunity", "my career", "our career"]):
                orgs.append(clean_cand)

    # Pattern 2: Possessive organization attribution (e.g. Globex's revenue, Globex's 23% conversion rate, Stark Industries' pipeline)
    p2 = re.compile(
        r'\b([A-Z][A-Za-z0-9&.-]+(?:\s+[A-Z][A-Za-z0-9&.-]+){0,2})(?:[\'’]s|[\'’])\s+(?:\d+(?:\.\d+)?%?\s+|\$\s*\d+(?:\.\d+)?\s*[mMkKbB\+]*(?:\s+in)?\s+)?(?i:(?:annual\s+|new\s+|total\s+)?(?:revenue|portfolio|pipeline|team|services|clients|conversion|scoping|turnaround|sales\s+cycles|sales|cycles|poc|bookings|poc-to-production|customer\s+retention|deal|outcomes|outcome))\b'
    )
    for m in p2.finditer(clause_text):
        raw_cand = m.group(1).strip()
        clean_cand = re.sub(r'[,.:;\'"]', '', raw_cand).strip()
        clean_lower = clean_cand.lower()
        if clean_lower not in COMMON_NON_ORGS and len(clean_lower) > 1 and len(clean_lower.split()) <= 4:
            orgs.append(clean_cand)

    # Pattern 3: Proper noun subject agents (e.g. Contoso achieved a 40% reduction, Globex delivered ...)
    p3 = re.compile(r'\b([A-Z][A-Za-z0-9&.\'-]+(?:\s+[A-Z][A-Za-z0-9&.\'-]+)?)\s+(?:achieved|generated|delivered|closed|influenced|reduced|improved|converted|targeted)\b')
    for m in p3.finditer(clause_text):
        raw_cand = m.group(1).strip()
        clean_cand = re.sub(r'[,.:;\'"]', '', raw_cand).strip()
        clean_lower = clean_cand.lower()
        if clean_lower not in COMMON_NON_ORGS and len(clean_lower) > 1 and len(clean_lower.split()) <= 4:
            orgs.append(clean_cand)

    # Pattern 4: Noun modifiers modifying metrics (e.g. Globex revenue, Globex annual revenue, Globex pipeline)
    p4 = re.compile(
        r'\b([A-Z][A-Za-z0-9&.\'-]+(?:\s+[A-Z][A-Za-z0-9&.\'-]+)?)\s+(?:annual\s+|new\s+|total\s+)?(?:revenue|pipeline|portfolio|bookings|services|poc|conversion|turnaround|sales\s+cycles|customer\s+retention)\b'
    )
    for m in p4.finditer(clause_text):
        raw_cand = m.group(1).strip()
        clean_cand = re.sub(r'[,.:;\'"]', '', raw_cand).strip()
        clean_lower = clean_cand.lower()
        if clean_lower not in COMMON_NON_ORGS and len(clean_lower) > 1 and len(clean_lower.split()) <= 4:
            orgs.append(clean_cand)

    # Pattern 5: Reordered metric noun modifiers (e.g. annual Globex revenue, estimated Globex pipeline)
    p5 = re.compile(
        r'\b(?:annual|new|total|presales|estimated)\s+([A-Z][A-Za-z0-9&.\'-]+(?:\s+[A-Z][A-Za-z0-9&.\'-]+)?)\s+(?:revenue|pipeline|portfolio|bookings|services|poc|conversion|turnaround|sales\s+cycles|customer\s+retention)\b'
    )
    for m in p5.finditer(clause_text):
        raw_cand = m.group(1).strip()
        clean_cand = re.sub(r'[,.:;\'"]', '', raw_cand).strip()
        clean_lower = clean_cand.lower()
        if clean_lower not in COMMON_NON_ORGS and len(clean_lower) > 1 and len(clean_lower.split()) <= 4:
            orgs.append(clean_cand)

    # Pattern 6: Preposition after metric (e.g. revenue for Globex, pipeline at Globex)
    p6 = re.compile(
        r'\b(?:revenue|pipeline|portfolio|bookings|services|conversion|turnaround|sales\s+cycles)\s+(?:for|at|of)\s+([A-Z][A-Za-z0-9&.\'-]+(?:\s+[A-Z][A-Za-z0-9&.\'-]+){0,2}?)(?=[.,;:\n]|$)'
    )
    for m in p6.finditer(clause_text):
        raw_cand = m.group(1).strip()
        clean_cand = re.sub(r'[,.:;\'"]', '', raw_cand).strip()
        clean_lower = clean_cand.lower()
        if clean_lower not in COMMON_NON_ORGS and len(clean_lower) > 1 and len(clean_lower.split()) <= 4:
            orgs.append(clean_cand)

    # Pattern 7: Metric before amount (e.g. Globex revenue totaling $8M, Globex revenue amounting to $8M)
    p7 = re.compile(
        r'\b([A-Z][A-Za-z0-9&.\'-]+(?:\s+[A-Z][A-Za-z0-9&.\'-]+)?)\s+revenue\s+(?:totaling|amounting\s+to|of)\b'
    )
    for m in p7.finditer(clause_text):
        raw_cand = m.group(1).strip()
        clean_cand = re.sub(r'[,.:;\'"]', '', raw_cand).strip()
        clean_lower = clean_cand.lower()
        if clean_lower not in COMMON_NON_ORGS and len(clean_lower) > 1 and len(clean_lower.split()) <= 4:
            orgs.append(clean_cand)

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for o in orgs:
        o_low = o.lower()
        if o_low not in seen:
            seen.add(o_low)
            deduped.append(o)
    return deduped


def extract_monetary_claims(text: str) -> List[Dict[str, Any]]:
    """
    Extracts all monetary expressions from text with exact character spans,
    identifying whether a '+' precision suffix was present.
    """
    results = []

    # Pattern 1: $X[M/B/K/million/billion][+]
    p1 = re.compile(r'\$\s*([0-9]+(?:\.[0-9]+)?)\s*([mMkKbB]|million|billion|thousand)?(\+)?', re.IGNORECASE)
    for m in p1.finditer(text):
        raw_full = m.group(0).strip()
        num_str = m.group(1)
        unit = m.group(2) or ""
        plus = m.group(3) or ""
        val = parse_monetary_value(num_str, unit)

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())

        results.append({
            "raw_text": raw_full,
            "numeric_value": val,
            "has_plus": bool(plus) or ("+" in raw_full),
            "sentence": sentence,
            "clause": clause,
            "start": m.start(),
            "end": m.end()
        })

    # Pattern 2: X million/billion dollars
    p2 = re.compile(r'\b([0-9]+(?:\.[0-9]+)?)\s+(million|billion|thousand)\s+dollars(\+)?\b', re.IGNORECASE)
    for m in p2.finditer(text):
        raw_full = m.group(0).strip()
        num_str = m.group(1)
        unit = m.group(2)
        plus = m.group(3) or ""
        val = parse_monetary_value(num_str, unit)

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())

        results.append({
            "raw_text": raw_full,
            "numeric_value": val,
            "has_plus": bool(plus) or ("+" in raw_full),
            "sentence": sentence,
            "clause": clause,
            "start": m.start(),
            "end": m.end()
        })

    return results


def extract_percentage_claims(text: str) -> List[Dict[str, Any]]:
    """
    Extracts all percentage expressions from text (e.g. 23%, 40%, 85%, 20 percent).
    """
    results = []
    p = re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*(?:%|\bpercent\b)', re.IGNORECASE)
    for m in p.finditer(text):
        raw_full = m.group(0).strip()
        num_str = m.group(1)
        try:
            val = float(num_str)
        except ValueError:
            continue

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())

        results.append({
            "raw_text": raw_full,
            "numeric_value": val,
            "sentence": sentence,
            "clause": clause,
            "start": m.start(),
            "end": m.end()
        })
    return results


# ---------------------------------------------------------------------------
# First-Person Employment and Chronology Claim Extraction (Section 11)
# ---------------------------------------------------------------------------

MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12
}

WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "several": 3, "multiple": 3
}


def parse_chronology_details(text: str) -> Dict[str, Any]:
    """
    Extracts structured chronology details from a sentence or clause:
    start_year, start_month, end_year, end_month, is_current_claim,
    is_ended_claim, is_former_claim, join_year, join_month, leave_year, leave_month, duration_years.
    """
    details: Dict[str, Any] = {
        "start_year": None,
        "start_month": None,
        "end_year": None,
        "end_month": None,
        "is_current_claim": None,
        "is_ended_claim": None,
        "is_former_claim": None,
        "join_year": None,
        "join_month": None,
        "leave_year": None,
        "leave_month": None,
        "duration_years": None
    }
    t_lower = text.lower()

    # 1. Current status markers
    if re.search(r'\b(?:currently\s+(?:work|working|employed|serve|serving|advise|advising)|am\s+currently|current\s+(?:role|position|tenure|employer)|these\s+days|now\b|still\s+(?:work|working|employed|serve|serving|advise|advising|employs)|employs\s+me|continues\s+to\s+employ\s+me|remain\s+(?:employed|working|on\s+the\s+payroll)|continue\s+to\s+work|present\b)', t_lower):
        details["is_current_claim"] = True

    # 1b. Former status markers
    if re.search(r'\b(?:formerly\s+(?:worked|employed|served|advised)|previously\s+(?:worked|employed|served|advised)|no\s+longer\s+employed|used\s+to\s+work|had\s+a\s+job|former\s+employer|past\s+employer)\b', t_lower):
        details["is_former_claim"] = True
        details["is_ended_claim"] = True

    # 2. Date ranges: from [Month] Year to/through/until/- [Month] Year/present
    m_range = re.search(r'\b(?:from\s+)?(?:([a-z]+)\s+)?(20\d\d|19\d\d)\s*(?:to|through|until|–|—|-)\s*(?:([a-z]+)\s+)?(20\d\d|19\d\d|present|current|now)\b', t_lower)
    if m_range:
        m1_str, y1_str, m2_str, y2_str = m_range.groups()
        details["start_year"] = int(y1_str)
        if m1_str and m1_str.lower() in MONTH_NAMES:
            details["start_month"] = MONTH_NAMES[m1_str.lower()]

        if y2_str in ["present", "current", "now"]:
            details["is_current_claim"] = True
        else:
            details["end_year"] = int(y2_str)
            details["is_ended_claim"] = True
            if m2_str and m2_str.lower() in MONTH_NAMES:
                details["end_month"] = MONTH_NAMES[m2_str.lower()]

    # 3. Between [Month] Year and [Month] Year
    m_between = re.search(r'\bbetween\s+(?:([a-z]+)\s+)?(20\d\d|19\d\d)\s+and\s+(?:([a-z]+)\s+)?(20\d\d|19\d\d)\b', t_lower)
    if m_between and not details["start_year"]:
        m1_str, y1_str, m2_str, y2_str = m_between.groups()
        details["start_year"] = int(y1_str)
        details["end_year"] = int(y2_str)
        details["is_ended_claim"] = True
        if m1_str and m1_str.lower() in MONTH_NAMES:
            details["start_month"] = MONTH_NAMES[m1_str.lower()]
        if m2_str and m2_str.lower() in MONTH_NAMES:
            details["end_month"] = MONTH_NAMES[m2_str.lower()]

    # 4. Beginning / starting / joined / hired / started in [Month] Year
    m_join = re.search(r'\b(?:beginning\s+in|starting\s+in|started\s+in|started\s+at|joined|hired(?:\s+by|\s+me)?|brought(?:\s+me)?\s+on)\s+(?:[A-Za-z0-9&.\'-]+\s+)?(?:in\s+)?(?:([a-z]+)\s+)?(20\d\d|19\d\d)\b', t_lower)
    if m_join and not details["start_year"]:
        m_str, y_str = m_join.groups()
        details["join_year"] = int(y_str)
        details["start_year"] = int(y_str)
        if m_str and m_str.lower() in MONTH_NAMES:
            details["join_month"] = MONTH_NAMES[m_str.lower()]
            details["start_month"] = MONTH_NAMES[m_str.lower()]

    # 5. Ending in / left / departed / ended in [Month] Year
    m_leave = re.search(r'\b(?:ending\s+in|left|departed|tenure\s+ended(?:\s+in)?|ended\s+in)\s+(?:[A-Za-z0-9&.\'-]+\s+)?(?:in\s+)?(?:([a-z]+)\s+)?(20\d\d|19\d\d)\b', t_lower)
    if m_leave and not details["end_year"]:
        m_str, y_str = m_leave.groups()
        details["leave_year"] = int(y_str)
        details["end_year"] = int(y_str)
        details["is_ended_claim"] = True
        if m_str and m_str.lower() in MONTH_NAMES:
            details["leave_month"] = MONTH_NAMES[m_str.lower()]
            details["end_month"] = MONTH_NAMES[m_str.lower()]

    # 6. Worked through / until / to Year (e.g. 'I worked at Google through 2024')
    m_through = re.search(r'\b(?:worked\s+at|served\s+at|was\s+at|[a-z0-9&.\'-]+)\s+(?:through|until|to)\s+(?:([a-z]+)\s+)?(20\d\d|19\d\d)\b', t_lower)
    if m_through and not details["end_year"]:
        m_str, y_str = m_through.groups()
        details["end_year"] = int(y_str)
        details["is_ended_claim"] = True
        if m_str and m_str.lower() in MONTH_NAMES:
            details["end_month"] = MONTH_NAMES[m_str.lower()]

    # 7. Since [Month] Year / from Year onward
    m_since = re.search(r'\b(?:since|from)\s+(?:([a-z]+)\s+)?(20\d\d|19\d\d)(?:\s+onward)?\b', t_lower)
    if m_since and not details["start_year"]:
        m_str, y_str = m_since.groups()
        details["start_year"] = int(y_str)
        if "onward" in t_lower or "since" in t_lower:
            details["is_current_claim"] = True
        if m_str and m_str.lower() in MONTH_NAMES:
            details["start_month"] = MONTH_NAMES[m_str.lower()]

    # 8. Duration (spent N years, for N years)
    m_dur = re.search(r'\b(?:spent|for)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|several|multiple)\s+years\b', t_lower)
    if m_dur:
        dur_raw = m_dur.group(1).lower()
        if dur_raw.isdigit():
            details["duration_years"] = float(dur_raw)
        elif dur_raw in WORD_TO_NUM:
            details["duration_years"] = float(WORD_TO_NUM[dur_raw])

    return details


def extract_first_person_employment_claims(text: str) -> List[Dict[str, Any]]:
    """
    Extracts all explicit first-person employment, title, payroll, and chronology assertions.
    Covers candidate-subject and employer-subject grammar:
    - I worked at/for X
    - X employed me / X has employed me / X hired me / X was my employer
    - My paycheck came from X / I was on X's payroll
    - The company I worked for was X
    - I served as <Title> at X
    """
    claims = []

    # Pattern 1: 'At/With/For/While at <Company>, I <verb>...'
    p_at = re.compile(
        r'\b(?:at|with|for|while\s+at|while\s+working\s+(?:at|for|with))\s+([A-Za-z0-9\s&.,\'-]+?),\s*(?:i\s+(?:was|worked|served|generated|delivered|managed|earned|led|held|joined|left|built|directed|spearheaded|ran|spent|oversaw)|my\s+role\s+was)\b',
        re.IGNORECASE
    )
    for m in p_at.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if len(clean_company) > 1 and len(clean_company.split()) <= 4 and clean_company.lower() not in COMMON_NON_ORGS:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 2A: First-person active employment verbs with explicit preposition
    p_emp_a = re.compile(
        r'\bi\s+(?:currently\s+work|formerly\s+worked|previously\s+worked|used\s+to\s+work|used\s+to\s+be|still\s+work|continue\s+to\s+work|remain\s+working|have\s+worked|worked|work|served|was|have\s+been|am\s+currently\s+employed|am\s+no\s+longer\s+employed|am\s+employed|was\s+employed|remain\s+employed|hold\s+the\s+role\s+of|held\s+the\s+role\s+of|held\s+a\s+role|had\s+a\s+job|spent\s+\w+\s+years\s+(?:working\s+)?)\s*(?:at|with|for|by|in)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+as|\s+for|\s+leading|\s+managing|\s+building|\s+developing|\s+in\s+\d{4}|\s+after|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_emp_a.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 2B: Prepositional introductory employment phrases
    p_emp_b = re.compile(
        r'\b(?:when\s+i\s+was\s+(?:employed\s+)?(?:at|with|for|by)|during\s+my\s+(?:time|tenure|years)\s+(?:at|with|for)|my\s+(?:role|position|tenure|employment)\s+(?:at|with|for)|as\s+an\s+employee\s+(?:at|with|for)|while\s+working\s+(?:at|with|for)|while\s+employed\s+(?:at|with|for|by)|led\s+[a-z\s]+\s+while\s+employed\s+by)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+as|\s+for|\s+leading|\s+managing|\s+building|\s+developing|\s+in\s+\d{4}|\s+after|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_emp_b.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 2a: 'I was with <Company>'
    p_with = re.compile(
        r'\bi\s+(?:was|have\s+been)\s+with\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+as|\s+in\s+\d{4}|$)',
        re.IGNORECASE
    )
    for m in p_with.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 2b: Joined or left employer (e.g. 'I joined Google in 2019', 'I left Google in 2020')
    p_join_leave = re.compile(
        r'\bi\s+(?:joined|left)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+in\s+\d{4}|\s+in|\s+after|\s+from|\s+as|\s+where|$)',
        re.IGNORECASE
    )
    for m in p_join_leave.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 2c: 'I [currently/formerly] advise[d] <Company>'
    p_advise = re.compile(
        r'\bi\s+(?:currently\s+advise|formerly\s+advised|previously\s+advised|advised|advise)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+as|\s+on|\s+since|\s+from|\s+in\s+\d{4}|$)',
        re.IGNORECASE
    )
    for m in p_advise.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": "Strategic Advisor",
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 3: Employer-subject grammar (e.g. 'Amazon has employed me since 2020', 'Netflix hired me in 2019', 'Pythian still employs me', 'Pythian continues to employ me')
    p_hired = re.compile(
        r'\b([A-Za-z0-9\s&.,\'-]+?)\s+(?:has\s+employed\s+me|employed\s+me|still\s+employs\s+me|employs\s+me|continues\s+to\s+employ\s+me|hired\s+me|recruited\s+me|brought\s+me\s+on)\b',
        re.IGNORECASE
    )
    for m in p_hired.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 4: Payroll / paycheck assertions (e.g. 'My paycheck came from Netflix', 'on Apple's payroll', 'on the payroll at Pythian')
    p_payroll = re.compile(
        r'\b(?:my\s+paycheck\s+came\s+from|my\s+salary\s+came\s+from|(?:was|am\s+currently|remain|spent\s+[a-z0-9\s]+)\s+(?:on\s+the\s+payroll\s+at|on))\s+([A-Za-z0-9\s&.,\'-]+?)(?:[\'’]s\s+payroll|[.,;:\n]|\s+for|\s+where|\s+as|$)',
        re.IGNORECASE
    )
    for m in p_payroll.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        clean_company = re.sub(r'[\'’]s$', '', clean_company).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 5: Relative / inverted employer identity (e.g. 'Globex was my employer', 'My current employer is Pythian')
    p_rel_emp = re.compile(
        r'\b(?:([A-Za-z0-9\s&.,\'-]+?)\s+was\s+my\s+employer|the\s+(?:company|firm)\s+i\s+worked\s+for\s+was\s+([A-Za-z0-9\s&.,\'-]+?)|my\s+(?:current\s+)?(?:employer|company)\s+(?:is|was)\s+([A-Za-z0-9\s&.,\'-]+?))\b',
        re.IGNORECASE
    )
    for m in p_rel_emp.finditer(text):
        c1, c2, c3 = m.groups()
        company_raw = (c1 or c2 or c3 or "").strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                chrono = parse_chronology_details(sentence)
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 6: 'Before/After joining X, I worked at Y'
    p_before_after = re.compile(
        r'\b(?:before|after)\s+(?:joining|leaving)\s+([A-Za-z0-9\s&.,\'-]+?),\s*i\s+(?:worked for|worked at|was at|served at)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|$)',
        re.IGNORECASE
    )
    for m in p_before_after.finditer(text):
        c1 = re.sub(r'[,.:;\'"]', '', m.group(1)).strip()
        c2 = re.sub(r'[,.:;\'"]', '', m.group(2)).strip()
        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
        chrono = parse_chronology_details(sentence)
        for c in [c1, c2]:
            if len(c) > 1 and len(c.split()) <= 4 and c.lower() not in COMMON_NON_ORGS:
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": c,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause,
                    **chrono
                })

    # Pattern 7: 'I served as <Title> at <Company>' / 'I was <Title> at <Company>' / 'I worked at <Company> as <Title>'
    p_title_emp = re.compile(
        r'\b(?:i\s+served\s+as|i\s+currently\s+serve\s+as|i\s+currently\s+work\s+as|i\s+was|holding\s+the\s+role\s+of|my\s+role\s+as|my\s+role\s+was|my\s+title\s+was|i\s+am(?:\s+currently)?(?: the)?|as)\s+([A-Za-z\s&/,—\-]+?)\s+(?:at|with|for|of)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_title_emp.finditer(text):
        title_raw = m.group(1).strip()
        company_raw = m.group(2).strip()
        clean_title = re.sub(r'[,.]', '', title_raw).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()

        if clean_title.lower() in ["a result", "part", "such", "an example", "well as", "soon"]:
            continue
        if clean_company.lower() in COMMON_NON_ORGS:
            continue

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
        if not is_opportunity_or_target_role_reference(sentence, clean_company):
            chrono = parse_chronology_details(sentence)
            claims.append({
                "raw_text": m.group(0),
                "claimed_employer": clean_company,
                "claimed_title": clean_title,
                "sentence": sentence,
                "clause": clause,
                **chrono
            })

    # Pattern 7b: 'I worked at <Company> as <Title>'
    p_emp_as_title = re.compile(
        r'\bi\s+(?:worked|served|was)\s+(?:at|with|for)\s+([A-Za-z0-9\s&.,\'-]+?)\s+as\s+([A-Za-z\s&/,—\-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_emp_as_title.finditer(text):
        company_raw = m.group(1).strip()
        title_raw = m.group(2).strip()
        clean_company = re.sub(r'[,.:;\'"]', '', company_raw).strip()
        clean_title = re.sub(r'[,.]', '', title_raw).strip()

        if clean_company.lower() in COMMON_NON_ORGS:
            continue
        if clean_title.lower() in ["a result", "part", "such", "an example", "well as", "soon"]:
            continue

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
        if not is_opportunity_or_target_role_reference(sentence, clean_company):
            chrono = parse_chronology_details(sentence)
            claims.append({
                "raw_text": m.group(0),
                "claimed_employer": clean_company,
                "claimed_title": clean_title,
                "sentence": sentence,
                "clause": clause,
                **chrono
            })

    # Pattern 8: Standalone first-person title assertions without explicit company
    p_title_standalone = re.compile(
        r'\b(?:i\s+served\s+as|i\s+was|my\s+role\s+was|my\s+title\s+was|holding\s+the\s+role\s+of|i\s+held\s+the\s+title\s+of)\s+(?:a|an|the)?\s*([A-Za-z\s&/,—\-]+?)(?:[.,;:\n]|\s+at\s+|\s+with\s+|\s+for\s+|\s+where|\s+leading|\s+managing|\s+building|\s+developing|\s+and|\s+in\s+my|$)',
        re.IGNORECASE
    )
    for m in p_title_standalone.finditer(text):
        title_raw = m.group(1).strip()
        clean_title = re.sub(r'[,.]', '', title_raw).strip()
        clean_title_lower = clean_title.lower()
        if clean_title_lower in ["a result", "part", "such", "an example", "well as", "responsible", "pleased", "excited", "happy", "thrilled"]:
            continue

        # Check if already captured with company in Pattern 7
        if any(c.get("claimed_title") and (clean_title_lower == c["claimed_title"].lower() or clean_title_lower in c["claimed_title"].lower()) for c in claims):
            continue

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
        if not is_opportunity_or_target_role_reference(sentence, ""):
            chrono = parse_chronology_details(sentence)
            claims.append({
                "raw_text": m.group(0),
                "claimed_employer": None,
                "claimed_title": clean_title,
                "sentence": sentence,
                "clause": clause,
                **chrono
            })

    return claims


def detect_unparsed_career_assertions(text: str, parsed_claims: List[Dict[str, Any]]) -> List[str]:
    """
    Scans text for conservative first-person career, employment, and payroll signals.
    Returns list of unparsed/indeterminate career assertion sentences that could not be verified.
    """
    career_signals = [
        r'\b(?:i\s+(?:used\s+to\s+work|used\s+to\s+be|worked|work|served|joined|left|led|managed|held|built|am\s+employed|was\s+employed|remain\s+employed|still\s+work|continue\s+to\s+work|spent))\b',
        r'\b(?:during my (?:time|tenure|years|role|employment))\b',
        r'\b(?:when i was (?:at|employed|working|leading|managing))\b',
        r'\b(?:while (?:employed|working|leading|managing|spearheading)\s+(?:at|for|by|with|across)?)\b',
        r'\b(?:my (?:employer|role|title|position|tenure|team at|paycheck|salary))\b',
        r'\b(?:former\s+[a-z\s]+)\b',
        r'\b(?:spent\s+(?:\w+|\d+)\s+years)\b',
        r'\b(?:hired me|employed me|employs me|payroll)\b',
        r'\b(?:was my employer|company i worked for|current employer)\b'
    ]

    unparsed = []
    sentences = [s.strip() for s in re.split(r'(?:\.\s+|\n+)', text) if s.strip()]
    for sent in sentences:
        if is_opportunity_or_target_role_reference(sent, ""):
            continue

        has_signal = any(re.search(pat, sent, re.IGNORECASE) for pat in career_signals)
        if has_signal:
            was_extracted = any(
                c.get("sentence") and (sent in c["sentence"] or c["sentence"] in sent)
                for c in parsed_claims
            )
            if not was_extracted:
                unparsed.append(sent)

    return unparsed


# ---------------------------------------------------------------------------
# Schema-Driven Quantitative Fact Tuple Matcher (Section 6 & 10)
# ---------------------------------------------------------------------------

def match_claim_to_fact(
    extracted_text: str,
    val: float,
    has_plus: bool,
    clause_text: str,
    sentence_text: str,
    fact: CanonicalFactDefinition
) -> Tuple[bool, ClaimStatus, str]:
    """
    Affirmatively matches an extracted quantitative claim against a CanonicalFactDefinition.
    Enforces value, precision, negation/disclaimer absence, attribution, metric, outcome,
    and local proposition employer binding without finite denylist reliance.
    """
    clause_lower = clause_text.lower()
    sentence_lower = sentence_text.lower()

    # 1. Negation & Disclaimer Check
    is_neg, neg_reason = check_negation_or_disclaimer(clause_text)
    if not is_neg:
        is_neg, neg_reason = check_negation_or_disclaimer(sentence_text)
    if is_neg:
        return False, ClaimStatus.UNSUPPORTED, f"Claim in '{clause_text}' is negated or disclaimed: detected {neg_reason}."

    # 2. Precision Policy Check
    if fact.precision_policy == PrecisionPolicy.PLUS_REQUIRED and not has_plus:
        return False, ClaimStatus.INSUFFICIENT_PRECISION, f"Claim '{extracted_text}' in '{sentence_text}' lacks required canonical '+' precision (must be '{fact.display_value}')."
    elif fact.precision_policy == PrecisionPolicy.EXACT_REQUIRED and has_plus:
        return False, ClaimStatus.DISALLOWED_QUALIFIER, f"Claim '{extracted_text}' in '{sentence_text}' improperly inflates precision with '+' (must be exact '{fact.display_value}')."

    # 3. Forbidden Attribution Check
    if any(fb in clause_lower for fb in fact.forbidden_attribution_aliases):
        matched_fb = next(fb for fb in fact.forbidden_attribution_aliases if fb in clause_lower)
        return False, ClaimStatus.DISALLOWED_QUALIFIER, f"Claim in '{clause_text}' violates attribution standards: disallowed term '{matched_fb}' (authorized: {fact.canonical_text})."

    # 4. Required Attribution Check (Affirmative)
    has_req_attribution = any(req in clause_lower for req in fact.required_attribution_aliases) or any(req in sentence_lower for req in fact.required_attribution_aliases)
    if not has_req_attribution:
        return False, ClaimStatus.UNSUPPORTED, f"Claim in '{sentence_text}' lacks authorized attribution qualifiers for {fact.fact_id}."

    # 5. Forbidden Metric Check
    if any(fb in clause_lower for fb in fact.forbidden_metric_aliases):
        matched_fb = next(fb for fb in fact.forbidden_metric_aliases if fb in clause_lower)
        return False, ClaimStatus.MISATTRIBUTED, f"Claim in '{clause_text}' is assigned to unapproved metric '{matched_fb}' (authorized: {fact.canonical_text})."

    # 6. Required Metric Check (Affirmative)
    has_req_metric = any(req in clause_lower for req in fact.required_metric_aliases) or any(req in sentence_lower for req in fact.required_metric_aliases)
    if not has_req_metric:
        return False, ClaimStatus.UNSUPPORTED, f"Claim in '{sentence_text}' lacks required canonical metric keywords for {fact.fact_id}."

    # 7. Structural Employer & Scope Policy Check
    extracted_orgs = extract_governing_organizations(clause_text)

    if fact.scope_policy == ScopePolicy.CAREER_WIDE_REQUIRED:
        if extracted_orgs:
            return False, ClaimStatus.DISALLOWED_QUALIFIER, f"Claim in '{clause_text}' misattributes career-wide impact ({fact.display_value}) to specific organization '{extracted_orgs[0]}'."
        if any(conf in clause_lower for conf in fact.conflicting_scope_aliases):
            matched_conf = next(conf for conf in fact.conflicting_scope_aliases if conf in clause_lower)
            return False, ClaimStatus.DISALLOWED_QUALIFIER, f"Claim in '{clause_text}' misattributes career-wide impact ({fact.display_value}) to single employer/scope '{matched_conf}'."

        has_career_scope = any(req in clause_lower for req in fact.required_scope_aliases) or any(req in sentence_lower for req in fact.required_scope_aliases)
        if not has_career_scope:
            return False, ClaimStatus.UNSUPPORTED, f"Claim in '{sentence_text}' lacks required career-wide scope context for {fact.fact_id}."

    elif fact.scope_policy == ScopePolicy.EMPLOYER_BOUND_REQUIRED:
        allowed_norm = [normalize_employer(a) for a in fact.allowed_employer_aliases]

        # Check for any unauthorized / conflicting organizations in the local proposition
        for org in extracted_orgs:
            norm_org = normalize_employer(org)
            is_allowed = (norm_org in allowed_norm)
            if not is_allowed:
                return False, ClaimStatus.MISATTRIBUTED, f"Claim in '{clause_text}' misattributes {fact.display_value} to unauthorized organization '{org}' (authorized: {fact.canonical_text})."

        # Check that required canonical employer is present in the local proposition
        has_authorized_in_clause = any(
            normalize_employer(org) in allowed_norm
            for org in extracted_orgs
        ) or any(normalize_employer(alias) in [normalize_employer(w) for w in clause_lower.split()] or normalize_employer(alias) in clause_lower for alias in fact.allowed_employer_aliases)

        if not has_authorized_in_clause:
            return False, ClaimStatus.UNSUPPORTED, f"Claim in '{clause_text}' omits required canonical employer '{fact.required_employer}' for {fact.fact_id}."

    return True, ClaimStatus.SUPPORTED, f"Verified against canonical fact {fact.fact_id}"


# ---------------------------------------------------------------------------
# Generic Multi-Tenure Employment & Chronology Validator (Sections 7, 8, 9)
# ---------------------------------------------------------------------------

def validate_first_person_employment_claim(
    claim: Dict[str, Any]
) -> Tuple[bool, ClaimStatus, str, Optional[str]]:
    """
    Generic ledger-record comparison for employment and title assertions.
    Evaluates ALL matching records for the employer, compares dates, status, duration,
    and exact normalized titles, selecting among multi-tenure records without relying on insertion order.
    """
    raw_emp = claim.get("claimed_employer")
    raw_title = claim.get("claimed_title")
    raw_match = claim.get("raw_text", "")
    sentence = claim.get("sentence", "")

    # Case A: Standalone title assertion without explicit company
    if not raw_emp and raw_title:
        norm_claimed_title = normalize_title(raw_title)

        # Target role titles cannot be claimed as held titles
        if any(normalize_title(target_t) == norm_claimed_title or norm_claimed_title in normalize_title(target_t) for target_t in TARGET_ROLE_TITLES):
            return False, ClaimStatus.UNSUPPORTED, f"Title claim '{raw_title}' in '{sentence}' is a target role or positioning title, not a title held in Brian Kinlaw's employment records.", None

        # Verify against all canonical employment records
        matched_recs = []
        for rec in CANONICAL_EMPLOYMENT_RECORDS.values():
            rec_titles = get_normalized_titles_for_record(rec)
            if norm_claimed_title in rec_titles:
                matched_recs.append(rec)

        if not matched_recs:
            return False, ClaimStatus.UNSUPPORTED, f"Title claim '{raw_title}' in '{sentence}' is not an authorized held title in Brian Kinlaw's Canonical Career System.", None

        chosen_rec = matched_recs[0]
        fact_id = f"FACT_EMPLOYMENT_{chosen_rec.employer_key.upper()}"
        return True, ClaimStatus.SUPPORTED, f"Authorized title at {chosen_rec.employer_canonical}: {raw_title}", fact_id

    # Case B: Employment assertion with claimed employer
    if raw_emp:
        norm_claimed_emp = normalize_employer(raw_emp)

        # Resolve all matching canonical employment records via exact normalized alias equality
        candidate_records = [
            rec for rec in CANONICAL_EMPLOYMENT_RECORDS.values()
            if any(norm_claimed_emp == normalize_employer(alias) for alias in rec.employer_aliases)
        ]

        if not candidate_records:
            return False, ClaimStatus.MISATTRIBUTED, f"Claim '{raw_match}' asserts employment at '{raw_emp}', which is not in Brian Kinlaw's canonical employment history.", None

        # Disambiguate multi-tenure employers: require title or specific dates to select
        has_specific_dates = bool(claim.get("start_year") or claim.get("end_year") or claim.get("join_year") or claim.get("leave_year"))
        if len(candidate_records) > 1 and not raw_title and not has_specific_dates:
            return False, ClaimStatus.INDETERMINATE, f"Multiple distinct canonical tenures exist for '{raw_emp}' and the claim provides no disambiguating title or chronology.", None

        # Evaluate compatibility with each candidate record
        compatible_records: List[CanonicalEmploymentRecord] = []
        incompatibility_reasons: List[str] = []

        for rec in candidate_records:
            rec_titles = get_normalized_titles_for_record(rec)

            # 1. Exact Title Check (when title is claimed)
            if raw_title:
                norm_claimed_title = normalize_title(raw_title)
                if norm_claimed_title not in rec_titles:
                    incompatibility_reasons.append(f"Title '{raw_title}' is not authorized for tenure {rec.employer_key} ({rec.employer_canonical})")
                    continue

            # 2. Current vs Past Status Check
            if claim.get("is_current_claim") is True and not rec.is_current:
                incompatibility_reasons.append(f"Claim asserts current employment at {rec.employer_canonical}, but tenure ended in {rec.end_year}")
                continue

            if (claim.get("is_ended_claim") is True or claim.get("is_former_claim") is True) and rec.is_current and rec.end_year is None:
                incompatibility_reasons.append(f"Claim asserts ended tenure at {rec.employer_canonical}, but {rec.employer_canonical} advisory is active")
                continue

            # 3. Start / Join Year & Month Check
            start_y = claim.get("start_year") or claim.get("join_year")
            start_m = claim.get("start_month") or claim.get("join_month")
            if start_y is not None:
                if start_m is not None and rec.start_month is not None:
                    if start_y != rec.start_year or start_m != rec.start_month:
                        incompatibility_reasons.append(f"Start date {start_m}/{start_y} does not match canonical {rec.start_month}/{rec.start_year} at {rec.employer_canonical}")
                        continue
                else:
                    if start_y != rec.start_year:
                        incompatibility_reasons.append(f"Start year {start_y} does not match canonical start year {rec.start_year} at {rec.employer_canonical}")
                        continue

            # 4. End / Leave Year & Month Check
            end_y = claim.get("end_year") or claim.get("leave_year")
            end_m = claim.get("end_month") or claim.get("leave_month")
            if end_y is not None:
                if rec.end_year is None:
                    incompatibility_reasons.append(f"Claim asserts end year {end_y}, but {rec.employer_canonical} tenure is ongoing")
                    continue
                if end_m is not None and rec.end_month is not None:
                    if end_y != rec.end_year or end_m != rec.end_month:
                        incompatibility_reasons.append(f"End date {end_m}/{end_y} does not match canonical {rec.end_month}/{rec.end_year} at {rec.employer_canonical}")
                        continue
                else:
                    if end_y != rec.end_year:
                        incompatibility_reasons.append(f"End year {end_y} does not match canonical end year {rec.end_year} at {rec.employer_canonical}")
                        continue

            # 5. Duration Check
            dur = claim.get("duration_years")
            if dur is not None:
                end_val = (rec.end_year or 2026) + ((rec.end_month or 9) / 12.0)
                start_val = rec.start_year + ((rec.start_month or 1) / 12.0)
                canonical_dur = end_val - start_val
                if abs(dur - canonical_dur) > 1.0 and abs(dur - round(canonical_dur)) > 0:
                    incompatibility_reasons.append(f"Claimed duration {dur} years does not match canonical tenure length ({round(canonical_dur, 1)} years)")
                    continue

            compatible_records.append(rec)

        if len(compatible_records) == 1:
            chosen_rec = compatible_records[0]
            fact_id = f"FACT_EMPLOYMENT_{chosen_rec.employer_key.upper()}"
            ref = f"{chosen_rec.employer_canonical} ({chosen_rec.employer_key})"
            if raw_title:
                ref += f" - {raw_title}"
            return True, ClaimStatus.SUPPORTED, f"Verified against canonical employment record {ref}", fact_id
        elif len(compatible_records) == 0:
            reasons_str = "; ".join(incompatibility_reasons) if incompatibility_reasons else "No compatible canonical record found."
            return False, ClaimStatus.UNSUPPORTED, f"Chronology/title violation for {raw_emp}: {reasons_str}", None
        else:
            # Ambiguous multi-tenure match
            chosen_rec = compatible_records[0]
            fact_id = f"FACT_EMPLOYMENT_{chosen_rec.employer_key.upper()}"
            return True, ClaimStatus.SUPPORTED, f"Verified against canonical record {chosen_rec.employer_canonical}", fact_id

    return False, ClaimStatus.INDETERMINATE, "Unresolved employment assertion structure.", None


# ---------------------------------------------------------------------------
# Authoritative Main Grounding Entry Point (CCS v2.1 — Phase 5.3)
# ---------------------------------------------------------------------------

def validate_canonical_grounding(
    draft_text: Any,
    claim_bindings: Optional[List[Union[ClaimBlockBinding, Dict[str, Any]]]] = None,
    provenance_claims: Optional[List[Dict[str, Any]]] = None,
    recipient_company: Optional[str] = None,
    draft_id: Optional[str] = None
) -> GroundingValidationResult:
    """
    Phase 5.5.1 Hybrid Grounding Validation & Advisory Scanner Engine:
    - Authoritative Grounding Path: ONLY provenance-backed claims regenerated and verified
      against server-side records and deterministic canonical templates bound to exact draft blocks
      can receive GROUNDED.
    - Advisory Scanner Path: All manual, typed, pasted, or edited prose is scanned for potential
      contradictions and unverified career claims. It can NEVER receive GROUNDED authority.
    """
    # -------------------------------------------------------------------------
    # 1. Strict Fail-Closed Input Validation
    # -------------------------------------------------------------------------
    if draft_text is None or not isinstance(draft_text, str):
        return GroundingValidationResult(
            is_grounded=False,
            status=GroundingStatus.VALIDATION_FAILED,
            requires_human_review=True,
            validation_summary="Validation failed: input is None or non-string."
        )

    clean_text = draft_text.strip()
    if not clean_text:
        return GroundingValidationResult(
            is_grounded=False,
            status=GroundingStatus.VALIDATION_FAILED,
            requires_human_review=True,
            validation_summary="Validation failed: input is empty or whitespace-only."
        )

    if (clean_text.startswith("{") and clean_text.endswith("}")) or (clean_text.startswith("[") and clean_text.endswith("]")):
        return GroundingValidationResult(
            is_grounded=False,
            status=GroundingStatus.VALIDATION_FAILED,
            requires_human_review=True,
            validation_summary="Validation failed: input is raw structured data/JSON rather than valid email prose."
        )

    supported: List[SupportedClaim] = []
    unsupported: List[UnsupportedClaim] = []
    verified_fact_ids: List[str] = []
    verified_ranges: List[Tuple[int, int]] = []

    # -------------------------------------------------------------------------
    # 2. Authoritative Provenance Claims Manifest & Verification
    # -------------------------------------------------------------------------
    raw_bindings = list(claim_bindings) if claim_bindings is not None else []

    # Failure B remediation: Detached legacy provenance_claims without explicit offsets
    # cannot establish authoritative grounding and are treated as non-authoritative metadata.
    if provenance_claims:
        for i, pc in enumerate(provenance_claims):
            cid = pc.get("claim_instance_id") or pc.get("claim_id") or f"legacy_claim_{i}"
            c_text = pc.get("text") or pc.get("extracted_text") or pc.get("rendered_text") or str(cid)
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.QUALIFIER,
                extracted_text=c_text,
                reason=f"Detached legacy provenance claim '{cid}' lacks explicit manifest block binding [start_offset:end_offset] and cannot establish authoritative grounding.",
                status=ClaimStatus.UNVERIFIED
            ))

    if raw_bindings:
        is_manifest_valid, m_status, m_reason, parsed_bindings = validate_claim_manifest(
            draft_text=draft_text,
            claim_bindings=raw_bindings,
            draft_id=draft_id
        )
        if not is_manifest_valid:
            return GroundingValidationResult(
                is_grounded=False,
                status=m_status,
                requires_human_review=True,
                validation_summary=f"Claim manifest validation failed: {m_reason}"
            )

        for binding in parsed_bindings:
            is_valid, c_status, c_reason, supp = verify_provenance_claim_binding(binding, draft_text)
            if is_valid and supp:
                supported.append(supp)
                if supp.fact_id not in verified_fact_ids:
                    verified_fact_ids.append(supp.fact_id)
                verified_ranges.append((binding.start_offset, binding.end_offset))
            else:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.QUALIFIER,
                    extracted_text=binding.submitted_block_text or str(binding.claim_instance_id),
                    reason=c_reason,
                    status=c_status
                ))

    # -------------------------------------------------------------------------
    # 3. Mask Verified Blocks & Advisory Scanner on Remaining Draft Text
    # -------------------------------------------------------------------------
    # Mask out verified claim blocks so surrounding/unverified prose is scanned advisorily
    masked_chars = list(draft_text)
    for start, end in verified_ranges:
        for idx in range(start, min(end, len(masked_chars))):
            masked_chars[idx] = ' '
    masked_text = "".join(masked_chars)

    monetary_claims = extract_monetary_claims(masked_text)
    for mc in monetary_claims:
        raw_str = mc["raw_text"]
        val = mc["numeric_value"]
        has_plus = mc["has_plus"]
        sentence = mc["sentence"]
        clause = mc["clause"]

        candidate_facts = [
            fdef for fdef in CANONICAL_FACT_REGISTRY.values()
            if fdef.category in [ClaimCategory.MONETARY, ClaimCategory.PIPELINE, ClaimCategory.PORTFOLIO]
            and fdef.normalized_value == val
        ]

        if not candidate_facts:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.MONETARY,
                extracted_text=raw_str,
                reason=f"Monetary value {raw_str} in sentence '{sentence}' is not in Brian Kinlaw's Canonical Accomplishment Ledger.",
                status=ClaimStatus.UNSUPPORTED
            ))
            continue

        matched_any = False
        last_failure_reason = ""
        last_failure_status = ClaimStatus.UNSUPPORTED

        for fact in candidate_facts:
            is_matched, status, reason = match_claim_to_fact(
                extracted_text=raw_str,
                val=val,
                has_plus=has_plus,
                clause_text=clause,
                sentence_text=sentence,
                fact=fact
            )
            if is_matched:
                matched_any = True
                # In Phase 5.5+, a parser match on manual prose is strictly ADVISORY (UNVERIFIED without provenance)
                unsupported.append(UnsupportedClaim(
                    category=fact.category,
                    extracted_text=raw_str,
                    reason=f"Manual or unprovenanced monetary claim '{raw_str}' detected without authoritative server-side provenance.",
                    status=ClaimStatus.UNVERIFIED
                ))
                break
            else:
                last_failure_reason = reason
                last_failure_status = status

        if not matched_any:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.MONETARY,
                extracted_text=raw_str,
                reason=last_failure_reason,
                status=last_failure_status if last_failure_status != ClaimStatus.SUPPORTED else ClaimStatus.POTENTIAL_CONFLICT
            ))

    pct_claims = extract_percentage_claims(masked_text)
    for pc in pct_claims:
        raw_str = pc["raw_text"]
        val = pc["numeric_value"]
        sentence = pc["sentence"]
        clause = pc["clause"]

        candidate_facts = [
            fdef for fdef in CANONICAL_FACT_REGISTRY.values()
            if fdef.category == ClaimCategory.PERCENTAGE and fdef.normalized_value == val
        ]

        if not candidate_facts:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.PERCENTAGE,
                extracted_text=raw_str,
                reason=f"Percentage {raw_str} in sentence '{sentence}' is not a verified Canonical Career System metric.",
                status=ClaimStatus.UNSUPPORTED
            ))
            continue

        matched_any = False
        last_failure_reason = ""
        last_failure_status = ClaimStatus.UNSUPPORTED

        for fact in candidate_facts:
            is_matched, status, reason = match_claim_to_fact(
                extracted_text=raw_str,
                val=val,
                has_plus=False,
                clause_text=clause,
                sentence_text=sentence,
                fact=fact
            )
            if is_matched:
                matched_any = True
                unsupported.append(UnsupportedClaim(
                    category=fact.category,
                    extracted_text=raw_str,
                    reason=f"Manual or unprovenanced percentage claim '{raw_str}' detected without authoritative server-side provenance.",
                    status=ClaimStatus.UNVERIFIED
                ))
                break
            else:
                last_failure_reason = reason
                last_failure_status = status

        if not matched_any:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.PERCENTAGE,
                extracted_text=raw_str,
                reason=last_failure_reason,
                status=last_failure_status if last_failure_status != ClaimStatus.SUPPORTED else ClaimStatus.POTENTIAL_CONFLICT
            ))

    emp_claims = extract_first_person_employment_claims(masked_text)
    for ec in emp_claims:
        raw_emp_claim = ec["raw_text"]

        is_supported, c_status, c_reason, fact_id = validate_first_person_employment_claim(ec)
        if is_supported:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.EMPLOYER if ec.get("claimed_employer") else ClaimCategory.TITLE,
                extracted_text=raw_emp_claim,
                reason=f"Manual employment assertion '{raw_emp_claim}' detected without authoritative server-side provenance.",
                status=ClaimStatus.UNVERIFIED
            ))
        else:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.EMPLOYER if ec.get("claimed_employer") else ClaimCategory.TITLE,
                extracted_text=raw_emp_claim,
                reason=c_reason,
                status=c_status if c_status != ClaimStatus.SUPPORTED else ClaimStatus.POTENTIAL_CONFLICT
            ))

    all_extracted_claims = monetary_claims + pct_claims + emp_claims
    unparsed_assertions = detect_unparsed_career_assertions(masked_text, all_extracted_claims)
    if unparsed_assertions:
        for u_sent in unparsed_assertions:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.EMPLOYER,
                extracted_text=u_sent,
                reason=f"Unparsed first-person career assertion detected in '{u_sent}' that could not be resolved to an authorized canonical employment record.",
                status=ClaimStatus.INDETERMINATE
            ))

    # -------------------------------------------------------------------------
    # 4. Synthesize Authoritative Grounding Result
    # -------------------------------------------------------------------------
    has_unsupported = len(unsupported) > 0
    has_supported = len(supported) > 0

    if has_supported and not has_unsupported:
        is_grounded = True
        status = GroundingStatus.GROUNDED
        requires_review = False
        summary = f"Authoritatively validated {len(supported)} provenance-backed claim(s) against Canonical Career System ({', '.join(verified_fact_ids)})."
    elif has_supported and has_unsupported:
        is_grounded = False
        status = GroundingStatus.MIXED_REVIEW_REQUIRED
        requires_review = True
        summary = f"Draft contains mixed content: {len(supported)} grounded claim(s) and {len(unsupported)} unverified or conflicting item(s). Human review required."
    elif not has_supported and has_unsupported:
        is_grounded = False
        requires_review = True
        if any(u.status in [ClaimStatus.POTENTIAL_CONFLICT, ClaimStatus.MISATTRIBUTED, ClaimStatus.UNSUPPORTED] for u in unsupported):
            status = GroundingStatus.POTENTIAL_CONFLICT
        elif any(u.status == ClaimStatus.STALE_PROVENANCE for u in unsupported):
            status = GroundingStatus.STALE_PROVENANCE
        elif any(u.status == ClaimStatus.INDETERMINATE for u in unsupported):
            status = GroundingStatus.INDETERMINATE
        else:
            status = GroundingStatus.UNVERIFIED
        unsupported_reasons = "; ".join([u.reason for u in unsupported])
        summary = f"Advisory scan identified {len(unsupported)} unverified, conflicting, or indeterminate item(s): {unsupported_reasons}"
    else:
        is_grounded = False
        status = GroundingStatus.NO_CAREER_CLAIMS_DETECTED
        requires_review = False
        summary = "Advisory scan detected no career-sensitive claims. No authoritative career grounding was performed."

    return GroundingValidationResult(
        is_grounded=is_grounded,
        status=status,
        requires_human_review=requires_review,
        supported_claims=supported,
        unsupported_claims=unsupported,
        verified_fact_ids=verified_fact_ids,
        validation_summary=summary
    )

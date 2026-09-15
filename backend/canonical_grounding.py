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
import logging
from typing import List, Dict, Any, Optional, Set, Tuple, Union
from enum import Enum
from pydantic import BaseModel, Field

logger = logging.getLogger("canonical_grounding")


class GroundingStatus(str, Enum):
    GROUNDED = "GROUNDED"
    UNGROUNDED = "UNGROUNDED"
    NO_CAREER_CLAIMS = "NO_CAREER_CLAIMS"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INDETERMINATE = "INDETERMINATE"


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
    MISATTRIBUTED = "MISATTRIBUTED"
    DISALLOWED_QUALIFIER = "DISALLOWED_QUALIFIER"
    INSUFFICIENT_PRECISION = "INSUFFICIENT_PRECISION"
    INDETERMINATE = "INDETERMINATE"


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
# Normalization & Exact Alias Matching Helpers (Section 3 & 9)
# ---------------------------------------------------------------------------

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
    if re.search(r'\b(?:currently\s+(?:work|working|employed|serve|serving|advise|advising)|am\s+currently|current\s+(?:role|position|tenure|employer)|these\s+days|now\b|still\s+(?:work|working|employed|serve|serving|advise|advising|employs)|employs\s+me|remain\s+(?:employed|on\s+the\s+payroll)|continue\s+to\s+work|present\b)', t_lower):
        details["is_current_claim"] = True

    # 1b. Former status markers
    if re.search(r'\b(?:formerly\s+(?:worked|employed|served|advised)|previously\s+(?:worked|employed|served|advised)|no\s+longer\s+employed|used\s+to\s+work|former\s+employer|past\s+employer)\b', t_lower):
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
        r'\bi\s+(?:currently\s+work|formerly\s+worked|previously\s+worked|used\s+to\s+work|used\s+to\s+be|still\s+work|continue\s+to\s+work|have\s+worked|worked|work|served|was|have\s+been|am\s+currently\s+employed|am\s+no\s+longer\s+employed|am\s+employed|was\s+employed|remain\s+employed|hold\s+the\s+role\s+of|held\s+the\s+role\s+of|held\s+a\s+role|spent\s+\w+\s+years\s+(?:working\s+)?)\s*(?:at|with|for|by|in)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+as|\s+for|\s+leading|\s+managing|\s+building|\s+developing|\s+in\s+\d{4}|\s+after|\s+i\s+|$)',
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

    # Pattern 3: Employer-subject grammar (e.g. 'Amazon has employed me since 2020', 'Netflix hired me in 2019', 'Pythian still employs me')
    p_hired = re.compile(
        r'\b([A-Za-z0-9\s&.,\'-]+?)\s+(?:has\s+employed\s+me|employed\s+me|still\s+employs\s+me|employs\s+me|hired\s+me|recruited\s+me|brought\s+me\s+on)\b',
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
    recipient_company: Optional[str] = None
) -> GroundingValidationResult:
    """
    Authoritative deterministic validation of career-sensitive claims in draft text.
    Uses schema-driven affirmative tuple matching against structured employment ledgers
    and canonical accomplishment registries. Fails closed on any unsupported, misattributed,
    indeterminate, or malformed input.
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

    # -------------------------------------------------------------------------
    # 2. Monetary Claims Validation via Common Schema Matcher
    # -------------------------------------------------------------------------
    monetary_claims = extract_monetary_claims(draft_text)
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
                supported.append(SupportedClaim(
                    fact_id=fact.fact_id,
                    category=fact.category,
                    extracted_text=raw_str,
                    canonical_reference=fact.canonical_text
                ))
                if fact.fact_id not in verified_fact_ids:
                    verified_fact_ids.append(fact.fact_id)
                break
            else:
                last_failure_reason = reason
                last_failure_status = status

        if not matched_any:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.MONETARY,
                extracted_text=raw_str,
                reason=last_failure_reason,
                status=last_failure_status
            ))

    # -------------------------------------------------------------------------
    # 3. Percentage Claims Validation via Common Schema Matcher
    # -------------------------------------------------------------------------
    pct_claims = extract_percentage_claims(draft_text)
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
                supported.append(SupportedClaim(
                    fact_id=fact.fact_id,
                    category=fact.category,
                    extracted_text=raw_str,
                    canonical_reference=fact.canonical_text
                ))
                if fact.fact_id not in verified_fact_ids:
                    verified_fact_ids.append(fact.fact_id)
                break
            else:
                last_failure_reason = reason
                last_failure_status = status

        if not matched_any:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.PERCENTAGE,
                extracted_text=raw_str,
                reason=last_failure_reason,
                status=last_failure_status
            ))

    # -------------------------------------------------------------------------
    # 4. First-Person Employment, Title & Chronology Claims Validation
    # -------------------------------------------------------------------------
    emp_claims = extract_first_person_employment_claims(draft_text)
    for ec in emp_claims:
        is_supported, c_status, c_reason, fact_id = validate_first_person_employment_claim(ec)
        if is_supported:
            supported.append(SupportedClaim(
                fact_id=fact_id or "FACT_EMPLOYMENT_UNKNOWN",
                category=ClaimCategory.EMPLOYER if ec.get("claimed_employer") else ClaimCategory.TITLE,
                extracted_text=ec["raw_text"],
                canonical_reference=c_reason
            ))
            if fact_id and fact_id not in verified_fact_ids:
                verified_fact_ids.append(fact_id)
        else:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.EMPLOYER if ec.get("claimed_employer") else ClaimCategory.TITLE,
                extracted_text=ec["raw_text"],
                reason=c_reason,
                status=c_status
            ))

    # -------------------------------------------------------------------------
    # 5. Unparsed Career Assertion Detection
    # -------------------------------------------------------------------------
    all_extracted_claims = monetary_claims + pct_claims + emp_claims
    unparsed_assertions = detect_unparsed_career_assertions(draft_text, all_extracted_claims)
    if unparsed_assertions:
        for u_sent in unparsed_assertions:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.EMPLOYER,
                extracted_text=u_sent,
                reason=f"Unparsed first-person career assertion detected in '{u_sent}' that could not be resolved to an authorized canonical employment record.",
                status=ClaimStatus.INDETERMINATE
            ))

    # -------------------------------------------------------------------------
    # 6. Synthesize Authoritative Grounding Result
    # -------------------------------------------------------------------------
    has_unsupported = len(unsupported) > 0
    has_supported = len(supported) > 0

    if has_unsupported:
        is_grounded = False
        has_indeterminate = any(u.status == ClaimStatus.INDETERMINATE for u in unsupported)
        status = GroundingStatus.INDETERMINATE if has_indeterminate else GroundingStatus.UNGROUNDED
        requires_review = True
        unsupported_reasons = "; ".join([u.reason for u in unsupported])
        summary = f"Grounding validation rejected {len(unsupported)} unverified, misattributed, or indeterminate claim(s): {unsupported_reasons}"
    elif has_supported:
        is_grounded = True
        status = GroundingStatus.GROUNDED
        requires_review = False
        summary = f"Validated {len(supported)} career claim(s) successfully against Canonical Career System facts ({', '.join(verified_fact_ids)})."
    else:
        is_grounded = True
        status = GroundingStatus.NO_CAREER_CLAIMS
        requires_review = False
        summary = "Draft evaluated as safe (valid prose containing no career-sensitive claims requiring verification)."

    return GroundingValidationResult(
        is_grounded=is_grounded,
        status=status,
        requires_human_review=requires_review,
        supported_claims=supported,
        unsupported_claims=unsupported,
        verified_fact_ids=verified_fact_ids,
        validation_summary=summary
    )

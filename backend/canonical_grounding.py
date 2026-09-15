"""
Canonical Career Grounding & Contextual Claim Validation Engine (CCS v2.1 — Phase 5.2)
Implements authoritative deterministic schema-driven affirmative tuple matching for career-sensitive claims.

SECURITY & INFORMATION-INTEGRITY INVARIANTS:
1. Complete Fact-Tuple Verification: A career claim is grounded ONLY when one authoritative structured
   record affirmatively validates EVERY material dimension (value, precision, metric, outcome, attribution,
   employer/scope, and chronology).
2. Schema-Driven Matcher: No fact is authorized by numeric value alone or absence of forbidden terms.
   All declared required dimensions must be affirmatively satisfied.
3. Separation of Held Titles vs Target Titles: First-person assertions of holding a title validate ONLY
   against HELD_EMPLOYMENT_TITLE or an approved display alias bound to that specific employment record.
   Target role titles (Field CTO, Practice Director, TPM, CEO, VP) never validate as held employment.
4. Employer-Bound Quantitative Facts: If a fact requires an employer (Google, CDW, Promevo, DXC), that
   employer must be affirmatively present. Conflicting or unknown employers (Stripe, Acme, Amazon, Meta) fail closed.
5. Positive Career Assertion Detection & Indeterminate Handling: Text containing likely first-person career
   assertions that cannot be reliably parsed/resolved must return INDETERMINATE/VALIDATION_FAILED (is_grounded=False).
   Only genuine claim-free prose returns NO_CAREER_CLAIMS.
6. Fail-Closed on Malformed Input: Non-string, empty, whitespace, or raw serialized objects fail closed.
7. Zero Transmission Authority: Grounding validation is strictly an information-integrity boundary;
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

# Explicit Title Categorization (Section 6)
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
# Quantitative Canonical Fact Schema & Registry (Sections 7, 8, 9)
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
# Text Extraction & Segmentation Helpers
# ---------------------------------------------------------------------------

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


def get_clause_and_sentence(text: str, start: int, end: int) -> Tuple[str, str]:
    """
    Returns (clause_text, sentence_text) around the given span [start, end].
    Sentence is delimited by '. ' or '.\n' or newline or end of string (ignoring decimal numbers like 2.1).
    Clause is delimited by ';', '\n', bullet points, or conjunctions (' and ', ' including ', ' while ', ' but ').
    """
    # Find sentence start: previous '.' followed by space/newline, or newline
    sent_start = 0
    for m in re.finditer(r'(?:\.\s+|\n+)', text[:start]):
        sent_start = m.end()

    # Find sentence end: next '.' followed by space/newline or end of text, or newline
    sent_end = len(text)
    m = re.search(r'(?:\.\s+|\n+|\.$)', text[end:])
    if m:
        sent_end = end + m.start() + (1 if text[end + m.start()] == '.' else 0)

    sentence = text[sent_start:sent_end].strip()

    # Clause boundaries within sentence
    c_start = sent_start
    clause_delims = [";", "\n", " and ", " including ", " while ", " but ", ", and ", ", but ", "• ", " - "]
    for delim in clause_delims:
        pos = text.rfind(delim, sent_start, start)
        if pos != -1:
            c_start = max(c_start, pos + len(delim))

    c_end = sent_end
    for delim in clause_delims:
        pos = text.find(delim, end, sent_end)
        if pos != -1:
            c_end = min(c_end, pos)

    clause = text[c_start:c_end].strip()
    if not clause:
        clause = sentence
    return clause, sentence


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

    # Pattern 2: X million/billion dollars (without leading $)
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


def is_opportunity_or_target_role_reference(sentence: str, match_text: str = "") -> bool:
    """
    Distinguishes legitimate incoming opportunity or recipient references from
    affirmative first-person claims of past/current employment.
    E.g. 'I am interested in the role at Amazon' -> True (Opportunity reference, not employment assertion)
    E.g. 'During my time at Amazon, I was CTO' -> False (Affirmative employment assertion)
    """
    s_lower = sentence.lower()

    # Affirmative past/current employment markers
    affirmative_employment_markers = [
        "when i was at", "during my time at", "during my tenure at", "during my years at",
        "during my time with", "during my tenure with", "during my years with",
        "my role at", "my position at", "my work as an employee at", "as an employee at",
        "i worked at", "i worked for", "i served at", "i was at", "i have been at",
        "i was chief", "i was vp", "i was vice president", "i was head of", "i was director",
        "former ", "while working at", "while working for", "while employed by", "while employed at",
        "i generated", "i booked", "i closed", "i managed", "i earned", "i led engineering",
        "spent five years", "spent 5 years", "spent several years", "spent 3 years", "spent three years",
        "am employed by", "was employed by", "i joined ", "hired me in", "my employer at the time",
        "my employer was", "formerly worked for", "before joining"
    ]
    if any(m in s_lower for m in affirmative_employment_markers):
        return False

    # Target opportunity reference markers
    opportunity_markers = [
        "regarding the", "regarding your", "reaching out regarding", "thank you for reaching out",
        "interested in the", "excited about the", "discuss the", "discussing the",
        "opportunity at", "opening at", "position at", "role at", "goals at",
        "aligns with", "align with", "suit your schedule", "introductory conversation",
        "role aligns", "opportunity aligns", "position aligns", "forward to speaking"
    ]
    return any(m in s_lower for m in opportunity_markers)


def extract_first_person_employment_claims(text: str) -> List[Dict[str, Any]]:
    """
    Extracts all explicit first-person employment and title assertions from text.
    Handles phrases across all grammatical mutations (worked for, employed by, joined, hired by,
    spent N years at, served as, held role at, employer was, etc.).
    """
    claims = []

    # Pattern 1: 'At/With/For/While at <Company>, I <verb>...'
    p_at = re.compile(
        r'\b(?:at|with|for|while\s+at|while\s+working\s+(?:at|for|with))\s+([A-Za-z0-9\s&.,\'-]+?),\s*(?:i\s+(?:was|worked|served|generated|delivered|managed|earned|led|held|joined|left|built|directed|spearheaded|ran|spent|oversaw)|my\s+role\s+was)\b',
        re.IGNORECASE
    )
    for m in p_at.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause
                })

    # Pattern 2: First-person employment verbs with explicit preposition (worked at/for, employed by, spent N years at, etc.)
    p_emp = re.compile(
        r'\b(?:when i was (?:employed )?at|during my (?:time|tenure|years) (?:at|with)|my (?:role|position|tenure|employment) at|as a[n]? [a-z\s]+ at|while working (?:at|for|with)|while employed (?:by|at|with)|as an employee at|former [a-z\s]+ at|formerly worked for|i\s+(?:worked|work|currently work|have worked|served|was|have been|hold the role of|held the role of|spent\s+\w+\s+years\s+(?:working\s+)?(?:at|for|with)|am employed by|was employed by|led\s+[a-z\s]+\s+while\s+employed\s+by|previously worked for)\s+(?:at|with|for|by|in))\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+as|\s+for|\s+leading|\s+managing|\s+building|\s+developing|\s+in\s+\d{4}|\s+after|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_emp.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if clean_company.lower() in ["the", "a", "an", "this", "that", "all", "our", "my", "your", "their", "many", "several", "various", "multiple", "both"]:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause
                })

    # Pattern 2b: Joined or left employer (e.g. 'I joined Google in 2019', 'I left Microsoft after three years')
    p_join_leave = re.compile(
        r'\bi\s+(?:joined|left)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+in\s+\d{4}|\s+in|\s+after|\s+from|\s+as|\s+where|$)',
        re.IGNORECASE
    )
    for m in p_join_leave.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if clean_company.lower() in ["the", "a", "an", "this", "that", "all", "our", "my", "your", "their", "many", "several", "various", "multiple", "both", "forces", "teams"]:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause
                })

    # Pattern 3: Company hired me / brought me on
    p_hired = re.compile(
        r'\b([A-Za-z0-9\s&.,\'-]+?)\s+(?:hired me|employed me|recruited me|brought me on)\s+(?:in|as|back in|to|for)\b',
        re.IGNORECASE
    )
    for m in p_hired.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause
                })

    # Pattern 4: My employer/company at the time was <Company>
    p_my_emp = re.compile(
        r'\b(?:my\s+(?:employer|company|firm|organization)\s+(?:at the time\s+)?was)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+where|\s+as|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_my_emp.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause
                })

    # Pattern 5: 'Former <Company> <role>' (e.g. 'Former Oracle architect')
    p_former = re.compile(
        r'\bformer\s+([A-Za-z0-9\s&.,\'-]+?)\s+(?:architect|engineer|lead|cto|vp|executive|director|consultant|manager|advisor|employee|specialist|strategist)\b',
        re.IGNORECASE
    )
    for m in p_former.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause
                })

    # Pattern 6: 'Before joining X, I worked for Y'
    p_before_after = re.compile(
        r'\b(?:before|after)\s+(?:joining|leaving)\s+([A-Za-z0-9\s&.,\'-]+?),\s*i\s+(?:worked for|worked at|was at|served at)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|$)',
        re.IGNORECASE
    )
    for m in p_before_after.finditer(text):
        c1 = re.sub(r'[,.]', '', m.group(1)).strip()
        c2 = re.sub(r'[,.]', '', m.group(2)).strip()
        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
        for c in [c1, c2]:
            if len(c) > 1 and len(c.split()) <= 4:
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": c,
                    "claimed_title": None,
                    "sentence": sentence,
                    "clause": clause
                })

    # Pattern 7: 'I served as <Title> at <Company>' / 'I was <Title> at <Company>' / 'As <Title> of/at <Company>'
    p_title_emp = re.compile(
        r'\b(?:i\s+served\s+as|i\s+was|holding\s+the\s+role\s+of|my\s+role\s+as|my\s+role\s+was|my\s+title\s+was|i\s+am(?: the)?|as)\s+([A-Za-z\s&/,—\-]+?)\s+(?:at|with|for|of)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_title_emp.finditer(text):
        title_raw = m.group(1).strip()
        company_raw = m.group(2).strip()
        clean_title = re.sub(r'[,.]', '', title_raw).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()

        if clean_title.lower() in ["a result", "part", "such", "an example", "well as", "soon"]:
            continue

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
        if not is_opportunity_or_target_role_reference(sentence, clean_company):
            claims.append({
                "raw_text": m.group(0),
                "claimed_employer": clean_company,
                "claimed_title": clean_title,
                "sentence": sentence,
                "clause": clause
            })

    # Pattern 8: Standalone first-person title assertions without explicit company
    # (e.g. 'I was Chief Technology Officer', 'My role was Vice President of Engineering', 'I served as Field CTO')
    p_title_standalone = re.compile(
        r'\b(?:i\s+served\s+as|i\s+was|my\s+role\s+was|my\s+title\s+was|holding\s+the\s+role\s+of|i\s+held\s+the\s+title\s+of)\s+(?:a|an|the)?\s*([A-Za-z\s&/,—\-]+?)(?:[.,;:\n]|\s+where|\s+leading|\s+managing|\s+building|\s+developing|\s+and|\s+in\s+my|$)',
        re.IGNORECASE
    )
    for m in p_title_standalone.finditer(text):
        title_raw = m.group(1).strip()
        clean_title = re.sub(r'[,.]', '', title_raw).strip()
        clean_title_lower = clean_title.lower()
        if clean_title_lower in ["a result", "part", "such", "an example", "well as", "responsible", "pleased", "excited", "happy", "thrilled"]:
            continue

        # Check if already captured with company in Pattern 7
        if any(c.get("claimed_title") and clean_title_lower in c["claimed_title"].lower() for c in claims):
            continue

        clause, sentence = get_clause_and_sentence(text, m.start(), m.end())
        if not is_opportunity_or_target_role_reference(sentence, ""):
            claims.append({
                "raw_text": m.group(0),
                "claimed_employer": None,
                "claimed_title": clean_title,
                "sentence": sentence,
                "clause": clause
            })

    return claims


def detect_unparsed_career_assertions(text: str, parsed_claims: List[Dict[str, Any]]) -> List[str]:
    """
    Scans text for conservative first-person career-assertion signals.
    Returns list of unparsed/indeterminate career assertion sentences that could not be verified.
    """
    career_signals = [
        r'\b(?:i\s+(?:worked|work|served|joined|left|led|managed|held|built|am employed|was employed|spent))\b',
        r'\b(?:during my (?:time|tenure|years|role|employment))\b',
        r'\b(?:when i was (?:at|employed|working|leading|managing))\b',
        r'\b(?:while (?:employed|working|leading|managing|spearheading)\s+(?:at|for|by|with|across)?)\b',
        r'\b(?:my (?:employer|role|title|position|tenure|team at))\b',
        r'\b(?:former\s+[a-z\s]+)\b',
        r'\b(?:spent\s+(?:\w+|\d+)\s+years)\b',
        r'\b(?:hired me in|employed me in)\b'
    ]

    unparsed = []
    sentences = [s.strip() for s in re.split(r'[.\n]', text) if s.strip()]
    for sent in sentences:
        if is_opportunity_or_target_role_reference(sent, ""):
            continue

        has_signal = any(re.search(pat, sent, re.IGNORECASE) for pat in career_signals)
        if has_signal:
            # Check if this sentence was successfully matched to an extracted claim
            was_extracted = any(
                c.get("sentence") and (sent in c["sentence"] or c["sentence"] in sent)
                for c in parsed_claims
            )
            if not was_extracted:
                unparsed.append(sent)

    return unparsed


# ---------------------------------------------------------------------------
# Schema-Driven Tuple Matcher (Section 7)
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
    Affirmatively matches an extracted claim against a CanonicalFactDefinition.
    Enforces all configured required dimensions: value, precision, attribution,
    metric, outcome, and employer/scope.
    """
    clause_lower = clause_text.lower()
    sentence_lower = sentence_text.lower()

    # 1. Precision Policy Check
    if fact.precision_policy == PrecisionPolicy.PLUS_REQUIRED and not has_plus:
        return False, ClaimStatus.INSUFFICIENT_PRECISION, f"Claim '{extracted_text}' in '{sentence_text}' lacks required canonical '+' precision (must be '{fact.display_value}')."
    elif fact.precision_policy == PrecisionPolicy.EXACT_REQUIRED and has_plus:
        return False, ClaimStatus.DISALLOWED_QUALIFIER, f"Claim '{extracted_text}' in '{sentence_text}' improperly inflates precision with '+' (must be exact '{fact.display_value}')."

    # 2. Forbidden Attribution Check (within clause)
    if any(fb in clause_lower for fb in fact.forbidden_attribution_aliases):
        matched_fb = next(fb for fb in fact.forbidden_attribution_aliases if fb in clause_lower)
        return False, ClaimStatus.DISALLOWED_QUALIFIER, f"Claim in '{clause_text}' violates attribution standards: disallowed term '{matched_fb}' (authorized: {fact.canonical_text})."

    # 3. Required Attribution Check (Affirmative)
    has_req_attribution = any(req in clause_lower for req in fact.required_attribution_aliases) or any(req in sentence_lower for req in fact.required_attribution_aliases)
    if not has_req_attribution:
        return False, ClaimStatus.UNSUPPORTED, f"Claim in '{sentence_text}' lacks authorized attribution qualifiers for {fact.fact_id}."

    # 4. Forbidden Metric Check (within clause)
    if any(fb in clause_lower for fb in fact.forbidden_metric_aliases):
        matched_fb = next(fb for fb in fact.forbidden_metric_aliases if fb in clause_lower)
        return False, ClaimStatus.MISATTRIBUTED, f"Claim in '{clause_text}' is assigned to unapproved metric '{matched_fb}' (authorized: {fact.canonical_text})."

    # 5. Required Metric Check (Affirmative)
    has_req_metric = any(req in clause_lower for req in fact.required_metric_aliases) or any(req in sentence_lower for req in fact.required_metric_aliases)
    if not has_req_metric:
        return False, ClaimStatus.UNSUPPORTED, f"Claim in '{sentence_text}' lacks required canonical metric keywords for {fact.fact_id}."

    # 6. Scope & Employer Policy Check (Affirmative)
    if fact.scope_policy == ScopePolicy.CAREER_WIDE_REQUIRED:
        if any(conf in clause_lower for conf in fact.conflicting_scope_aliases):
            matched_conf = next(conf for conf in fact.conflicting_scope_aliases if conf in clause_lower)
            return False, ClaimStatus.DISALLOWED_QUALIFIER, f"Claim in '{clause_text}' misattributes career-wide impact ({fact.display_value}) to single employer/scope '{matched_conf}'."

        has_career_scope = any(req in clause_lower for req in fact.required_scope_aliases) or any(req in sentence_lower for req in fact.required_scope_aliases)
        if not has_career_scope:
            return False, ClaimStatus.UNSUPPORTED, f"Claim in '{sentence_text}' lacks required career-wide scope context for {fact.fact_id}."

    elif fact.scope_policy == ScopePolicy.EMPLOYER_BOUND_REQUIRED:
        # 1. Check if clause itself contains an employer
        clause_has_auth = any(alias in clause_lower for alias in fact.allowed_employer_aliases)
        clause_emp_match = re.search(r'\b(?:at|for|while\s+at)\s+([A-Za-z0-9&.,\'-]+)', clause_lower)
        ignore_words = {"the", "our", "a", "an", "all", "my", "your", "shared", "scale", "present", "least", "first", "most", "high", "enterprise", "concept", "production", "work", "time", "clients", "teams"}

        clause_conflicting = [
            emp for emp in ["amazon", "aws", "meta", "microsoft", "apple", "netflix", "oracle", "salesforce", "stripe", "acme", "snowflake", "palantir", "databricks"]
            if emp not in fact.allowed_employer_aliases and emp in clause_lower
        ]

        if clause_emp_match:
            claimed_e = clause_emp_match.group(1).strip().lower()
            if claimed_e and claimed_e not in ignore_words and not any(alias in claimed_e or claimed_e in alias for alias in fact.allowed_employer_aliases):
                return False, ClaimStatus.MISATTRIBUTED, f"Claim in '{clause_text}' misattributes {fact.display_value} to unauthorized employer '{claimed_e}' (authorized: {fact.canonical_text})."

        if clause_conflicting:
            return False, ClaimStatus.MISATTRIBUTED, f"Claim in '{clause_text}' misattributes {fact.display_value} to unauthorized employer '{clause_conflicting[0]}' (authorized: {fact.canonical_text})."

        # If clause explicitly matched an authorized employer, it is validated for employer scope
        if clause_has_auth:
            return True, ClaimStatus.SUPPORTED, f"Verified against canonical fact {fact.fact_id}"

        # 2. If clause did not contain an employer, check sentence context
        sent_emp_match = re.search(r'\b(?:at|for|while\s+at)\s+([A-Za-z0-9&.,\'-]+)', sentence_lower)
        if sent_emp_match:
            claimed_e = sent_emp_match.group(1).strip().lower()
            if claimed_e and claimed_e not in ignore_words and not any(alias in claimed_e or claimed_e in alias for alias in fact.allowed_employer_aliases):
                return False, ClaimStatus.MISATTRIBUTED, f"Claim in '{sentence_text}' misattributes {fact.display_value} to unauthorized employer '{claimed_e}' (authorized: {fact.canonical_text})."

        sent_conflicting = [
            emp for emp in ["amazon", "aws", "meta", "microsoft", "apple", "netflix", "oracle", "salesforce", "stripe", "acme", "snowflake", "palantir", "databricks"]
            if emp not in fact.allowed_employer_aliases and (emp in sentence_lower or f"at {emp}" in sentence_lower or f"for {emp}" in sentence_lower)
        ]
        if sent_conflicting:
            return False, ClaimStatus.MISATTRIBUTED, f"Claim in '{sentence_text}' misattributes {fact.display_value} to unauthorized employer '{sent_conflicting[0]}' (authorized: {fact.canonical_text})."

        sent_has_auth = any(alias in sentence_lower for alias in fact.allowed_employer_aliases)
        if not sent_has_auth:
            return False, ClaimStatus.UNSUPPORTED, f"Claim in '{sentence_text}' omits required canonical employer '{fact.required_employer}' for {fact.fact_id}."

    return True, ClaimStatus.SUPPORTED, f"Verified against canonical fact {fact.fact_id}"


# ---------------------------------------------------------------------------
# General Chronology & Tenure Validator (Section 11)
# ---------------------------------------------------------------------------

def validate_chronology_for_text(text: str) -> List[UnsupportedClaim]:
    """
    Validates employer chronology, start/end dates, and tenure ranges against
    the Authoritative Structured Employment Ledger.
    """
    unsupported = []
    text_lower = text.lower()

    # 1. Google (Oct 2019 - Nov 2021)
    if "google" in text_lower:
        g_invalid_years = [
            r'\b(?:joined|started at|hired by)\s+google\s+(?:in\s+)?20(?:0\d|1[0-8]|2[2-9])\b',
            r'\bgoogle\s+(?:hired|recruited|employed)\s+me\s+(?:in\s+)?20(?:0\d|1[0-8]|2[2-9])\b',
            r'\bworked\s+at\s+google\s+(?:from\s+)?20(?:0\d|1[0-8])\b',
            r'\bgoogle\s+(?:through|until|to)\s+20(?:2[2-9]|3\d)\b',
            r'\b(?:currently\s+(?:work|working|employed)\s+(?:at\s+)?google|worked\s+at\s+google\s+since|employed\s+at\s+google\s+since|at\s+google\s+since)\b',
            r'\bgoogle\s+since\s+20\d\d\b'
        ]
        for pat in g_invalid_years:
            m = re.search(pat, text_lower)
            if m:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.CHRONOLOGY,
                    extracted_text=m.group(0),
                    reason=f"Chronology violation: Google employment tenure was October 2019 to November 2021 (found invalid claim '{m.group(0)}').",
                    status=ClaimStatus.UNSUPPORTED
                ))

    # 2. Promevo (Mar 2026 - Aug 2026)
    if "promevo" in text_lower:
        p_invalid = [
            r'\bcurrently\s+(?:work|working|employed)\s+(?:at\s+)?promevo\b',
            r'\bjoined\s+promevo\s+(?:in\s+)?20(?:1\d|2[0-5]|2[7-9])\b',
            r'\bpromevo\s+from\s+20(?:1\d|2[0-5])\b',
            r'\bworked\s+at\s+promevo\s+from\s+20(?:1\d|2[0-5])\b'
        ]
        for pat in p_invalid:
            m = re.search(pat, text_lower)
            if m:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.CHRONOLOGY,
                    extracted_text=m.group(0),
                    reason=f"Chronology violation: Promevo tenure was March 2026 to August 2026 (ended August 2026). Current role is Strategic Advisor at MavenCode.",
                    status=ClaimStatus.UNSUPPORTED
                ))

    # 3. MavenCode (Sep 2026 - Present active advisory; Oct 2024 - Feb 2026 prior director)
    if "mavencode" in text_lower or "maven code" in text_lower:
        m_invalid = [
            r'\bmavencode\s+tenure\s+ended\s+in\s+2025\b',
            r'\bleft\s+mavencode\s+in\s+2025\b',
            r'\bmavencode\s+from\s+20(?:1\d|2[0-3])\b'
        ]
        for pat in m_invalid:
            m = re.search(pat, text_lower)
            if m:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.CHRONOLOGY,
                    extracted_text=m.group(0),
                    reason=f"Chronology violation: MavenCode current advisory engagement began September 2026 and is active.",
                    status=ClaimStatus.UNSUPPORTED
                ))

    # 4. CDW (Nov 2023 - Oct 2024)
    if "cdw" in text_lower:
        cdw_invalid = [
            r'\bcurrently\s+(?:work|working|employed)\s+(?:at\s+)?cdw\b',
            r'\bjoined\s+cdw\s+(?:in\s+)?20(?:1\d|2[0-2]|2[5-9])\b',
            r'\bcdw\s+from\s+20(?:1\d|2[0-2])\b'
        ]
        for pat in cdw_invalid:
            m = re.search(pat, text_lower)
            if m:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.CHRONOLOGY,
                    extracted_text=m.group(0),
                    reason=f"Chronology violation: CDW tenure was November 2023 to October 2024.",
                    status=ClaimStatus.UNSUPPORTED
                ))

    return unsupported


# ---------------------------------------------------------------------------
# Authoritative Main Grounding Entry Point (CCS v2.1 — Phase 5.2)
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
    # 1. Strict Fail-Closed Input Validation (Section 5)
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
    # 2. Monetary Claims Validation via Common Schema Matcher (Sections 7, 8)
    # -------------------------------------------------------------------------
    monetary_claims = extract_monetary_claims(draft_text)
    for mc in monetary_claims:
        raw_str = mc["raw_text"]
        val = mc["numeric_value"]
        has_plus = mc["has_plus"]
        sentence = mc["sentence"]
        clause = mc["clause"]

        # Find candidate facts matching this numeric value
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

        # Evaluate through common affirmative tuple matcher
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
    # 3. Percentage Claims Validation via Common Schema Matcher (Sections 7, 9)
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
    # 4. First-Person Employment & Title Claims Validation (Sections 5, 6)
    # -------------------------------------------------------------------------
    emp_claims = extract_first_person_employment_claims(draft_text)
    for ec in emp_claims:
        raw_emp = ec.get("claimed_employer")
        claimed_emp = raw_emp.lower() if raw_emp else None
        raw_title = ec.get("claimed_title")
        claimed_title = raw_title.lower() if raw_title else None
        sentence = ec["sentence"]
        raw_match = ec["raw_text"]

        # Case A: Standalone title assertion without explicit company
        if not claimed_emp and claimed_title:
            # Target role titles (Field CTO, Practice Director, TPM, CEO, VP) cannot be claimed as held titles
            if any(target_t in claimed_title or claimed_title in target_t for target_t in TARGET_ROLE_TITLES):
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.TITLE,
                    extracted_text=raw_match,
                    reason=f"Title claim '{raw_title}' in '{sentence}' is a target role or positioning title, not a title held in Brian Kinlaw's employment records.",
                    status=ClaimStatus.UNSUPPORTED
                ))
                continue

            # Verify if title matches any held title across canonical employment records
            matched_held = False
            for rec in CANONICAL_EMPLOYMENT_RECORDS.values():
                if any(ht in claimed_title or claimed_title in ht for ht in rec.held_titles + rec.approved_display_aliases):
                    matched_held = True
                    fact_id = f"FACT_TITLE_{rec.employer_canonical.upper()}"
                    supported.append(SupportedClaim(
                        fact_id=fact_id,
                        category=ClaimCategory.TITLE,
                        extracted_text=raw_match,
                        canonical_reference=f"Authorized title at {rec.employer_canonical}: {raw_title}"
                    ))
                    if fact_id not in verified_fact_ids:
                        verified_fact_ids.append(fact_id)
                    break

            if not matched_held:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.TITLE,
                    extracted_text=raw_match,
                    reason=f"Title claim '{raw_title}' in '{sentence}' is not an authorized held title in Brian Kinlaw's Canonical Career System.",
                    status=ClaimStatus.UNSUPPORTED
                ))
            continue

        # Case B: Employment assertion with claimed employer
        if claimed_emp:
            matched_recs = [
                rdata for rdata in CANONICAL_EMPLOYMENT_RECORDS.values()
                if any(alias in claimed_emp or claimed_emp in alias for alias in rdata.employer_aliases)
            ]

            if not matched_recs:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_match,
                    reason=f"Claim '{raw_match}' asserts employment at '{raw_emp}', which is not in Brian Kinlaw's canonical employment history.",
                    status=ClaimStatus.MISATTRIBUTED
                ))
                continue

            matched_rec = matched_recs[0]

            # If a title was claimed at this canonical employer, verify authorization for that specific employer
            if claimed_title:
                is_auth_for_emp = any(
                    auth_t in claimed_title or claimed_title in auth_t
                    for auth_t in matched_rec.held_titles + matched_rec.approved_display_aliases
                )
                if not is_auth_for_emp:
                    unsupported.append(UnsupportedClaim(
                        category=ClaimCategory.TITLE,
                        extracted_text=raw_match,
                        reason=f"Title claim '{raw_title}' is not authorized for tenure at {matched_rec.employer_canonical}.",
                        status=ClaimStatus.UNSUPPORTED
                    ))
                else:
                    fact_id = f"FACT_EMPLOYMENT_{matched_rec.employer_canonical.upper()}"
                    supported.append(SupportedClaim(
                        fact_id=fact_id,
                        category=ClaimCategory.EMPLOYER,
                        extracted_text=raw_match,
                        canonical_reference=f"{matched_rec.employer_canonical} tenure ({raw_title})"
                    ))
                    if fact_id not in verified_fact_ids:
                        verified_fact_ids.append(fact_id)
            else:
                fact_id = f"FACT_EMPLOYMENT_{matched_rec.employer_canonical.upper()}"
                supported.append(SupportedClaim(
                    fact_id=fact_id,
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_match,
                    canonical_reference=f"{matched_rec.employer_canonical} tenure"
                ))
                if fact_id not in verified_fact_ids:
                    verified_fact_ids.append(fact_id)

    # -------------------------------------------------------------------------
    # 5. Chronology Validation (Section 11)
    # -------------------------------------------------------------------------
    chrono_violations = validate_chronology_for_text(draft_text)
    if chrono_violations:
        unsupported.extend(chrono_violations)

    # -------------------------------------------------------------------------
    # 6. Unparsed Career Assertion Detection (Section 10)
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
    # 7. Synthesize Authoritative Grounding Result (Section 2)
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

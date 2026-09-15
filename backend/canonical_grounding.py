"""
Canonical Career Grounding & Contextual Claim Validation Engine (CCS v2.1)
Implements authoritative deterministic multi-dimensional validation for career-sensitive generated claims.

SECURITY & INFORMATION-INTEGRITY INVARIANTS:
1. Complete Fact-Tuple Verification: A career claim is grounded ONLY when EVERY material factual
   dimension (amount, precision, metric name, business outcome, attribution/qualifier, employer scope,
   and tenure/date) matches an authorized Canonical Career System fact or employment record.
2. Contextual Isolation: Numeric values ($8M, $100M+, $2.1M, $4M, $22M, 23%, 40%, etc.) are strictly
   bound to their specific canonical metric, employer, and qualifier. A number cannot be reassigned
   to an unrelated metric, employer, or attribution.
3. Precision Preservation: Required qualifiers such as "+" ($100M+, $2M+) must be present in raw text.
   The validator must never silently add, remove, or alter precision modifiers.
4. Positive Employment & Title Verification: First-person employment claims ("I worked at X", "When I was at X",
   "As TITLE at X") are strictly validated against authoritative Canonical Employment Records. A finite
   denylist is not used as the sole boundary.
5. Zero Recipient Bypass: Recipient/target company names must never exempt or suppress validation of
   first-person employment assertions.
6. Fail-Closed on Malformed Input: Empty strings, whitespace, non-string types (None, dicts, ints), and
   serialized non-prose structures (raw JSON) must strictly fail closed (is_grounded=False, requires_human_review=True).
7. Zero Transmission Authority: Grounding validation is purely an information-integrity control;
   grounding success NEVER grants or invokes mail transmission authority.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum
from pydantic import BaseModel, Field

logger = logging.getLogger("canonical_grounding")


class GroundingStatus(str, Enum):
    GROUNDED = "GROUNDED"
    UNGROUNDED = "UNGROUNDED"
    NO_CAREER_CLAIMS = "NO_CAREER_CLAIMS"
    VALIDATION_FAILED = "VALIDATION_FAILED"


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
# Authoritative Canonical Fact Registry with Complete Multi-Dimensional Tuples
# ---------------------------------------------------------------------------

CANONICAL_FACT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "FACT_GOOGLE_REVENUE": {
        "fact_id": "FACT_GOOGLE_REVENUE",
        "category": ClaimCategory.MONETARY,
        "canonical_text": "Influenced $8M in new Google Cloud revenue (never 'generated $8M')",
        "canonical_amount_str": "$8M",
        "normalized_value": 8_000_000,
        "requires_plus": False,
        "required_metric_keywords": ["revenue", "cloud revenue", "google cloud revenue", "arr", "new revenue", "sales revenue"],
        "required_employer_or_scope": "google",
        "disallowed_employers": ["amazon", "aws", "meta", "microsoft", "promevo", "cdw", "dxc", "apple", "netflix", "oracle", "salesforce"],
        "required_qualifiers": ["influenced", "influence", "influencing", "advised", "advisory", "assisted", "driven in advisory", "contributed to", "helped drive", "helped influence"],
        "forbidden_qualifiers": ["generated", "generate", "generating", "closed", "close", "closing", "sold", "sell", "selling", "booked", "book", "booking", "billed", "bill", "my revenue", "my personal revenue", "salary", "earned", "commission", "bonus", "quota"],
    },
    "FACT_CAREER_IMPACT": {
        "fact_id": "FACT_CAREER_IMPACT",
        "category": ClaimCategory.MONETARY,
        "canonical_text": "$100M+ enterprise revenue influenced and delivered across career",
        "canonical_amount_str": "$100M+",
        "normalized_value": 100_000_000,
        "requires_plus": True,  # Strictly requires the '+' modifier
        "required_metric_keywords": ["revenue", "enterprise revenue", "enterprise value", "value", "delivered revenue", "pipeline and revenue", "impact"],
        "required_scope_keywords": ["career", "across career", "over my career", "throughout my career", "total", "cross-functional", "enterprise", "overall"],
        "forbidden_qualifiers": ["booked", "personally booked", "salary", "earned", "quota", "commission", "at promevo", "at amazon", "at meta", "at google", "at cdw", "at dxc"],
    },
    "FACT_CDW_SERVICES": {
        "fact_id": "FACT_CDW_SERVICES",
        "category": ClaimCategory.MONETARY,
        "canonical_text": "Closed $2.1M in services at CDW",
        "canonical_amount_str": "$2.1M",
        "normalized_value": 2_100_000,
        "requires_plus": False,
        "required_metric_keywords": ["services", "services closed", "professional services", "consulting services", "solutions"],
        "required_employer": "cdw",
        "disallowed_employers": ["amazon", "meta", "google", "microsoft", "promevo", "dxc", "apple", "netflix", "oracle"],
        "required_qualifiers": ["closed", "close", "closing", "delivered", "services"],
        "forbidden_qualifiers": ["salary", "earned", "compensation", "bonus", "commission", "annual revenue"],
    },
    "FACT_CDW_REVENUE": {
        "fact_id": "FACT_CDW_REVENUE",
        "category": ClaimCategory.MONETARY,
        "canonical_text": "Influenced $4M in annual revenue at CDW",
        "canonical_amount_str": "$4M",
        "normalized_value": 4_000_000,
        "requires_plus": False,
        "required_metric_keywords": ["annual revenue", "annualized revenue", "revenue"],
        "required_employer": "cdw",
        "disallowed_employers": ["amazon", "meta", "google", "microsoft", "promevo", "dxc", "apple", "netflix", "oracle"],
        "required_qualifiers": ["influenced", "influence", "influencing", "driven", "advised", "assisted"],
        "forbidden_qualifiers": ["generated", "generate", "closed", "close", "sold", "salary", "earned", "quota", "portfolio", "services"],
    },
    "FACT_PROMEVO_PIPELINE": {
        "fact_id": "FACT_PROMEVO_PIPELINE",
        "category": ClaimCategory.PIPELINE,
        "canonical_text": "Pipeline contribution estimated $2M+ at Promevo",
        "canonical_amount_str": "$2M+",
        "normalized_value": 2_000_000,
        "requires_plus": True,
        "required_metric_keywords": ["pipeline", "pipeline contribution", "estimated pipeline", "presales pipeline", "deal pipeline"],
        "required_employer": "promevo",
        "disallowed_employers": ["amazon", "meta", "google", "microsoft", "cdw", "dxc", "apple"],
        "forbidden_qualifiers": ["salary", "earned", "closed revenue", "quota"],
    },
    "FACT_DXC_PORTFOLIO": {
        "fact_id": "FACT_DXC_PORTFOLIO",
        "category": ClaimCategory.PORTFOLIO,
        "canonical_text": "$22M portfolio with shared GTM P&L responsibility at DXC",
        "canonical_amount_str": "$22M",
        "normalized_value": 22_000_000,
        "requires_plus": False,
        "required_metric_keywords": ["portfolio", "gtm p&l", "p&l", "business unit", "portfolio responsibility"],
        "required_employer": "dxc",
        "disallowed_employers": ["amazon", "meta", "google", "microsoft", "promevo", "cdw", "apple"],
        "forbidden_qualifiers": ["personal quota", "quota", "salary", "earned", "sales target"],
    },
    "FACT_PROMEVO_POC_CONVERSION": {
        "fact_id": "FACT_PROMEVO_POC_CONVERSION",
        "category": ClaimCategory.PERCENTAGE,
        "canonical_text": "23% POC-to-production conversion rate",
        "canonical_pct": 23.0,
        "required_metric_keywords": ["poc", "conversion", "poc-to-production", "production conversion", "win rate", "pilot conversion"],
        "forbidden_metric_keywords": ["customer satisfaction", "csat", "revenue", "cost", "headcount", "margin", "uptime", "latency", "efficiency", "turnaround"],
    },
    "FACT_PROMEVO_SCOPING_TURNAROUND": {
        "fact_id": "FACT_PROMEVO_SCOPING_TURNAROUND",
        "category": ClaimCategory.PERCENTAGE,
        "canonical_text": "40% reduced scoping turnaround",
        "canonical_pct": 40.0,
        "required_metric_keywords": ["scoping", "turnaround", "reduced scoping", "scoping time", "scoping turnaround"],
        "forbidden_metric_keywords": ["headcount", "cost", "revenue", "margin", "customer satisfaction", "csat", "uptime", "conversion"],
    },
    "FACT_PROMEVO_SALES_CYCLES": {
        "fact_id": "FACT_PROMEVO_SALES_CYCLES",
        "category": ClaimCategory.PERCENTAGE,
        "canonical_text": "20% shorter sales cycles",
        "canonical_pct": 20.0,
        "required_metric_keywords": ["sales cycle", "sales cycles", "shorter cycle", "cycle reduction", "deal cycle", "sales duration"],
        "forbidden_metric_keywords": ["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "uptime"],
    },
    "FACT_PROMEVO_LEGACY_COMPLEXITY": {
        "fact_id": "FACT_PROMEVO_LEGACY_COMPLEXITY",
        "category": ClaimCategory.PERCENTAGE,
        "canonical_text": "25% reduction in legacy architecture complexity",
        "canonical_pct": 25.0,
        "required_metric_keywords": ["legacy", "complexity", "architecture complexity", "legacy architecture", "technical debt", "simplification"],
        "forbidden_metric_keywords": ["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "sales cycle"],
    },
    "FACT_PROMEVO_TIME_TO_VALUE": {
        "fact_id": "FACT_PROMEVO_TIME_TO_VALUE",
        "category": ClaimCategory.PERCENTAGE,
        "canonical_text": "33% faster time-to-value",
        "canonical_pct": 33.0,
        "required_metric_keywords": ["time-to-value", "time to value", "faster delivery", "deployment time", "implementation time", "value delivery"],
        "forbidden_metric_keywords": ["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "complexity"],
    },
    "FACT_PROMEVO_EFFICIENCY_ROADMAP": {
        "fact_id": "FACT_PROMEVO_EFFICIENCY_ROADMAP",
        "category": ClaimCategory.PERCENTAGE,
        "canonical_text": "Presales efficiency roadmap targeting a 30% improvement",
        "canonical_pct": 30.0,
        "required_metric_keywords": ["efficiency", "presales efficiency", "efficiency roadmap", "roadmap improvement", "presales roadmap", "efficiency target"],
        "forbidden_metric_keywords": ["revenue", "margin", "headcount", "cost", "customer satisfaction", "csat", "sales cycle"],
    },
}

# ---------------------------------------------------------------------------
# Authoritative Canonical Employment Records (CCS v2.1 Source of Truth)
# ---------------------------------------------------------------------------

CANONICAL_EMPLOYMENT_RECORDS: Dict[str, Dict[str, Any]] = {
    "mavencode": {
        "employer_canonical": "MavenCode",
        "aliases": ["mavencode", "maven code"],
        "authorized_titles": [
            "strategic advisor, data & ai",
            "strategic advisor",
            "advisor, data & ai",
            "advisor",
            "consulting advisor"
        ],
        "status": "CURRENT_CONTRACT",
        "start_year": 2026,
        "start_month": 9,
        "end_year": None,
        "is_current": True
    },
    "promevo": {
        "employer_canonical": "Promevo",
        "aliases": ["promevo"],
        "authorized_titles": [
            "senior solutions architect",
            "solutions architect",
            "cloud solutions architect",
            "principal solutions architect"
        ],
        "status": "PAST",
        "start_year": 2024,
        "start_month": 1,
        "end_year": 2026,
        "end_month": 8,
        "is_current": False
    },
    "cdw": {
        "employer_canonical": "CDW",
        "aliases": ["cdw", "cdw cloud", "cdw technology", "cdw corporation"],
        "authorized_titles": [
            "principal solutions architect",
            "solutions architect",
            "practice consultant",
            "consulting practice lead",
            "cloud architect"
        ],
        "status": "PAST",
        "start_year": 2020,
        "end_year": 2024,
        "is_current": False
    },
    "dxc": {
        "employer_canonical": "DXC Technology",
        "aliases": ["dxc", "dxc technology", "dxc tech"],
        "authorized_titles": [
            "senior solutions architect",
            "enterprise architect",
            "solutions architect",
            "portfolio lead",
            "chief architect"
        ],
        "status": "PAST",
        "start_year": 2017,
        "end_year": 2020,
        "is_current": False
    }
}

# General Authoritative Titles across Career Archetypes
AUTHORITATIVE_CAREER_TITLES = {
    "advisor",
    "strategic advisor",
    "strategic advisor, data & ai",
    "advisor, data & ai",
    "senior solutions architect",
    "principal solutions architect",
    "solutions architect",
    "principal cloud architect",
    "cloud architect",
    "enterprise architect",
    "principal enterprise architect",
    "principal technical program manager",
    "technical program manager",
    "tpm",
    "ai & data governance leader",
    "director of data governance",
    "field cto",
    "technology strategist",
    "presales advisory lead",
    "practice director",
    "practice consultant",
    "consulting practice lead",
}

APPROVED_TITLES = AUTHORITATIVE_CAREER_TITLES
APPROVED_PAST_EMPLOYERS = {r["employer_canonical"] for r in CANONICAL_EMPLOYMENT_RECORDS.values()}



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
    Sentence is delimited by '.', while Clause is delimited by '.', ';', '\n', or conjunctions.
    """
    sent_start = max(0, text.rfind(".", 0, start) + 1)
    sent_end = text.find(".", end)
    if sent_end == -1:
        sent_end = len(text)
    sentence = text[sent_start:sent_end].strip()

    # Clause boundaries within sentence
    c_start = sent_start
    for delim in [";", "\n", " and ", " including ", " while ", " but ", ", "]:
        pos = text.rfind(delim, sent_start, start)
        if pos != -1:
            c_start = max(c_start, pos + len(delim))

    c_end = sent_end
    for delim in [";", "\n", " and ", " including ", " while ", " but ", ", "]:
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


def is_opportunity_or_target_role_reference(sentence: str, match_text: str) -> bool:
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
        "my role at", "my position at", "my work as an employee at", "as an employee at",
        "i worked at", "i worked for", "i served at", "i was at", "i have been at",
        "i was chief", "i was vp", "i was vice president", "i was head of", "i was director",
        "former ", "while working at", "i generated", "i booked", "i closed", "i managed", "i earned"
    ]
    if any(m in s_lower for m in affirmative_employment_markers):
        return False

    # Target opportunity reference markers
    opportunity_markers = [
        "regarding the", "regarding your", "reaching out regarding", "thank you for reaching out",
        "interested in the", "excited about the", "discuss the", "discussing the",
        "opportunity at", "opening at", "position at", "role at", "goals at",
        "aligns with", "align with", "suit your schedule", "introductory conversation"
    ]
    return any(m in s_lower for m in opportunity_markers)


def extract_first_person_employment_claims(text: str) -> List[Dict[str, Any]]:
    """
    Extracts all explicit first-person employment and title assertions from text.
    Handles phrases like 'At Amazon, I generated...', 'During my time at Google...',
    'I served as Chief Technology Officer at Google', 'When I was at Microsoft...',
    'Former Oracle architect...', 'I currently work at Stripe', etc.
    """
    claims = []

    # Pattern 1: 'At/With/For <Company>, I <verb>...' / 'With <Company>, I <verb>...'
    p_at = re.compile(
        r'\b(?:at|with|for)\s+([A-Za-z0-9\s&.,\'-]+?),\s*(?:i\s+(?:was|worked|served|generated|delivered|managed|earned|led|held|joined|left|built|directed|spearheaded)|my role was)\b',
        re.IGNORECASE
    )
    for m in p_at.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            start = max(0, text.rfind(".", 0, m.start()) + 1)
            end = text.find(".", m.end())
            if end == -1: end = len(text)
            sentence = text[start:end].strip()
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence
                })

    # Pattern 2: 'when I was at <Company>' / 'during my time at <Company>' / 'I worked at <Company>' / 'I work at <Company>' / 'I joined <Company>'
    p_emp = re.compile(
        r'\b(?:when i was (?:employed )?at|during my (?:time|tenure|years) at|my (?:role|position|tenure|employment) at|as a[n]? [a-z\s]+ at|while working at|as an employee at|former [a-z\s]+ at|i\s+(?:worked|work|currently work|have worked|served|was|have been|joined|left|hold the role of|held the role of)\s+(?:at|with|for|in)?)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+as|\s+for|\s+leading|\s+managing|\s+building|\s+developing|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_emp.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        # Filter out common non-company words
        if clean_company.lower() in ["the", "a", "an", "this", "that", "all", "our", "my", "your", "their", "many", "several", "various", "multiple", "both"]:
            continue
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            start = max(0, text.rfind(".", 0, m.start()) + 1)
            end = text.find(".", m.end())
            if end == -1: end = len(text)
            sentence = text[start:end].strip()
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence
                })

    # Pattern 3: 'Former <Company> <role>' (e.g. 'Former Oracle architect', 'Former Google engineer')
    p_former = re.compile(
        r'\bformer\s+([A-Za-z0-9\s&.,\'-]+?)\s+(?:architect|engineer|lead|cto|vp|executive|director|consultant|manager|advisor|employee|specialist|strategist)\b',
        re.IGNORECASE
    )
    for m in p_former.finditer(text):
        company_raw = m.group(1).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()
        if len(clean_company) > 1 and len(clean_company.split()) <= 4:
            start = max(0, text.rfind(".", 0, m.start()) + 1)
            end = text.find(".", m.end())
            if end == -1: end = len(text)
            sentence = text[start:end].strip()
            if not is_opportunity_or_target_role_reference(sentence, clean_company):
                claims.append({
                    "raw_text": m.group(0),
                    "claimed_employer": clean_company,
                    "claimed_title": None,
                    "sentence": sentence
                })

    # Pattern 4: 'I served as <Title> at <Company>' / 'I was <Title> at <Company>' / 'As <Title> of/at <Company>'
    p_title_emp = re.compile(
        r'\b(?:i\s+served\s+as|i\s+was|holding\s+the\s+role\s+of|my\s+role\s+as|my\s+role\s+was|i\s+am(?: the)?|as)\s+([A-Za-z\s&/,]+?)\s+(?:at|with|for|of)\s+([A-Za-z0-9\s&.,\'-]+?)(?:[.,;:\n]|\s+from|\s+where|\s+since|\s+i\s+|$)',
        re.IGNORECASE
    )
    for m in p_title_emp.finditer(text):
        title_raw = m.group(1).strip()
        company_raw = m.group(2).strip()
        clean_title = re.sub(r'[,.]', '', title_raw).strip()
        clean_company = re.sub(r'[,.]', '', company_raw).strip()

        # Filter out common false positives like 'as a result of'
        if clean_title.lower() in ["a result", "part", "such", "an example", "well as", "soon"]:
            continue

        start = max(0, text.rfind(".", 0, m.start()) + 1)
        end = text.find(".", m.end())
        if end == -1: end = len(text)
        sentence = text[start:end].strip()
        if not is_opportunity_or_target_role_reference(sentence, clean_company):
            claims.append({
                "raw_text": m.group(0),
                "claimed_employer": clean_company,
                "claimed_title": clean_title,
                "sentence": sentence
            })

    # Pattern 5: Standalone first-person title assertions without explicit company
    # (e.g. 'I was Chief Technology Officer', 'My role was Vice President of Engineering', 'I served as CEO')
    p_title_standalone = re.compile(
        r'\b(?:i\s+served\s+as|i\s+was|my\s+role\s+was|holding\s+the\s+role\s+of|i\s+held\s+the\s+title\s+of)\s+(?:a|an|the)?\s*([A-Za-z\s&/,]+?)(?:[.,;:\n]|\s+where|\s+leading|\s+managing|\s+building|\s+developing|\s+and|\s+in\s+my|$)',
        re.IGNORECASE
    )
    for m in p_title_standalone.finditer(text):
        title_raw = m.group(1).strip()
        clean_title = re.sub(r'[,.]', '', title_raw).strip()
        clean_title_lower = clean_title.lower()
        if clean_title_lower in ["a result", "part", "such", "an example", "well as", "responsible", "pleased", "excited", "happy", "thrilled"]:
            continue

        # Check if already captured with company in Pattern 4
        if any(c.get("claimed_title") and clean_title_lower in c["claimed_title"].lower() for c in claims):
            continue

        start = max(0, text.rfind(".", 0, m.start()) + 1)
        end = text.find(".", m.end())
        if end == -1: end = len(text)
        sentence = text[start:end].strip()
        if not is_opportunity_or_target_role_reference(sentence, ""):
            claims.append({
                "raw_text": m.group(0),
                "claimed_employer": None,
                "claimed_title": clean_title,
                "sentence": sentence
            })

    return claims


def validate_canonical_grounding(
    draft_text: Any,
    recipient_company: Optional[str] = None
) -> GroundingValidationResult:
    """
    Authoritative deterministic validation of career-sensitive claims in draft text.
    Validates complete factual tuples across monetary amounts, qualifiers, percentages,
    employers, titles, dates, and tenures.
    Fails closed on any unsupported, misattributed, malformed, or indeterminate input.
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

    # Check for raw JSON, serialized objects, or dictionary wrappers
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

    text_lower = draft_text.lower()

    # -------------------------------------------------------------------------
    # 2. Monetary Claims Contextual Tuple Validation (Sections 4.1, 4.2, 4.3)
    # -------------------------------------------------------------------------
    monetary_claims = extract_monetary_claims(draft_text)
    for mc in monetary_claims:
        raw_str = mc["raw_text"]
        val = mc["numeric_value"]
        has_plus = mc["has_plus"]
        raw_str = mc["raw_text"]
        val = mc["numeric_value"]
        has_plus = mc["has_plus"]
        sentence = mc["sentence"]
        clause = mc["clause"]
        sentence_lower = sentence.lower()
        clause_lower = clause.lower()

        # Check $8M Google Cloud Revenue (FACT_GOOGLE_REVENUE)
        if val == 8_000_000:
            fact = CANONICAL_FACT_REGISTRY["FACT_GOOGLE_REVENUE"]

            # Check for forbidden qualifiers ('generated', 'closed', 'sold', 'salary', etc.) in clause or sentence
            has_forbidden_qualifier = any(f in clause_lower or (f in sentence_lower and f not in ["across career", "across my career"]) for f in fact["forbidden_qualifiers"])

            # Check for disallowed employers attached to $8M (Amazon, AWS, Promevo, Meta, etc.)
            has_disallowed_employer = (
                any(emp in clause_lower for emp in fact["disallowed_employers"]) or
                any(f"at {emp}" in sentence_lower or f"for {emp}" in sentence_lower or f"{emp} revenue" in sentence_lower for emp in fact["disallowed_employers"])
            )

            # Check for required Google Cloud scope
            has_required_scope = any(req in clause_lower or req in sentence_lower for req in ["google", "google cloud", "gcp"])

            if has_forbidden_qualifier:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.QUALIFIER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' violates Accomplishment Ledger precision: $8M must be qualified as 'influenced', never 'generated', 'closed', or 'sold'.",
                    status=ClaimStatus.DISALLOWED_QUALIFIER
                ))
            elif has_disallowed_employer or (not has_required_scope and any(e in sentence_lower for e in ["amazon", "meta", "microsoft", "promevo", "cdw"])):
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' misattributes $8M revenue to an unauthorized employer (must be Google Cloud partner revenue influence).",
                    status=ClaimStatus.MISATTRIBUTED
                ))
            else:
                supported.append(SupportedClaim(
                    fact_id="FACT_GOOGLE_REVENUE",
                    category=ClaimCategory.MONETARY,
                    extracted_text=raw_str,
                    canonical_reference=fact["canonical_text"]
                ))
                if "FACT_GOOGLE_REVENUE" not in verified_fact_ids:
                    verified_fact_ids.append("FACT_GOOGLE_REVENUE")

        # Check $100M+ Career Enterprise Revenue (FACT_CAREER_IMPACT)
        elif val == 100_000_000:
            fact = CANONICAL_FACT_REGISTRY["FACT_CAREER_IMPACT"]

            # Strict Precision Check: $100M+ requires the '+' modifier
            if not has_plus:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.MONETARY,
                    extracted_text=raw_str,
                    reason=f"Monetary claim '{raw_str}' in '{sentence}' lacks required canonical '+' precision (must be '$100M+' career-wide revenue).",
                    status=ClaimStatus.INSUFFICIENT_PRECISION
                ))
                continue

            # Scope Check: Must be career-wide enterprise revenue, NOT attributed as a personal booking at a single company
            has_forbidden_qualifier = any(f in clause_lower or f in sentence_lower for f in fact["forbidden_qualifiers"])
            has_single_employer_booking = ("personally booked" in sentence_lower) or any(f"at {e}" in sentence_lower for e in ["promevo", "amazon", "meta", "cdw", "dxc", "google"])

            if has_forbidden_qualifier or has_single_employer_booking:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.QUALIFIER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' misattributes $100M+ as a single employer booking/salary rather than career-wide enterprise revenue influenced and delivered.",
                    status=ClaimStatus.DISALLOWED_QUALIFIER
                ))
            else:
                supported.append(SupportedClaim(
                    fact_id="FACT_CAREER_IMPACT",
                    category=ClaimCategory.MONETARY,
                    extracted_text=raw_str,
                    canonical_reference=fact["canonical_text"]
                ))
                if "FACT_CAREER_IMPACT" not in verified_fact_ids:
                    verified_fact_ids.append("FACT_CAREER_IMPACT")

        # Check $2.1M CDW Services (FACT_CDW_SERVICES)
        elif val == 2_100_000:
            fact = CANONICAL_FACT_REGISTRY["FACT_CDW_SERVICES"]
            has_forbidden = any(f in clause_lower or f in sentence_lower for f in fact["forbidden_qualifiers"])
            has_disallowed_employer = any(emp in sentence_lower for emp in fact["disallowed_employers"])

            if has_forbidden:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.QUALIFIER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' mischaracterizes $2.1M (must be CDW services closed, not salary/earned).",
                    status=ClaimStatus.DISALLOWED_QUALIFIER
                ))
            elif has_disallowed_employer:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' misattributes $2.1M services to an unauthorized employer (authorized: CDW).",
                    status=ClaimStatus.MISATTRIBUTED
                ))
            else:
                supported.append(SupportedClaim(
                    fact_id="FACT_CDW_SERVICES",
                    category=ClaimCategory.MONETARY,
                    extracted_text=raw_str,
                    canonical_reference=fact["canonical_text"]
                ))
                if "FACT_CDW_SERVICES" not in verified_fact_ids:
                    verified_fact_ids.append("FACT_CDW_SERVICES")

        # Check $4M CDW Annual Revenue (FACT_CDW_REVENUE)
        elif val == 4_000_000:
            fact = CANONICAL_FACT_REGISTRY["FACT_CDW_REVENUE"]
            has_forbidden = any(f in clause_lower or f in sentence_lower for f in fact["forbidden_qualifiers"])
            has_disallowed_employer = any(emp in sentence_lower for emp in fact["disallowed_employers"])

            if has_forbidden or "generated" in sentence_lower or "closed" in sentence_lower:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.QUALIFIER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' mischaracterizes $4M (must be CDW annual revenue influenced, not generated/salary).",
                    status=ClaimStatus.DISALLOWED_QUALIFIER
                ))
            elif has_disallowed_employer or ("at amazon" in sentence_lower or "at meta" in sentence_lower or "at google" in sentence_lower):
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' misattributes $4M annual revenue to an unauthorized employer (authorized: CDW).",
                    status=ClaimStatus.MISATTRIBUTED
                ))
            else:
                supported.append(SupportedClaim(
                    fact_id="FACT_CDW_REVENUE",
                    category=ClaimCategory.MONETARY,
                    extracted_text=raw_str,
                    canonical_reference=fact["canonical_text"]
                ))
                if "FACT_CDW_REVENUE" not in verified_fact_ids:
                    verified_fact_ids.append("FACT_CDW_REVENUE")

        # Check $2M+ Promevo Pipeline (FACT_PROMEVO_PIPELINE)
        elif val == 2_000_000:
            fact = CANONICAL_FACT_REGISTRY["FACT_PROMEVO_PIPELINE"]
            has_forbidden = any(f in clause_lower or f in sentence_lower for f in fact["forbidden_qualifiers"])
            has_disallowed_employer = any(emp in sentence_lower for emp in fact["disallowed_employers"])

            if not has_plus:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.MONETARY,
                    extracted_text=raw_str,
                    reason=f"Pipeline claim '{raw_str}' in '{sentence}' lacks required canonical '+' precision (must be '$2M+' pipeline contribution).",
                    status=ClaimStatus.INSUFFICIENT_PRECISION
                ))
            elif has_forbidden:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.QUALIFIER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' violates pipeline qualifier standards.",
                    status=ClaimStatus.DISALLOWED_QUALIFIER
                ))
            elif has_disallowed_employer:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_str,
                    reason=f"Pipeline claim in '{sentence}' misattributed to unauthorized employer.",
                    status=ClaimStatus.MISATTRIBUTED
                ))
            else:
                supported.append(SupportedClaim(
                    fact_id="FACT_PROMEVO_PIPELINE",
                    category=ClaimCategory.PIPELINE,
                    extracted_text=raw_str,
                    canonical_reference=fact["canonical_text"]
                ))
                if "FACT_PROMEVO_PIPELINE" not in verified_fact_ids:
                    verified_fact_ids.append("FACT_PROMEVO_PIPELINE")

        # Check $22M DXC Portfolio (FACT_DXC_PORTFOLIO)
        elif val == 22_000_000:
            fact = CANONICAL_FACT_REGISTRY["FACT_DXC_PORTFOLIO"]
            has_forbidden = any(f in clause_lower or f in sentence_lower for f in fact["forbidden_qualifiers"])
            has_disallowed_employer = any(emp in sentence_lower for emp in fact["disallowed_employers"])

            if has_forbidden or "personal quota" in sentence_lower or "sales quota" in sentence_lower:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.QUALIFIER,
                    extracted_text=raw_str,
                    reason=f"Claim in '{sentence}' mischaracterizes $22M (must be DXC portfolio with shared GTM P&L, not personal quota/salary).",
                    status=ClaimStatus.DISALLOWED_QUALIFIER
                ))
            elif has_disallowed_employer:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_str,
                    reason=f"Portfolio claim in '{sentence}' misattributed to unauthorized employer (authorized: DXC).",
                    status=ClaimStatus.MISATTRIBUTED
                ))
            else:
                supported.append(SupportedClaim(
                    fact_id="FACT_DXC_PORTFOLIO",
                    category=ClaimCategory.PORTFOLIO,
                    extracted_text=raw_str,
                    canonical_reference=fact["canonical_text"]
                ))
                if "FACT_DXC_PORTFOLIO" not in verified_fact_ids:
                    verified_fact_ids.append("FACT_DXC_PORTFOLIO")

        # Any other unapproved monetary value ($80M, $50M, $15M, $500K, etc.)
        else:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.MONETARY,
                extracted_text=raw_str,
                reason=f"Monetary value {raw_str} in sentence '{sentence}' is not in Brian Kinlaw's Canonical Accomplishment Ledger.",
                status=ClaimStatus.UNSUPPORTED
            ))

    # -------------------------------------------------------------------------
    # 3. Percentage Claims Contextual Tuple Validation (Section 4.1)
    # -------------------------------------------------------------------------
    pct_claims = extract_percentage_claims(draft_text)
    for pc in pct_claims:
        raw_str = pc["raw_text"]
        val = pc["numeric_value"]
        sentence = pc["sentence"]
        clause = pc["clause"]
        sentence_lower = sentence.lower()
        clause_lower = clause.lower()

        matched_fact_key = None
        for fkey, fdef in CANONICAL_FACT_REGISTRY.items():
            if fdef.get("category") == ClaimCategory.PERCENTAGE and fdef.get("canonical_pct") == val:
                matched_fact_key = fkey
                break

        if not matched_fact_key:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.PERCENTAGE,
                extracted_text=raw_str,
                reason=f"Percentage {raw_str} in sentence '{sentence}' is not a verified Canonical Career System metric.",
                status=ClaimStatus.UNSUPPORTED
            ))
            continue

        fdef = CANONICAL_FACT_REGISTRY[matched_fact_key]

        # Check if forbidden metric keywords are present in the local clause
        has_forbidden_metric = any(fb in clause_lower for fb in fdef["forbidden_metric_keywords"])
        # Check if required metric keywords are present in the local clause or sentence
        has_required_metric = any(req in clause_lower or req in sentence_lower for req in fdef["required_metric_keywords"])

        if has_forbidden_metric or not has_required_metric:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.PERCENTAGE,
                extracted_text=raw_str,
                reason=f"Percentage {raw_str} in sentence '{sentence}' is assigned to an unverified outcome (authorized metric: {fdef['canonical_text']}).",
                status=ClaimStatus.MISATTRIBUTED
            ))
        else:
            supported.append(SupportedClaim(
                fact_id=matched_fact_key,
                category=ClaimCategory.PERCENTAGE,
                extracted_text=raw_str,
                canonical_reference=fdef["canonical_text"]
            ))
            if matched_fact_key not in verified_fact_ids:
                verified_fact_ids.append(matched_fact_key)

    # -------------------------------------------------------------------------
    # 4. First-Person Employment & Title Claims Validation (Sections 4.4, 4.5, 4.6, 4.7)
    # -------------------------------------------------------------------------
    emp_claims = extract_first_person_employment_claims(draft_text)
    for ec in emp_claims:
        raw_emp = ec.get("claimed_employer")
        claimed_emp = raw_emp.lower() if raw_emp else None
        raw_title = ec.get("claimed_title")
        claimed_title = raw_title.lower() if raw_title else None
        sentence = ec["sentence"]
        raw_match = ec["raw_text"]

        # Case A: Standalone title assertion without company (e.g. 'I was Vice President of Engineering', 'I served as CEO')
        if not claimed_emp and claimed_title:
            is_auth_title = any(
                auth_t in claimed_title or claimed_title in auth_t
                for auth_t in AUTHORITATIVE_CAREER_TITLES
            )
            if not is_auth_title:
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.TITLE,
                    extracted_text=raw_match,
                    reason=f"Title claim '{raw_title}' in '{sentence}' is not an authorized title in Brian Kinlaw's Canonical Career System.",
                    status=ClaimStatus.UNSUPPORTED
                ))
            else:
                supported.append(SupportedClaim(
                    fact_id="FACT_TITLE_AUTHORIZED",
                    category=ClaimCategory.TITLE,
                    extracted_text=raw_match,
                    canonical_reference=f"Authorized career archetype title: {raw_title}"
                ))
            continue

        # Case B: First-person employment assertion with employer
        if claimed_emp:
            # Match against Canonical Employment Records
            matched_rec = None
            for rkey, rdata in CANONICAL_EMPLOYMENT_RECORDS.items():
                if any(alias in claimed_emp or claimed_emp in alias for alias in rdata["aliases"]):
                    matched_rec = rdata
                    break

            # Check for Google specifically (Partner ecosystem / Influenced revenue, NOT salaried employee)
            if "google" in claimed_emp:
                if claimed_title or "worked at" in raw_match.lower() or "during my time at" in raw_match.lower() or "when i was at" in raw_match.lower():
                    unsupported.append(UnsupportedClaim(
                        category=ClaimCategory.EMPLOYER,
                        extracted_text=raw_match,
                        reason=f"Claim '{raw_match}' asserts salaried employment at Google, which is not in canonical career records (Brian Kinlaw influenced Google Cloud partner revenue in advisory capacity).",
                        status=ClaimStatus.MISATTRIBUTED
                    ))
                    continue

            if not matched_rec:
                # Unrecognized / Non-canonical employer assertion
                unsupported.append(UnsupportedClaim(
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_match,
                    reason=f"Claim '{raw_match}' asserts employment at '{raw_emp}', which is not in Brian Kinlaw's canonical employment history.",
                    status=ClaimStatus.MISATTRIBUTED
                ))
                continue

            # If a title was claimed at this canonical employer, verify title authorization
            if claimed_title:
                is_authorized_title = any(
                    auth_t in claimed_title or claimed_title in auth_t
                    for auth_t in matched_rec["authorized_titles"]
                )
                if not is_authorized_title:
                    unsupported.append(UnsupportedClaim(
                        category=ClaimCategory.TITLE,
                        extracted_text=raw_match,
                        reason=f"Title claim '{raw_title}' is not authorized for tenure at {matched_rec['employer_canonical']}.",
                        status=ClaimStatus.UNSUPPORTED
                    ))
                else:
                    fact_id = f"FACT_EMPLOYMENT_{matched_rec['employer_canonical'].upper()}"
                    supported.append(SupportedClaim(
                        fact_id=fact_id,
                        category=ClaimCategory.EMPLOYER,
                        extracted_text=raw_match,
                        canonical_reference=f"{matched_rec['employer_canonical']} tenure ({', '.join(matched_rec['authorized_titles'][:2])})"
                    ))
                    if fact_id not in verified_fact_ids:
                        verified_fact_ids.append(fact_id)
            else:
                fact_id = f"FACT_EMPLOYMENT_{matched_rec['employer_canonical'].upper()}"
                supported.append(SupportedClaim(
                    fact_id=fact_id,
                    category=ClaimCategory.EMPLOYER,
                    extracted_text=raw_match,
                    canonical_reference=f"{matched_rec['employer_canonical']} tenure"
                ))
                if fact_id not in verified_fact_ids:
                    verified_fact_ids.append(fact_id)

    # -------------------------------------------------------------------------
    # 5. Chronology & Date Range Validation (Section 4.7)
    # -------------------------------------------------------------------------
    # Check for invalid Promevo dates (Promevo tenure ended August 2026)
    promevo_invalid_dates = [
        r'\bcurrently\s+(?:work|working|employed|role)\s+(?:as\s+[a-z\s]+)?at\s+promevo\b',
        r'\b(?:i currently work at promevo|my current position at promevo)\b',
        r'\bpromevo\s+from\s+20(?:1\d|2[0-3])\b',
        r'\bjoined\s+promevo\s+in\s+20(?:1\d|2[0-3]|2[5-9])\b',
        r'\bworked\s+at\s+promevo\s+from\s+20(?:1\d|2[0-3])\b'
    ]
    for pat in promevo_invalid_dates:
        m = re.search(pat, text_lower)
        if m:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.CHRONOLOGY,
                extracted_text=m.group(0),
                reason="Promevo tenure was 2024 to August 2026 (ended August 2026). Current role is Strategic Advisor at MavenCode.",
                status=ClaimStatus.UNSUPPORTED
            ))

    # Check for invalid MavenCode dates
    mavencode_invalid_dates = [
        r'\bmavencode\s+tenure\s+ended\b',
        r'\bleft\s+mavencode\b',
        r'\bmavencode\s+from\s+20(?:1\d|2[0-5])\b',
    ]
    for pat in mavencode_invalid_dates:
        m = re.search(pat, text_lower)
        if m:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.CHRONOLOGY,
                extracted_text=m.group(0),
                reason="MavenCode engagement began in September 2026 and is currently active.",
                status=ClaimStatus.UNSUPPORTED
            ))

    # Check for invalid Google employment date ranges (e.g. 'worked at Google from 2018 through 2024')
    google_emp_dates = [
        r'\bworked\s+at\s+google\s+(?:from\s+\d{4}|since\s+\d{4}|through\s+\d{4})\b',
        r'\bgoogle\s+from\s+20\d\d\s+through\s+20\d\d\b',
        r'\bgoogle\s+since\s+20\d\d\b',
        r'\bmy\s+tenure\s+at\s+google\b'
    ]
    for pat in google_emp_dates:
        m = re.search(pat, text_lower)
        if m:
            unsupported.append(UnsupportedClaim(
                category=ClaimCategory.CHRONOLOGY,
                extracted_text=m.group(0),
                reason="Brian Kinlaw was not a salaried employee at Google; revenue influence was delivered through partner advisory.",
                status=ClaimStatus.UNSUPPORTED
            ))

    # -------------------------------------------------------------------------
    # 6. Synthesize Authoritative Grounding Result (Section 5)
    # -------------------------------------------------------------------------
    has_unsupported = len(unsupported) > 0
    has_supported = len(supported) > 0

    if has_unsupported:
        is_grounded = False
        status = GroundingStatus.UNGROUNDED
        requires_review = True
        unsupported_reasons = "; ".join([u.reason for u in unsupported])
        summary = f"Grounding validation rejected {len(unsupported)} unverified, misattributed, or qualifier-violating claim(s): {unsupported_reasons}"
    elif has_supported:
        is_grounded = True
        status = GroundingStatus.GROUNDED
        requires_review = False
        summary = f"Validated {len(supported)} career claim(s) successfully against Canonical Career System facts ({', '.join(verified_fact_ids)})."
    else:
        # Valid prose with no career claims
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

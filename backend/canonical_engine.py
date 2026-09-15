"""
Canonical Resume Engine
Indexes, parses, and matches Brian Kinlaw's Canonical Career System across:
1. Canonical - Active (Level 1 Ledger & Level 3 Standard Archetypes)
2. Targeted Applications (Custom tailored resumes for specific roles/companies)
3. Downloads / Resume Variants (Expanded PDF, Field CTO, Presales Advisory)
"""

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from backend.config import RESUMES_DIR
from backend.canonical_grounding import (
    CANONICAL_FACT_REGISTRY,
    validate_canonical_grounding,
    GroundingValidationResult,
    SupportedClaim,
    UnsupportedClaim,
    ClaimCategory,
    ClaimStatus
)

logger = logging.getLogger("canonical_engine")

# Canonical System Paths (pointing directly to CCS v2.1 repository with fallback)
CANONICAL_ACTIVE_DIR = Path(os.getenv("CANONICAL_ACTIVE_DIR", "/Users/briankinlaw/CCS-v211-upload/Canonical – Active"))
TARGETED_APPS_DIR = Path(os.getenv("TARGETED_APPS_DIR", "/Users/briankinlaw/CCS-v211-upload/Targeted Applications"))
DOWNLOADS_VARIANTS_DIR = Path(os.getenv("DOWNLOADS_VARIANTS_DIR", "/Users/briankinlaw/Downloads/Resume Variants"))


# Lens Archetype Definitions
LENS_DEFINITIONS = {
    "level_3a_advisor": {
        "id": "level_3a_advisor",
        "name": "Level 3A — Advisor / Principal Solutions Architect",
        "badge": "Advisor (Level 3A)",
        "color": "#3b82f6",
        "description": "Pre-sales, enterprise architecture, discovery, executive advisory, GTM strategy",
        "keywords": ["advisor", "solutions architect", "enterprise architect", "presales", "pre-sales", "gtm", "solution architect", "principal architect", "cloud architect", "consulting architect"]
    },
    "level_3b_tpm": {
        "id": "level_3b_tpm",
        "name": "Level 3B — Principal Technical Program Manager",
        "badge": "TPM (Level 3B)",
        "color": "#8b5cf6",
        "description": "Cross-functional orchestration, multi-cloud roadmaps, delivery governance, PMP execution",
        "keywords": ["tpm", "program manager", "technical program manager", "pmp", "project manager", "delivery", "orchestration", "roadmap", "program leadership"]
    },
    "level_3c_governance": {
        "id": "level_3c_governance",
        "name": "Level 3C — AI Governance & Enterprise Data Leader",
        "badge": "AI & Data Governance (Level 3C)",
        "color": "#10b981",
        "description": "Data quality, metadata, lineage, stewardship, MDM, NIST AI RMF, compliance",
        "keywords": ["governance", "data governance", "ai governance", "metadata", "collibra", "lineage", "nist", "compliance", "data management", "mdm", "stewardship", "model governance"]
    },
    "field_cto": {
        "id": "field_cto",
        "name": "Field CTO / Technology Strategist",
        "badge": "Field CTO / Strategist",
        "color": "#ec4899",
        "description": "Executive advisory, platform strategy, customer transformation, C-suite alignment",
        "keywords": ["field cto", "cto", "chief technology", "technology strategist", "executive advisor", "strategy director", "practice director"]
    },
    "data_platform_ai": {
        "id": "data_platform_ai",
        "name": "Principal Data Platform & AI Architect",
        "badge": "Data & Agentic AI Architect",
        "color": "#f59e0b",
        "description": "Modern Data Lakehouse, Agentic AI, Google Cloud / BigQuery, Databricks, GenAI systems",
        "keywords": ["data platform", "lakehouse", "agentic ai", "genai", "generative ai", "ai systems", "bigquery", "databricks", "gcp data", "data architect", "ai architect"]
    },
    "presales_lead": {
        "id": "presales_lead",
        "name": "Presales Advisory Lead / Practice Director",
        "badge": "Presales Advisory Lead",
        "color": "#06b6d4",
        "description": "Pre-sales leadership, technical discovery, proposal architecture, POC to production",
        "keywords": ["presales lead", "presales advisory", "sales engineering", "practice director", "practice leader", "solution engineering"]
    }
}

# Locked Metrics and Career Facts from Canonical Ledger with Stable Fact IDs
LOCKED_FACTS = {
    "FACT_GOOGLE_REVENUE": "Influenced $8M in new Google Cloud revenue (never 'generated $8M')",
    "FACT_CDW_REVENUE": "Closed $2.1M in services; Influenced $4M in annual revenue",
    "FACT_PROMEVO_PIPELINE": "Pipeline contribution estimated $2M+; Presales efficiency roadmap targeting a 30% improvement",
    "FACT_PROMEVO_RESULTS": "23% POC-to-production conversion, 40% reduced scoping turnaround, 20% shorter sales cycles, 25% reduction in legacy architecture complexity, 33% faster time-to-value",
    "FACT_DXC_PORTFOLIO": "$22M portfolio with shared GTM P&L responsibility between OCTO and LOB Sales",
    "FACT_CAREER_IMPACT": "$100M+ enterprise revenue influenced and delivered across career",
    "FACT_CERTIFICATIONS": ["PMP (Project Management Professional)", "Google Cloud Certified Professional Cloud Architect", "Google Cloud Certified Professional Data Engineer"],
    "FACT_EMPLOYMENT_MAVENCODE": "Strategic Advisor, Data & AI (Contract) at MavenCode (Sep 2026-Present)",
    "FACT_EMPLOYMENT_PROMEVO": "Senior Solutions Architect at Promevo (2024 - Aug 2026; ended August 2026)",
    "google": "Influenced $8M in new Google Cloud revenue (never 'generated $8M')",
    "cdw": "Closed $2.1M in services; Influenced $4M in annual revenue",
    "promevo_pipeline": "Pipeline contribution estimated $2M+; Presales efficiency roadmap targeting a 30% improvement",
    "promevo_results": "23% POC-to-production conversion, 40% reduced scoping turnaround, 20% shorter sales cycles, 25% reduction in legacy architecture complexity, 33% faster time-to-value",
    "dxc": "$22M portfolio with shared GTM P&L responsibility between OCTO and LOB Sales",
    "career_impact": "$100M+ enterprise revenue influenced and delivered",
    "certifications": ["PMP (Project Management Professional)", "Google Cloud Certified Professional Cloud Architect", "Google Cloud Certified Professional Data Engineer"],
    "current_status": "Strategic Advisor, Data & AI (Contract) at MavenCode (Sep 2026-Present)"
}

def resolve_resume_file(identifier: Optional[str]) -> Optional[Path]:
    """Finds the absolute path of a resume given an absolute path, filename, or stem."""
    search_dirs = [CANONICAL_ACTIVE_DIR, TARGETED_APPS_DIR, DOWNLOADS_VARIANTS_DIR, RESUMES_DIR]
    
    if not identifier:
        # Default to level 3A advisor canonical if available
        for d in search_dirs:
            if d.exists():
                adv = list(d.glob("*Advisor_Canonical*.docx")) + list(d.glob("*.docx"))
                if adv:
                    return adv[0]
        return None

    path_obj = Path(identifier)
    if path_obj.is_absolute() and path_obj.exists():
        return path_obj

    clean_name = path_obj.name.lower()

    for d in search_dirs:
        if not d.exists():
            continue
        # Direct exact match
        direct = d / path_obj.name
        if direct.exists():
            return direct
        # Case-insensitive match
        for f in d.glob("*"):
            if f.is_file() and f.name.lower() == clean_name:
                return f
    return None

_RESUME_CACHE: Dict[str, Any] = {}
_LAST_SCAN_TIME: Optional[float] = None

def extract_docx_text(path: Path) -> str:
    """Extract plain text from a docx file using standard library zipfile and xml parsing."""
    try:
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" not in z.namelist():
                return ""
            tree = ET.fromstring(z.read("word/document.xml"))
            namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for p in tree.iterfind(".//w:p", namespaces):
                p_text = "".join([node.text for node in p.iterfind(".//w:t", namespaces) if node.text])
                if p_text:
                    paragraphs.append(p_text.strip())
            return "\n".join(paragraphs)
    except Exception as e:
        logger.warning(f"Failed to read docx {path}: {e}")
        return ""


def determine_lens_from_content(filename: str, text: str) -> str:
    """Determine the role lens archetype based on filename and extracted document text."""
    fname_lower = filename.lower()
    text_lower = text.lower()[:2000]  # Focus on top header / summary

    if "governance" in fname_lower or "compliance" in fname_lower or "model_gov" in fname_lower or "data_gov" in fname_lower:
        return "level_3c_governance"
    elif "tpm" in fname_lower or "denodo" in fname_lower or "pmp" in fname_lower or "program_manager" in fname_lower:
        return "level_3b_tpm"
    elif "field_cto" in fname_lower or "strategist" in fname_lower or "interim_ai_strategy" in fname_lower or "practice_director" in fname_lower:
        return "field_cto"
    elif "lakehouse" in fname_lower or "agentic" in fname_lower or "gcp_data" in fname_lower or "engineer_iii_ai" in fname_lower or "data_architecture" in fname_lower:
        return "data_platform_ai"
    elif "presales" in fname_lower or "advisory_lead" in fname_lower:
        return "presales_lead"
    elif "advisor" in fname_lower or "solutions_architect" in fname_lower or "industry_advisor" in fname_lower:
        return "level_3a_advisor"

    # Secondary check on content
    if "governance" in text_lower and ("nist" in text_lower or "collibra" in text_lower or "metadata" in text_lower):
        return "level_3c_governance"
    elif "program manager" in text_lower or "cross-functional orchestration" in text_lower:
        return "level_3b_tpm"
    elif "field cto" in text_lower or "chief technology" in text_lower:
        return "field_cto"
    elif "lakehouse" in text_lower or "agentic ai" in text_lower:
        return "data_platform_ai"
    
    return "level_3a_advisor"


def parse_resume_metadata(path: Path, category: str) -> Dict[str, Any]:
    """Parse resume file metadata, lens, summary snippet, and format."""
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    size_kb = round(stat.st_size / 1024, 1)
    file_ext = path.suffix.lower().replace(".", "")

    text = ""
    if file_ext == "docx":
        text = extract_docx_text(path)
    
    lens_key = determine_lens_from_content(path.name, text)
    lens_info = LENS_DEFINITIONS.get(lens_key, LENS_DEFINITIONS["level_3a_advisor"])

    # Extract clean title/headline from document text or filename
    headline = ""
    if text:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        for idx in range(min(5, len(lines))):
            line = lines[idx]
            if any(term in line.upper() for term in ["ARCHITECT", "ADVISOR", "GOVERNANCE", "DIRECTOR", "MANAGER", "STRATEGIST", "CTO", "LEAD"]):
                headline = line
                break
    
    if not headline:
        clean_name = path.stem.replace("_", " ").replace("-", " ")
        headline = clean_name

    snippet = text[:400] if text else f"Standard {file_ext.upper()} resume document"

    # Human-friendly display title
    display_title = path.stem.replace("Brian_Kinlaw_", "").replace("Brian_", "").replace("_current", "").replace("_", " ")

    return {
        "id": str(path.resolve()),
        "filename": path.name,
        "filepath": str(path.resolve()),
        "display_title": display_title,
        "category": category,  # 'standard_canonical', 'targeted_custom', 'source_of_truth', 'master_variant'
        "target_lens": lens_key,
        "lens_name": lens_info["name"],
        "lens_badge": lens_info["badge"],
        "lens_color": lens_info["color"],
        "headline": headline,
        "snippet": snippet,
        "format": file_ext,
        "size_kb": size_kb,
        "last_modified": mtime,
        "raw_text_length": len(text)
    }


def scan_canonical_system(force_refresh: bool = False) -> Dict[str, Any]:
    """Scan all canonical directories on disk and return indexed resume variants."""
    global _RESUME_CACHE, _LAST_SCAN_TIME
    import time
    now = time.time()
    if not force_refresh and _RESUME_CACHE and _LAST_SCAN_TIME and (now - _LAST_SCAN_TIME < 60):
        return _RESUME_CACHE

    standard_canonicals = []
    targeted_customs = []
    source_of_truth_docs = []
    master_variants = []

    # 1. Scan Canonical - Active
    if CANONICAL_ACTIVE_DIR.exists():
        for f in sorted(CANONICAL_ACTIVE_DIR.glob("*")):
            if f.name.startswith(("~$", ".")) or f.is_dir():
                continue
            if f.suffix.lower() in [".docx", ".pdf"]:
                fname_lower = f.name.lower()
                if "ledger" in fname_lower or "narrative" in fname_lower or "linkedin" in fname_lower or "leadership track record" in fname_lower:
                    meta = parse_resume_metadata(f, "source_of_truth")
                    source_of_truth_docs.append(meta)
                else:
                    meta = parse_resume_metadata(f, "standard_canonical")
                    standard_canonicals.append(meta)

    # 2. Scan Targeted Applications
    if TARGETED_APPS_DIR.exists():
        for f in sorted(TARGETED_APPS_DIR.glob("*")):
            if f.name.startswith(("~$", ".")) or f.is_dir():
                continue
            if f.suffix.lower() in [".docx", ".pdf"]:
                meta = parse_resume_metadata(f, "targeted_custom")
                targeted_customs.append(meta)

    # 3. Scan Downloads / Resume Variants
    if DOWNLOADS_VARIANTS_DIR.exists():
        for f in sorted(DOWNLOADS_VARIANTS_DIR.glob("*")):
            if f.name.startswith(("~$", ".")) or f.is_dir():
                continue
            if f.suffix.lower() in [".docx", ".pdf"]:
                meta = parse_resume_metadata(f, "master_variant")
                master_variants.append(meta)

    # 4. Scan Local Project Resumes Directory
    if RESUMES_DIR.exists():
        for f in sorted(RESUMES_DIR.glob("*")):
            if f.name.startswith(("~$", ".")) or f.is_dir():
                continue
            if f.suffix.lower() in [".docx", ".pdf", ".txt"]:
                # Check if already indexed
                if any(r["filename"] == f.name for r in (standard_canonicals + targeted_customs + master_variants + source_of_truth_docs)):
                    continue
                fname_lower = f.name.lower()
                if "ledger" in fname_lower or "master" in fname_lower:
                    meta = parse_resume_metadata(f, "source_of_truth")
                    source_of_truth_docs.append(meta)
                elif "advisor" in fname_lower or "canonical" in fname_lower:
                    meta = parse_resume_metadata(f, "standard_canonical")
                    standard_canonicals.append(meta)
                else:
                    meta = parse_resume_metadata(f, "targeted_custom")
                    targeted_customs.append(meta)

    all_resumes = standard_canonicals + targeted_customs + master_variants

    _RESUME_CACHE = {
        "status": "SUCCESS",
        "canonical_active_path": str(CANONICAL_ACTIVE_DIR),
        "targeted_apps_path": str(TARGETED_APPS_DIR),
        "downloads_variants_path": str(DOWNLOADS_VARIANTS_DIR),
        "resumes_dir_path": str(RESUMES_DIR),
        "total_resumes": len(all_resumes),
        "standard_canonicals": standard_canonicals,
        "targeted_customs": targeted_customs,
        "master_variants": master_variants,
        "source_of_truth_docs": source_of_truth_docs,
        "all_resumes": all_resumes,
        "lenses": LENS_DEFINITIONS,
        "locked_facts": LOCKED_FACTS,
        "timestamp": datetime.now().isoformat()
    }
    _LAST_SCAN_TIME = now
    return _RESUME_CACHE


def get_canonical_ledger_summary() -> str:
    """Read the latest Accomplishment Ledger for factual grounding."""
    search_dirs = [CANONICAL_ACTIVE_DIR, RESUMES_DIR]
    for d in search_dirs:
        if not d.exists():
            continue
        ledger_files = list(d.glob("*Accomplishment_Ledger*.docx")) + list(d.glob("*Ledger*.docx")) + list(d.glob("*master*.txt"))
        if ledger_files:
            ledger_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            chosen = ledger_files[0]
            if chosen.suffix.lower() == ".docx":
                return extract_docx_text(chosen)
            else:
                try:
                    with open(chosen, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
    
    # Fallback to compiled locked facts text if no raw file on disk
    return "\n".join([f"- {k}: {v}" for k, v in LOCKED_FACTS.items()])


def find_best_resume_match(job_title: str, job_description: str, sender: str = "") -> Dict[str, Any]:
    """
    Intelligently matches incoming job specifications against the canonical system.
    Returns the recommended resume, matching lens, match score (0-100), and rationale.
    """
    catalog = scan_canonical_system()
    all_resumes = catalog.get("all_resumes", [])
    if not all_resumes:
        return {
            "selected_resume": None,
            "selected_resume_path": None,
            "match_score": 0,
            "matching_lens": "level_3a_advisor",
            "lens_name": LENS_DEFINITIONS["level_3a_advisor"]["name"],
            "lens_badge": LENS_DEFINITIONS["level_3a_advisor"]["badge"],
            "lens_color": LENS_DEFINITIONS["level_3a_advisor"]["color"],
            "rationale": "No canonical resumes found on disk.",
            "key_skills_matched": []
        }

    full_context = f"{job_title} {job_description} {sender}".lower()

    # 1. Score each lens archetype
    lens_scores: Dict[str, int] = {k: 0 for k in LENS_DEFINITIONS.keys()}
    for lens_key, lens_data in LENS_DEFINITIONS.items():
        for kw in lens_data["keywords"]:
            if kw in full_context:
                lens_scores[lens_key] += full_context.count(kw) * 3

    # Direct keyword boosts
    if any(k in full_context for k in ["governance", "collibra", "metadata", "lineage", "nist", "stewardship", "mdm", "compliance"]):
        lens_scores["level_3c_governance"] += 15
    if any(k in full_context for k in ["field cto", "chief technology", "platform strategist"]):
        lens_scores["field_cto"] += 15
    if any(k in full_context for k in ["lakehouse", "agentic", "gcp data", "bigquery", "databricks"]):
        lens_scores["data_platform_ai"] += 12
    if any(k in full_context for k in ["program manager", "tpm", "cross-functional orchestration", "pmp"]):
        lens_scores["level_3b_tpm"] += 15
    if any(k in full_context for k in ["presales", "pre-sales", "solutions architect", "advisor", "discovery"]):
        lens_scores["level_3a_advisor"] += 10

    best_lens = max(lens_scores.items(), key=lambda x: x[1])[0]
    best_lens_info = LENS_DEFINITIONS[best_lens]

    # 2. Find best specific resume candidate
    best_resume = None
    best_candidate_score = -1

    for resume in all_resumes:
        score = 0
        r_fname = resume["filename"].lower()
        r_lens = resume["target_lens"]

        if r_lens == best_lens:
            score += 30

        if resume["category"] == "standard_canonical":
            score += 25
        elif resume["category"] == "targeted_custom":
            score += 15

        if resume["format"] == "pdf":
            score += 5

        # Check company specific matching in filename
        for token in full_context.split():
            clean_tok = re.sub(r'[^a-zA-Z0-9]', '', token)
            if len(clean_tok) > 4 and clean_tok in r_fname:
                score += 35

        if score > best_candidate_score:
            best_candidate_score = score
            best_resume = resume

    if not best_resume:
        best_resume = all_resumes[0]

    match_pct = min(98, max(75, 70 + (lens_scores[best_lens] * 2)))

    matched_skills = [kw.title() for kw in best_lens_info["keywords"] if kw in full_context]
    if not matched_skills:
        matched_skills = ["Enterprise Architecture", "Cloud Data & AI", "Executive Advisory", "Google Cloud / GCP"]

    rationale = f"Matched to {best_lens_info['name']} based on focus on {', '.join(matched_skills[:4])}. Selected authoritative resume: {best_resume['filename']}."

    return {
        "selected_resume": best_resume["filename"],
        "selected_resume_path": best_resume["filepath"],
        "selected_resume_meta": best_resume,
        "match_score": match_pct,
        "matching_lens": best_lens,
        "lens_name": best_lens_info["name"],
        "lens_badge": best_lens_info["badge"],
        "lens_color": best_lens_info["color"],
        "rationale": rationale,
        "key_skills_matched": matched_skills[:6]
    }

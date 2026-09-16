# Aura Mail AI — Authoritative Documentation Index

**System Version:** Aura Mail AI v1.1  
**Certified Implementation Baseline:** `0cc60495e9fdc64526cd231beb562c2c36de53df`  
**Baseline Tree Hash:** `6c6422cc3b26927f5539ac3c8988fb983041a9a9`  

This index defines the authoritative documentation model for Aura Mail AI. It categorizes current living specifications from historical audit artifacts, ensuring future maintainers and security reviewers navigate the repository accurately.

---

## 1. Documentation Structure & Responsibilities

```text
docs/
├── README.md                 # Master Authoritative Index (This Document)
├── architecture/             # Current System & Component Architecture
│   └── ARCHITECTURE.md
├── security/                 # Current Security Specifications & Threat Models
│   ├── THREAT_MODEL.md
│   ├── SECURITY_REPORT.md
│   └── REMEDIATION_BASELINE.md
├── operations/               # Operational Guides & Setup Procedures
│   ├── OUTLOOK_ADDIN_SETUP.md
│   └── MAC_SMOKE_TEST_CHECKLIST.md
├── development/              # Engineering, Review & Testing Standards
│   ├── PEER_REVIEW_GUIDE.md
│   └── CHATGPT_REVIEW_PROMPT.md
├── release/                  # Release Notes & Migration Guides
│   └── MIGRATION_v1.0_to_v1.1.md
└── history/                  # Historical Audit Trail & Phase Evidence Index
    └── README.md
```

---

## 2. Authoritative Document Classification

| Document Path | Status | Role / Domain | Authoritative Scope |
| :--- | :--- | :--- | :--- |
| [`docs/architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md) | **CURRENT** | Architecture | System architecture, component boundaries, provider isolation fences, data lifecycles. |
| [`docs/security/THREAT_MODEL.md`](security/THREAT_MODEL.md) | **CURRENT** | Security | Formal local-desktop threat model, loopback boundaries, in-scope vs out-of-scope threats. |
| [`docs/security/SECURITY_REPORT.md`](security/SECURITY_REPORT.md) | **CURRENT** | Security | Comprehensive security assessment, provider authorization fences, risk governance. |
| [`docs/security/REMEDIATION_BASELINE.md`](security/REMEDIATION_BASELINE.md) | **HISTORICAL BASELINE** | Security | Remediation tracking baseline from Phase 0 through release. |
| [`docs/operations/OUTLOOK_ADDIN_SETUP.md`](operations/OUTLOOK_ADDIN_SETUP.md) | **CURRENT** | Operations | New Outlook & M365 manifest sideloading, local TLS certificates, debugging. |
| [`docs/operations/MAC_SMOKE_TEST_CHECKLIST.md`](operations/MAC_SMOKE_TEST_CHECKLIST.md) | **CURRENT** | Operations | Mac desktop manual verification procedures, menubar helper, radar workflows. |
| [`docs/development/PEER_REVIEW_GUIDE.md`](development/PEER_REVIEW_GUIDE.md) | **CURRENT** | Development | Independent peer review guide, adversarial test suites, reproduction protocols. |
| [`docs/development/CHATGPT_REVIEW_PROMPT.md`](development/CHATGPT_REVIEW_PROMPT.md) | **CURRENT** | Development | Independent AI audit prompts and verification guidelines. |
| [`docs/release/MIGRATION_v1.0_to_v1.1.md`](release/MIGRATION_v1.0_to_v1.1.md) | **CURRENT** | Release | Migration specifications, breaking changes, settings migration from v1.0 to v1.1. |
| [`docs/history/README.md`](history/README.md) | **HISTORICAL INDEX** | Audit Provenance | Complete multi-phase remediation audit log, frozen SHA lineage, and permanent audit principles. |
| [`evidence/`](../evidence/README.md) | **EVIDENCE STORE** | Evidence | Standalone cryptographic audit packages, test transcripts, and correction records. |

---

## 3. Core Architectural Invariants

1. **Permanent Mail-Safety Invariant:** Direct mail transmission by Aura is strictly forbidden (`ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN`). All send primitives fail closed with `SEND_FORBIDDEN`.
2. **Provider Scope Least-Privilege:** Microsoft Graph requests only `User.Read` and `Mail.ReadWrite` (`Mail.Send` is omitted). Gmail requests only `https://www.googleapis.com/auth/gmail.modify` (`gmail.send` is omitted).
3. **Loopback-Only Interface:** Local API server binds strictly to `127.0.0.1` and enforces constant-time session token authentication and ASGI client peer socket validation.
4. **Canonical Attachment Containment:** All draft attachments are resolved strictly through `backend/canonical_engine.py` against 4 approved directory roots, requiring regular files (`stat.S_ISREG`) and rejecting traversal/symlink escapes.
5. **Deterministic Risk Governance:** Risk Sentinel enforces monotonic scoring floors (`FINAL_RISK >= DETERMINISTIC_RISK`) and exact draft hash binding.

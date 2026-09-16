# Aura Mail AI — External Evidence Archive Reference

**Certified Implementation Baseline:** `0cc60495e9fdc64526cd231beb562c2c36de53df`  
**Certified Implementation Tree:** `6c6422cc3b26927f5539ac3c8988fb983041a9a9`  
**External Archive Canonical Path:** `$HOME/Aura-Mail-AI-Audit-Archive/`  

---

## 1. Archive Scope & Relationship to Repository

This document establishes the official reference from the Aura Mail AI codebase to the external **Master Security Remediation & Audit Archive**.

> [!IMPORTANT]
> The external evidence archive `$HOME/Aura-Mail-AI-Audit-Archive/` was consolidated after completion of the Phase 13 Final Release Gate.
> It contains the complete forensic and historical evidence trail from Phase 0 through Phase 13.
> The existence of this post-release archive reference does not modify or retroactively change the certified application source tree (`0cc6049`).

---

## 2. External Archive Structure

The external archive is organized into dedicated, immutable domain directories:

```text
$HOME/Aura-Mail-AI-Audit-Archive/
├── README.md                  # Master Archive Overview & Invariants
├── MASTER_EVIDENCE_INDEX.md   # Comprehensive Catalog of 119 Evidence Artifacts
├── SHA256SUMS_MASTER.txt      # Cryptographic SHA-256 Manifest
├── protocols/                 # Build & Remediation Governance Protocols (Rev 2.0, 2.1)
├── peer-reviews/              # Independent Peer Review Bundles
├── phase-04/ through phase-05/# Historical Audit ZIP Archives (Phase 4.0 - 5.5.5)
├── phase-06.1/ - phase-12.1/  # Phase Artifact Bundles (Committed, Parent, Patches, Logs)
├── phase-13/                  # Phase 13 Release Reports, Telemetry, and Transcripts
└── unclassified/              # Reserved for Unattributed Evidence
```

---

## 3. Cryptographic Verification

All external evidence files are cryptographically anchored by SHA-256 hashes in:
* Master Manifest: `$HOME/Aura-Mail-AI-Audit-Archive/SHA256SUMS_MASTER.txt`
* In-Repo Evidence Manifest: [`evidence/security-remediation-v1.1/phase-13/SHA256SUMS_phase13_corrected.txt`](file:///Users/briankinlaw/aura-mail-ai/evidence/security-remediation-v1.1/phase-13/SHA256SUMS_phase13_corrected.txt)

To verify the external archive integrity at any time from terminal:
```bash
cd "$HOME/Aura-Mail-AI-Audit-Archive"
shasum -a 256 -c SHA256SUMS_MASTER.txt
```

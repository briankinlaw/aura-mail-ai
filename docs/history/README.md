# Aura Mail AI — Historical Remediation & Audit Provenance Index

**Certified Baseline Commit:** `0cc60495e9fdc64526cd231beb562c2c36de53df`  
**Certified Baseline Tree:** `6c6422cc3b26927f5539ac3c8988fb983041a9a9`  

This index documents the complete historical lineage of the Aura Mail AI v1.1 security remediation lifecycle. It preserves every audit, remediation candidate, failed attempt, and certification milestone to maintain full transparency and audit reproducibility.

---

## 1. Remediation Phase & Lineage Table

| Phase | Purpose | Candidate SHA | Parent SHA | Verdict | Frozen? | Superseded? | Primary Evidence / Artifact Location | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 6.4** | Localhost desktop boundary remediation | `79e4a8c` | `630c6b5` | PASS | YES | NO | `~/aura_mail_ai_phase6_4_artifacts/` | Enforced loopback peer validation & CORS |
| **Phase 6.5** | Browser context & Fetch Metadata checks | `73c02b8` | `79e4a8c` | PASS | YES | NO | `~/aura_mail_ai_phase6_5_artifacts/` | Sec-Fetch-Site and Origin filtering |
| **Phase 7** | Multi-account isolation candidate | `d52f537` | `73c02b8` | FAIL | NO | YES | `~/aura_mail_ai_phase7_artifacts/` | Test runner concurrency issue |
| **Phase 7.1** | Multi-account isolation remediation | `900ea28` | `73c02b8` | PASS | YES | NO | `~/aura_mail_ai_phase7_1_artifacts/` | Multi-account state fencing complete |
| **Phase 8** | Outlook cloud-draft staging | `b3314ec` | `900ea28` | PASS | YES | NO | `~/aura_mail_ai_phase8_artifacts/` | 52 JS tests for draft staging without send |
| **Phase 9** | Outlook content HTML escaping | `167eaf4` | `b3314ec` | PASS | YES | NO | `~/aura_mail_ai_phase9_artifacts/` | 48 JS tests for content neutralization |
| **Phase 10** | Reproducible build candidate | `3d4035f` | `167eaf4` | FAIL | NO | YES | `~/aura_mail_ai_phase10_artifacts/` | Missing pyproject.toml declaration |
| **Phase 10.1** | Reproducible build remediation | `1b38dcc` | `3d4035f` | PASS | YES | NO | `~/aura_mail_ai_phase10_1_artifacts/` | Hermetic pyproject.toml / requirements |
| **Phase 11** | Documentation truth candidate | `0b9720a` | `1b38dcc` | FAIL | NO | YES | `~/aura_mail_ai_phase11_artifacts/` | Residual documentation claims |
| **Phase 11.1 (p)**| Documentation truth remediation | `29f13c3` | `1b38dcc` | FAIL (proc) | NO | YES | `~/aura_mail_ai_phase11_1_artifacts/` | Substantive PASS, procedural commit subject fail |
| **Phase 11.1 (c)**| Documentation truth corrected | `cfa15a3` | `1b38dcc` | PASS | YES | NO | `~/aura_mail_ai_phase11_1_artifacts/` | Frozen documentation baseline |
| **Phase 12** | Independent adversarial regression audit | `cfa15a3` | `1b38dcc` | CAUTION | YES | NO | `evidence/security-remediation-v1.1/phase-12/` | Read-only audit; identified finding P12-001 |
| **Phase 12.1** | Attachment boundary remediation | `0cc6049` | `cfa15a3` | PASS | YES | NO | `~/aura_mail_ai_phase12_1_artifacts/` | Authoritative attachment canonical boundary |
| **Phase 13** | Final release gate audit | `0cc6049` | `cfa15a3` | PASS | YES | NO | `evidence/security-remediation-v1.1/phase-13/` | Read-only release gate certification |
| **Phase 13 (ec)**| Evidence root cause & certification repair| `0cc6049` | `cfa15a3` | PASS | YES | NO | `evidence/security-remediation-v1.1/phase-13/` | Restored 29-section report & exact scope truth |

---

## 2. Permanent Audit Principles

All future development, maintenance, and auditing within Aura Mail AI must adhere to the following ten governing principles:

1. **Failed candidates remain part of history:** Failed audit candidates are never deleted or rewritten from Git history or provenance indices.
2. **Frozen SHA values are never reassigned:** Once a baseline is certified, its SHA and tree hash remain permanent.
3. **Historical reports are not silently corrected:** Historical reports preserve their original state as evidence; corrections are made through explicit, additive superseding records.
4. **Corrections are additive and explicitly superseding:** Every modification to certification evidence must clearly reference its predecessor and document the rationale and delta.
5. **Evidence artifacts are immutable once hashed:** Once an artifact is cryptographically hashed and added to a manifest, its content is immutable.
6. **Packaging copies evidence; it does not regenerate it:** Evidence packaging workflows must copy existing audit artifacts byte-for-byte without on-the-fly synthesis or summarization.
7. **Current documentation and historical documentation are separated:** Living architecture and security specifications are organized separately from historical audit records (`docs/` vs `docs/history/` / `evidence/`).
8. **Repository organization after certification creates a new repository state:** Post-release organizational commits do not retroactively modify the certified application baseline SHA (`0cc6049`).
9. **Provider technical capability, application capability, and application authorization are distinct concepts:** Credentials granted by third-party providers do not define application-level authorization.
10. **Security certification means no unresolved release-blocking findings identified:** Certification guarantees that all tested invariants, boundaries, and threat model criteria pass without open blocking findings; it does not imply unprovable claims of absolute zero possible bugs.

---
name: audit-evidence
description: Prepares audit-ready proof from AgentFox. It verifies the tamper-evident audit chain, checkpoints it, recomputes control status, reports framework posture (EU AI Act, NIST AI RMF, ISO 42001, SOC 2, OWASP, MITRE ATLAS) and exports an evidence package an auditor can verify independently. Use for "we have an audit", "export evidence", "are we EU AI Act ready", compliance status, or /agentfox:evidence.
---

# Audit evidence

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

**Honesty rule.** Every framework mapping ships as `review_status: draft`. Present results as
"control coverage mapped by engineers, DRAFT — UNVERIFIED / NOT LEGAL ADVICE". Never say
"compliant". The evidence package badges drafts the same way.

## 1. Is the record intact?

```bash
agentfox report verify
```

- **Exit 1:** the chain is broken, and the output names the first bad entry. **Stop.** This
  is now an incident. Load **incident-response**. Don't checkpoint over a broken chain.
- **Exit 0:** write a signed checkpoint so later tampering is detectable back to this point:

```bash
agentfox admin checkpoint
```

In production, `AGENTFOX_AUDIT_SIGNING_KEY` must not be the dev default. Check this with
**operate-deployment**'s hardening list.

## 2. Bring control status up to date

```bash
agentfox admin catalog validate
agentfox admin catalog sync
agentfox admin catalog compute --window-days 90
```

Pick the window to match the audit period. `validate` exits 1 if the catalog itself is
inconsistent; fix that before quoting any posture.

## 3. Posture for the framework in question

```bash
agentfox report frameworks
agentfox report status --framework <eu-ai-act|nist-ai-rmf|iso-42001|soc2|owasp-llm|owasp-agentic|mitre-atlas>
agentfox report risk
agentfox report obligations
```

Summarise four things:

- which controls are effective, partial or failing
- which obligations are coming due, from the dated calendar
- which agents are high-risk in the risk register
- **what the mapping does not cover**, from Appendix B §B.4 (`docs/design/control-catalog.md`)

For executives, run `compliance board`, or `agentfox report --since 90d --format html --out
summary.html` for a one-page plain-language summary. Both compute control status themselves if
step 2 was skipped.

## 3b. Offer the path out of DRAFT

Every mapping ships `DRAFT — UNVERIFIED / NOT LEGAL ADVICE`, and an auditor will ask about it.
There is now a reviewable artefact to hand a qualified reviewer, one row per decision:

```bash
agentfox report review-packet --framework eu-ai-act --out review-packet.md
```

When a named, accountable human signs off, record it. This is an attestation by that person,
not something you decide on their behalf:

```bash
agentfox report signoff NOM-IAM-03 --framework eu-ai-act --reviewer "<their name>"
```

Never run the review command on your own judgement. Offer the packet, and say who has to sign it.

## 4. Export the package

```bash
agentfox report evidence --agent <slug> --since-days 90 --requested-by "<user's name>"
```

- Repeat `--agent` or `--control` to scope the export. Leave them out for everything.
- For a fixed audit period, give the dates instead of a window:
  `agentfox report evidence --from 2026-01-01 --to 2026-03-31`. An end date given as
  `YYYY-MM-DD` covers that whole day.
- The zip lands in `AGENTFOX_EVIDENCE_DIR` (default `var/evidence/`). Tell the user the path.
- It opens on `SUMMARY.md` / `SUMMARY.html`, the plain-language page for the same scope. Point
  the auditor there first; the JSON files are what it is built from.

## 5. Prove the package stands on its own

Unzip into a temp directory and run the bundled verifier. It needs nothing but Python:

```bash
python verify_chain.py            # exit 0 = intact, 1 = tampered
```

With `AGENTFOX_AUDIT_KEY` set, it also checks checkpoint
signatures. Tell the auditor they
can run it themselves, because that's the point of it.

## 6. Hand-off note

Write a short cover note for the auditor. It has five parts:

1. the period covered and the agents in scope
2. the chain verification result and the checkpoint time
3. framework posture counts, with the DRAFT caveat
4. the known gaps
5. how to run `verify_chain.py`

# Production Readiness Review

**Date: 2026-09-04, with a 2026-10-06 addendum (§7). Scope: [docs/hld.md](../architecture/high-level-design.md) and [docs/lld.md](../architecture/low-level-design.md), checked against
the live codebase.**

This document is **not** a replacement for [docs/gap-analysis.md](gap-analysis.md), which
remains the canonical, severity-ranked, continuously re-audited enterprise-readiness
assessment (last updated 2026-08-29, itself already a rigorous, code-verified piece of work —
re-read it before this document if you haven't). This document does three things
gap-analysis.md doesn't:

1. **Re-verifies, as of today, the specific open items gap-analysis.md flagged as most
   important** — particularly its own stated #1 priority ("wire the stub-only modules") —
   against the code as it stands right now, six days later.
2. **Surfaces new findings** that fell out of writing the HLD/LLD documents — things noticed
   while tracing the actual request path and deployment artifacts that the previous audit
   didn't call out, because it was scoped differently.
3. **Reconciles a documentation inconsistency** the LLD-writing process surfaced between
   `traceability.md` and `appendix-b-control-catalog.md` on a compliance-relevant question
   (whether DRAFT framework mappings are excluded from evidence packages, or included with a
   label).

Everything here is grep/read-verified against the repository on 2026-09-04, not inferred
from prior documents. Where a claim is unverifiable from the code alone (certifications,
legal review, org process), it's marked as such rather than guessed at.

---

## 1. New findings this pass

These were not in gap-analysis.md's register as of 2026-08-29.

### 1.1 ✅ (was 🔴) `deploy/Dockerfile` builds against paths that don't exist in the repo

> **Resolved in `6863b8b`** — the Dockerfile's `COPY` paths now exist, and CI's `docker-smoke` job builds the `deps` stage on every push.

```dockerfile
COPY compliance ./compliance
COPY policies ./policies
```

Verified directly: `ls -d compliance policies` at the repo root returns "No such file or
directory" for both. The actual data these lines presumably meant to copy already ships via
the preceding `COPY src ./src` — it lives at `src/agentfox/compliance_data/` and
`src/agentfox/policies_data/`. As written, `docker build -f deploy/Dockerfile .` targets a
source path that isn't in the tree. This is the **primary supported deployment path** (HLD
§9) — if this build is not actually being run as part of any CI or release process right
now, that itself is worth knowing, because it means the "self-host, docker compose up" story
in the README has not been exercised end-to-end recently. **Action: fix the two `COPY` lines
(most likely they should read `src/agentfox/compliance_data` /
`src/agentfox/policies_data`, or be deleted if `COPY src ./src` already covers them — check
whether anything downstream in the image expects a top-level `/app/compliance` path before
choosing), then add a CI job that actually builds this image so this class of drift can't
recur silently.** Effort: S.

### 1.2 ✅ (was 🔴) The Vercel-vendored wheel is currently stale, not just historically incident-prone

> **Resolved in `6863b8b`** — a pre-commit hook rebuilds both vendored wheels when `src/agentfox/` changes, and CI's `vendored-wheel-freshness` job fails pushes that skip it.

Gap-analysis.md and the LLD both note the wheel-drift *pattern* (three recent commits —
`2cfe048`, `551c220`, `00a4d4f` — show a real production incident from exactly this).
Checked freshly on 2026-09-04: `api/vendor/nometria-0.1.0-py3-none-any.whl` is dated
2026-08-28. Files newer than the wheel under `src/agentfox/` include `enforcement.py`,
`autoguard.py`, `context_integrity.py`, `models.py`, `answerability.py`, `entitlement.py`,
`data_access.py`, `discovery.py`, `register.py`, `system_log.py`, `db.py`, `config.py`,
`finding.py`, `effects.py`, `availability.py`, `attribution.py`, `seed.py`, plus
`audit/chain.py` and `audit/evidence.py`. **The hosted/Vercel deployment is running code that
predates changes to at least 19 modules, including the enforcer itself.** This isn't
necessarily broken today — depends what actually changed — but it means the wheel-rebuild
step is not currently part of anyone's habitual workflow, which is exactly the condition that
produced the prior incident. **Action: either (a) automate the wheel rebuild as a pre-commit
or CI step so it can never silently drift again, or (b) if the hosted path is low-priority
enough to accept manual staleness, say so explicitly in the README/HLD rather than let it
read as fully supported.** Effort: S (automate) or documentation-only (accept and disclose).

### 1.3 🟡 PL-4 (loop governance) is mid-flight right now — track it to completion, don't let it stall as a fourth stub

The uncommitted working-tree diff (`git status`, five modified files:
`gateway/routes/inline.py`, `integrations/langgraph.py`, `seed.py`, and two test files) is
actively wiring `agent_loop.py`'s `LoopGovernor` to receive a full step history
(`prior_steps`, each `{tool, arguments, observation}`) from both the gateway's
`guard_tool_call` endpoint and the LangGraph `tool_node` decorator, rather than just a
per-tool repeat count. This is a direct, in-progress response to gap-analysis.md's own
highest-priority open item ("wire the stub-only modules... the single highest-leverage
remaining item in this whole document"). Good sign: this work is real and in flight. Flag,
not a gap: it's uncommitted, and the LLD (§1.1) now documents `agent_loop.py` as having a
real caller (`enforcement.py:2367`) — good — but the richer step-history wiring should be
finished, tested, and committed before it's described anywhere as done, or the next audit
will have to re-discover the same in-progress state. **Action: finish and commit this
change, then re-run `scripts/gen/coverage.py --write` so `docs/status.md`'s PL-4 entry reflects
it.** Effort: S (appears nearly complete already).

### 1.4 ✅ (was 🟡) `jobs.py` remains genuinely, verifiably stub-only

> **Resolved in `56767b0`** — the deferred job queue (PL-5) is wired into evidence export and red-team campaigns, with a migration and a cron-driven runner.

Re-checked directly (`grep` for any import of `jobs` outside `jobs.py` itself and its test
file): zero matches. This is the one item from gap-analysis.md's stub-only list that shows
**no forward progress** as of this pass — `agent_loop.py` now has a real caller (§1.3),
`context_integrity.py` has real callers (`finding.py`, `gateway/routes/provenance.py`), but
`jobs.py`'s async job-queue interface is still built, tested, and wired to nothing. This
matches Tier 0 gap 0.5 in gap-analysis.md ("everything synchronous... stub-only") almost
exactly — that finding is still accurate for this specific module. **Action: either wire it
in (evidence-package export and red-team-campaign runs are the two candidates gap-analysis.md
names as the operations that should move off the request thread) or, if it's not on the
near-term roadmap, remove it from any "built" framing until it has a caller — an untested-by-
production-use module sitting in the codebase is a maintenance liability even when its own
unit tests pass.** Effort: M.

### 1.5 🟢 `context_integrity.py` (F8, Pillar 14) has moved from stub-only to wired — update the record

Gap-analysis.md (2026-08-29) listed context integrity (F8, except F8.3) as built-and-tested
but "wired into nothing a live request touches." Re-checked: `context_integrity.py` now has
real callers in `finding.py` and `gateway/routes/provenance.py`. This looks like genuine
progress since the last audit. **Action: verify with an actual end-to-end trace (not just a
grep for imports) that a live request path exercises this, then update `docs/status.md` and
gap-analysis.md's F8 row accordingly** — don't let a positive finding go stale the same way a
negative one would. Effort: S (verification only, if the wiring is confirmed real on inspection).

### 1.6 🟡 `commitments.py`/`register.py` (F6) status is genuinely ambiguous from a grep pass alone

An initial grep for "register" callers returned several hits in `cli/main.py` and
`gateway/app.py`, but on inspection every one of them is an unrelated `register()` function
(CLI subcommand registration, the compliance risk register, offline-provider script
re-registration) — not `commitments.py`'s commitment register. This is a **documentation-
verification finding, not a code finding**: F6 (commitment/advice/liability-language
detection) could not be confirmed wired or unwired by name-based search alone, because
`register` and `register_agent`-style names collide across unrelated modules. Treat
gap-analysis.md's existing "stub-only" call on F6 as still the best available answer, but
**recommend a targeted trace (log a marker inside `commitments.py`'s entry point and run one
real request through the full path) rather than a follow-up grep**, since grep has now
produced one false positive already for the same question. Effort: S.

### 1.7 ✅ (was 🟡) No frontend test coverage anywhere in the repo

> **Resolved in `c512ee3`** — vitest was added with tests for `lib/product/proxy.ts` and the legacy redirects; the suite has grown since (the auth routes among others), and CI runs `npm test`.

The LLD's module/test inventory pass (§2) found 46 backend test files and zero anywhere
exercising `dashboard/`. Given the dashboard is a genuine client of the API with real
mutation flows (proxy routes, session-cookie auth, the playground's unauthenticated
client-side path — HLD §4), and given a recent commit
(`b0df213 refactor(dashboard): consolidate proxy boilerplate, restructure IA around
researched terminology, fix bugs found in review`) shows the dashboard has undergone a real
structural refactor recently, shipping that kind of change with zero automated regression
coverage is a real risk, distinct from (and not mentioned in) gap-analysis.md's existing
gap register, which is scoped to the Python package. **Action: at minimum, add coverage for
`dashboard/lib/product/proxy.ts` (the auth/mutation boundary) and the board→compliance-tab redirect
logic, since both are exactly the kind of "worked when I looked, broke when someone touched
something two files away" surface unit tests exist for.** Effort: M.

### 1.8 🟢 Documentation inconsistency, now reconciled: are DRAFT framework mappings excluded from evidence packages, or included with a label?

Three documents make three different-sounding statements about the same control:

- `traceability.md`: "All 257 framework mappings are `review_status: draft` and are
  **excluded** from evidence packages until a qualified reviewer completes the gate."
- `docs/README.md` §"Honest limits": "The product badges them as such and **excludes**
  drafts from evidence packages."
- `appendix-b-control-catalog.md`'s changelog (dated later, per its own record): draft
  mappings ship in evidence packages **chip-labeled** `DRAFT — UNVERIFIED / NOT LEGAL ADVICE`
  rather than being excluded.

**Settled, by reading the actual code**: `audit/evidence.py:249-253,391-396,443-444,522-552`
confirms the current implementation **chip-labels, does not exclude**. Every mapping ships in
`framework_mappings.json`, each row carrying either a `reviewed` or a
`"DRAFT — UNVERIFIED / NOT LEGAL ADVICE"` chip (line 396); the package's manifest separately
counts `reviewed_mappings` and `draft_mappings_included` (lines 443-444); the evidence
package's own README template states explicitly that draft mappings "are engineering drafts
produced from framework texts and are not legal [advice]" (lines 549-552). So
`appendix-b-control-catalog.md`'s changelog is the accurate document; `traceability.md` and
the README's "Honest limits" line ("excludes drafts from evidence packages") are both stale
and should be corrected to say draft mappings are **included with a DRAFT chip**, not
excluded. **This has been fixed directly in both files as part of this review** — see
`README.md` and `traceability.md`.

---

## 2. Re-verification of gap-analysis.md's own open items

Spot-checked the items gap-analysis.md itself flagged as its top priorities (Part 7) rather
than the full register, since re-litigating the whole document would just be a slower copy of
it.

| Item | gap-analysis.md status (2026-08-29) | Status as re-checked (2026-09-04) |
|---|---|---|
| "Wire the stub-only modules" (top priority) | `agent_loop.py`, `jobs.py`, `availability.py`'s limiter, F6, F8 all stub-only | **Partially closed since the last audit**: `agent_loop.py` has a real caller and active in-flight work (§1.3); `context_integrity.py`/F8 has real callers (§1.5); `jobs.py` remains fully stub-only (§1.4); F6/`commitments.py` status unconfirmed either way by this pass (§1.6); `availability.py`'s admission controller (`get_admission_controller`) is wired into `gateway/app.py`'s middleware — real, not stub — but see §3 for a caveat on its per-process scope |
| Start the SOC 2/ISO 27001/pentest clock | Unstarted, organisational | **Not verifiable from code** — this is a legal/process track, not something a repository audit can confirm one way or the other. See §4. |
| Close F7.7 and F8.3 | Named as the only genuinely-absent failure modes remaining (besides F3.8, closed 2026-08-30) | Not independently re-verified this pass — would require re-running the failure-mode coverage computation (`scripts/gen/coverage.py`), which is out of scope for a documentation-focused review. **Recommend running it fresh rather than trusting either document's snapshot.** |
| Decide Salesforce/ServiceNow/M365 estate connectors | Open, "a real, if large, build" | Unchanged — no evidence of new work in this area found during the HLD/LLD pass (nothing under `src/agentfox/integrations/` references these platforms) |

---

## 3. A structural observation worth adding to the register: `availability.py`'s admission control is per-process

Noticed while tracing the request path for the HLD (§9/§10 of the LLD): `gateway/app.py`'s
`admission_gate` middleware calls `get_admission_controller()`, and traceability.md's own
NFR-2 row already notes "fail_mode=open default... no full single-point-of-failure story."
Worth being explicit about the specific mechanism: if the gateway is horizontally scaled (the
architecture explicitly claims it's stateless and "scales out horizontally," HLD §4), and the
admission controller / budget limiter state is in-process rather than shared (e.g. via
Postgres or a shared cache), then a deployment with N gateway replicas gets N times the
declared admission threshold and N times the declared budget — each process enforces its own
local view. This is the same shape of issue traceability.md's PL-7 entry already names for
fail-open budgets ("multi-worker deployment gets N times the declared budget"), just
confirmed here as applying to admission control specifically, not only budgets. **Action: if
horizontal scale-out is a claim made to a prospective enterprise buyer, either move this
state to a shared store or explicitly scope the "stateless, scales out horizontally" claim to
mean "scales out for throughput, single-process for admission/budget enforcement until
follow-up work lands."** Effort: L (moving to shared state) or documentation-only (scoping
the claim honestly in the interim).

---

## 4. What this document cannot verify

Consistent with gap-analysis.md's own methodology (mark unverifiable claims as unverified,
don't assert them either way):

- **Everything on the organisational/procurement track** — SOC 2 Type II, ISO 27001, a
  penetration test report, a filled DPA/sub-processor register, a published RTO/RPO, cloud
  marketplace listings, live IdP/SSO deployment against a real identity provider. None of
  this is discoverable from source code. Gap-analysis.md's Part 6 (Enterprise procurement
  bar) is the right document for tracking this, and nothing in this pass changes its
  conclusions.
- **Whether `deploy/Dockerfile` is currently exercised by any CI pipeline.** No CI
  configuration (GitHub Actions workflows, etc.) was located during this pass — if one
  exists elsewhere and does build this image, finding 1.1 would already be failing it loudly,
  which would itself be useful signal about whether the primary deployment path is being
  tested at all.
- **Runtime behavior of the currently-stale Vercel deployment** (finding 1.2) — whether the
  drift between the vendored wheel and current `src/agentfox` has caused any *currently live*
  incorrect behavior wasn't tested; only the staleness itself was confirmed.

---

## 5. Consolidated punch list (this pass only — see gap-analysis.md for the full register)

Ranked by severity, effort noted:

| # | Finding | Severity | Effort |
|---|---|---|---|
| 1.1 | `deploy/Dockerfile` COPY paths don't exist — primary deployment path may not build | ✅ fixed in `6863b8b` | S |
| 1.2 | Vercel-vendored wheel is currently stale (19+ modules changed since) | ✅ automated in `6863b8b` | S (automate) |
| 1.4 | `jobs.py` still fully stub-only | ✅ fixed in `56767b0` | M |
| 1.7 | Zero frontend test coverage despite a recent structural refactor | ✅ fixed in `c512ee3` | M |
| 1.8 | Docs disagreed on DRAFT-mapping evidence-package behavior — settled against code (chip-labeled, not excluded) and fixed in README.md/traceability.md | ✅ fixed | S |
| 3 | Admission control / budget enforcement is per-process, undermines the "scales out" claim if not scoped honestly | 🟡 | L / doc-only |
| 1.3 | PL-4 loop-governance wiring is in flight — finish and commit | 🟢 (in progress) | S |
| 1.5 | `context_integrity.py` looks wired now — verify and update the record | 🟢 (likely good news) | S |
| 1.6 | F6 (`commitments.py`) status genuinely unclear from grep — needs a traced request, not another search | 🟡 | S |

None of these are Tier-0 "the company can't be built" findings — that bar was set by
gap-analysis.md's original 2026-08-18 audit and most of it is now closed by its own
2026-08-29 update. These are the next layer down: two concrete, fixable deployment-integrity
bugs (1.1, 1.2) that a fresh HLD/LLD pass surfaced by actually tracing the deployment
artifacts rather than reasoning about them from the README, plus confirmation that the
"wire the stubs" work gap-analysis.md prioritized is genuinely underway.

---

## 6. What's solid — don't relitigate these

To avoid this document reading as purely critical: the audit-chain design (LLD §6), the
taint-tracking/containment model (LLD §4), the single-preflight-path architecture that
prevents gateway/SDK enforcement drift (LLD §3, §7), and the swappable-OSS-seam pattern (HLD
§2, validated against three real dependency-status changes in twelve months) all held up
under direct code inspection with no new concerns. These remain the parts of the system worth
leading with in any external conversation — see [competitor-analysis.md](competitor-analysis.md)
§4 for how to frame them.

---

## 7. Addendum, 2026-10-06: security and operations fixes, and new production configuration

Re-verified against the code on 2026-10-06. Nothing here changes §§1–6; it records what a
deployment must know about the fixes and features merged since.

### 7.1 Security and operations fixes

| Fix | What it does | Where | Tests |
|---|---|---|---|
| Startup secret refusal | Outside development (any `AGENTFOX_ENVIRONMENT` other than development, dev, test, testing or local — an unrecognised value counts as production), the gateway refuses to start while `AGENTFOX_SERVICE_AUTH_SECRET` or `AGENTFOX_AUDIT_SIGNING_KEY` is unset, a default, or a placeholder our deploy files have shipped. The GitHub provisioning route refuses a published secret too, even if startup was bypassed. | `core/config.py::assert_production_secrets` | `tests/apps/gateway/test_auth_hardening.py` |
| First operator | `agentfox admin users create EMAIL` creates an operator on a fresh database without demo data, and can issue its token in the same step; the action is audited. The Docker image no longer seeds demo data on boot; a self-hoster signs in to the dashboard with that token. | `cli/auth_cli.py::create_user`, `deploy/Dockerfile`, `deploy/docker-compose.yml` | `tests/apps/cli/test_first_operator.py` |
| Token logout | `POST /api/auth/logout` revokes the presented token and only that one. GitHub sign-in keeps at most five live login tokens and revokes the oldest beyond that. | `gateway/routes/integrations.py` (`MAX_LOGIN_SESSIONS`) | `tests/apps/gateway/test_auth_hardening.py` |
| Agent keys and the kill switch | An invalid or revoked agent key is a 401 on every route, in development too; a request with no credential is still served as shadow traffic. A stopped agent is refused on every guard surface, and no approval can be granted while it is stopped. | `gateway/deps.py`, `runtime/enforcement` | `tests/apps/gateway/test_auth_hardening.py`, `tests/runtime/test_kill_switch_every_surface.py` |
| Fail modes | A policy pack's own `fail_mode` is honoured alongside the deployment's `AGENTFOX_FAIL_MODE`, so a pack that declares `fail_mode: closed` fails closed on its own. | `runtime/enforcement/enforcer.py` | `tests/runtime/test_pack_fail_mode.py` |
| Unloadable stored policy | Every stored version becomes a document through `policy/store.py::load_version_document`. A version missing a protected rule gets only that rule restored from the shipped pack, with a warning; saving a new document without it is still refused. Any other unloadable version raises `UnloadablePolicyVersion`: read-only views (coverage, effective, lint, the policy list) skip it and report it as `unloadable_policies`, and the enforcer evaluates the healthy packs and records `policy.unloadable` on the decision, blocking only for an enforce binding when the deployment or the pack is fail-closed. This replaced a production 500 on the Overview page. | `policy/store.py`, `runtime/enforcement/enforcer.py`, `discovery/threats.py` | `tests/platform/policy/test_stored_version_loading.py` |

### 7.2 New production configuration

Settings are read as `AGENTFOX_<name>` (the pre-rename `NOMETRIA_<name>` is no longer read).

| Setting | Purpose | When unset |
|---|---|---|
| `AGENTFOX_SERVICE_AUTH_SECRET`, `AGENTFOX_AUDIT_SIGNING_KEY` | Already required; now enforced at startup (§7.1). | The gateway refuses to start outside development. |
| `AGENTFOX_CRON_SECRET` (or Vercel's `CRON_SECRET`) | Bearer secret for `GET`/`POST /api/internal/jobs/run`, the job runner that drives monitors, live probes, escalation scans and the other schedules. The `Run monitors` GitHub Actions workflow calls it every 30 minutes and needs the repository secrets `AGENTFOX_API_URL` and `AGENTFOX_CRON_SECRET`. | The endpoint answers 503 and nothing scheduled runs, except by hand with `agentfox admin jobs run-due`. The workflow exits successfully without calling anything. |
| `AGENTFOX_GITHUB_WEBHOOK_SECRET` | Verifies GitHub push deliveries to `/api/integrations/github/webhook`, which queue an immediate rescan. A connection can carry its own secret instead (`POST /api/integrations/github/webhook-secret`). | With neither, every delivery is refused; scheduled rescans still run. |
| `AGENTFOX_WEBHOOK_URL`, `AGENTFOX_WEBHOOK_SECRET`, `AGENTFOX_WEBHOOK_MIN_SEVERITY` | The finding webhook. With the secret set, each request carries an HMAC signature header (`X-AgentFox-Signature`). | No webhook; with a URL but no secret, requests are unsigned. |
| `AGENTFOX_SLACK_WEBHOOK_URL`, `AGENTFOX_SLACK_MIN_SEVERITY` (default `medium`) | Slack messages for monitor findings opened, reopened or closed. A tenant can set its own channel with `PUT /api/alerts/slack`. | No deployment-wide Slack channel. |
| `AGENTFOX_SHOWCASE_ENABLED` (default `false`), `AGENTFOX_SHOWCASE_ORG_ID` (default `org_showcase`) | Runs AgentFox against its own demo agent in a dedicated tenant and publishes the result at `GET /api/public/showcase` for the `/live` page. Only the hosted deployment behind the marketing site should turn it on. | Off: the public endpoint reports the showcase as disabled. |
| `AGENTFOX_LIVE_PROBES_ENABLED` (default `true`) | Kill switch for every live probe target at once. Each target also needs its own recorded opt-in. | — |

Slack and the finding webhook send nothing while `AGENTFOX_ALLOW_EGRESS` is off. Monitors, alert
channels and probe targets add tables: run `agentfox admin db upgrade` before serving.

### 7.3 Still open from this review

§3's per-process admission and budget state is unchanged: it also applies to the circuit
breaker and to the fail-open budget. The code restructure, the last of the Nometria→AgentFox
rename and building the vendored wheels at deploy time are deferred by decision; see
[gap-analysis.md](gap-analysis.md) Part 7.

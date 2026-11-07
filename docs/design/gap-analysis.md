# Gap analysis: what is still open

**The one register of what AgentFox does not do yet.** Re-verified against `main` at release
0.5.0 (2026-11-07). Each open item names the code that shows its state; closed items are
removed rather than kept here (git history has the earlier editions). The competitive field
itself is in
[competitor-analysis.md](competitor-analysis.md); failure-mode coverage is in
[failure-modes.md](failure-modes.md) and [coverage-map.md](coverage-map.md); live
capability status is generated into [../status.md](../status.md).

**Editions.** Since 0.5.0 the repository is an Apache-2.0 open core plus a source-available
enterprise package in `ee/` (`agentfox_ee`). Compliance status, reviews and sign-off, the
risk register and board view, evidence packages, fleet monitoring with Slack alerts and
external access checks are Enterprise. Enforcement, containment, detectors, validators,
packs and retention stay in the open core. A gap below says which edition it sits in when
that matters.

Legend: ✗ absent · ◐ partial (what exists is named). Module paths are relative to
`src/agentfox/`; `agentfox_ee/` paths are under `ee/src/`.

---

## 1. Engineering gaps

### 1.1 Identity, keys and scale

| Gap | State | Evidence |
|---|---|---|
| SSO (OIDC, SAML) and SCIM | ✗ | `auth_mode` accepts `oidc` (`core/config.py`), but no IdP integration exists. Sign-in is API tokens plus GitHub sign-in (`apps/gateway/routes/integrations.py`); `User.external_id` is the seam. |
| External KMS or Vault | ◐ | Secrets are Fernet-encrypted at rest (`token_encryption_key`), and both stored-data keys rotate with `agentfox admin keys rotate` (`platform/keys/rotation.py`). Keys still come from the environment; there is no KMS or Vault client. |
| Shared state across workers | ✗ | The admission controller, the fail-open ledger and the circuit breaker are module-level, per-process state (`runtime/availability.py`, `runtime/reliability.py`). N workers get N times the declared budget. |
| Rate limiting on the control plane | ◐ | `admission_gate` (`apps/gateway/app.py`) covers every `/v1/*` request. `/api/*` is left out on purpose: it is authenticated and low-volume. |
| Background workers | ◐ | A database-backed job queue with retries, backoff and stuck-job recovery (`platform/jobs/`), drained by a cron call or `agentfox admin jobs run-due` in the calling process. No Redis or SQS worker. |
| Load testing and scale-out (NFR-3, PL-6) | ◐ | Pooling and pre-ping ship, and SQLite is refused for a multi-worker deployment. Throughput under real load is untested. |
| Credential brokerage (P2-6) | ✗ | Not built. |
| Entra Agent ID, Okta (P2-8) | ✗ | Non-human identities are modelled (`platform/identity/service.py`); no external IdP. |

### 1.2 Estate coverage

| Gap | State | Evidence |
|---|---|---|
| Live connectors to the estate (Gartner "interoperability") | ◐ | Discovery reads code and the files platforms export (`capabilities/discovery/platforms.py`: Vapi, Retell, ElevenLabs, Bland, n8n, Dify, Flowise, Langflow, Voiceflow, Dialogflow, Copilot Studio, Agentforce, Bedrock Agents, AgentCore, Lex, Genesys). Tool calls from Vapi, Retell, Copilot Studio and AgentCore Gateway are governed through their pre-tool hooks (`/v1/hooks/...`, `deploy/aws-agentcore-interceptor/`). Nothing enumerates a live account: no Bedrock console, Copilot Studio catalog, Salesforce, ServiceNow or M365 API connector. Model-provider connectors (Azure, Bedrock, Vertex, LiteLLM) are a different thing and exist. |
| Microsoft 365 Copilot and Power Platform agents | ✗ | Copilot Studio is covered as above; M365 Copilot and Power Platform are not. |
| Network-level discovery (desktop apps, IDEs) | ✗ | Not planned. |
| Catalog ingestion (P8-9: DataHub, OpenMetadata, Unity) | ✗ | Source tiers and freshness are declared by hand. |
| Retrieval-scope adapters for vector stores (I-12), OpenFGA (P10-2) | ◐ | Native entitlement engine; `openfga_url` is a declared seam (`core/config.py`), not an implementation. |
| Monitoring breadth | ◐ | GitHub is the only code host. Alerts go to Slack and the finding webhook; no PagerDuty or email. (Enterprise.) |
| Voice call records | ◐ | Personal data and secrets are masked before a Vapi or Retell call record is stored; spoken numbers are not masked yet. |

### 1.3 Governance depth (Gartner criteria and regulated buyers)

| Gap | State | Evidence |
|---|---|---|
| Dynamic risk scoring | ◐ | `agentfox_ee/compliance/risk.py::classify` proposes a class (prohibited, high, limited, minimal) from live capability, tool and data signals, with a review cycle. It is categorical, not a continuous score. (Enterprise.) |
| General workflow engine | ◐ | Runtime approvals (bound to agent, tool and arguments, redeemed once), escalation routing with owner and SLA, risk-assessment reviews, control reviews recorded as attestations with an outcome and a 90-day expiry (Enterprise), and two-person policy and MCP changes. No general assessment workflow or task routing across them. |
| Bias and fairness audits (NYC LL144, EU DSA) | ◐ | One disparate-impact probe (`capabilities/grounding/commitments.py::fairness_probe`), on the compliance path. No named audit workflow. |
| Model risk management (SR 11-7) | ✗ | Drift is measured; there is no model inventory, validation or challenge workflow. |
| Third-party AI vendor risk | ✗ | Not built. |
| Framework mappings reviewed by a qualified assessor | ◐ | Every mapping in `packs/compliance/catalog/controls/controls.yaml` is `review_status: draft`. Evidence packages include them with a `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` chip. Open mapping work is in [compliance-crosswalk-review.md](compliance-crosswalk-review.md). |
| Framework-mapping diff engine (P6-8) | ✗ | The catalog is versioned; no diff between versions. |
| Chargeback by team (P15-5) | ◐ | Budgets and cost tracking per agent (`runtime/reliability.py`); no cost report by team. |

### 1.4 Detection and failure modes

| Gap | State | Evidence |
|---|---|---|
| Stale index (F8.3, P14-5) | ✗ | No index-freshness check. |
| Self-contradiction across turns (F7.7) | ✗ | Nothing tracks an agent's earlier claims; `SelfConsistencyScorer` is an offline eval scorer for resampled outputs, not this. |
| Licensed-advice classifier (F6.2) | ◐ | Register checks are lexical and licensed per domain (`capabilities/grounding/register.py`). |
| Context stuffing that pushes out the system prompt (L1.9, P14-6) | ✗ | No context-budget governance. |
| Invalid logical inference (L0.4) | ✗ | No reasoning validator; see [coverage-map.md](coverage-map.md). |
| Instructions in images or scanned PDFs (L2.19) | ✗ | Reported as unread on the decision, never as clean. |
| Quality in languages other than English (L0.10) | ◐ | Localised number and date parsing only. |
| Model-based groundedness as the default (P4-10) | ◐ | Runs through a configured model provider beside the lexical scorer; the default is still lexical and behind Cleanlab, Vectara HHEM and similar. |
| Content-safety and jailbreak classifiers | ◐ | Wired, on by default where installed, but they need `agentfox[classifiers]` and a weights download. |
| Idempotency and compensation on effectful calls (P9-8) | ◐ | `capabilities/containment/effects.py::assess_effects` and `compensation_plan` are built and tested, but nothing on the request path calls them; only `cascade_risk` is wired (`runtime/enforcement/tool_calls.py`). |
| Sandboxed execution | ✗ | A non-goal: AgentFox governs the call into a tool, not the agent's own runtime. |

### 1.5 Evaluation

| Gap | State | Evidence |
|---|---|---|
| Eval UX depth | ◐ | Suites, CI gate, drift, red team, live probes, and an annotation queue for borderline or disagreeing results (`GET /api/eval/annotations/queue`, annotated from the run page). No dataset splits, pairwise comparison or experiment tracking. |

---

## 2. Coding agents and product surface

Open items from the Failproof AI comparison (2026-10-07). The comparison's other product
gaps are closed: `agentfox up` is the one-command setup; the Claude Code adapter binds
**Stop**, and the delivery policies (`capabilities/delivery`) steer an agent that is about
to lose finished work; adapters can return a `context` decision that lets a call through
with guidance (`harnesses/base.py`); findings reopen when the problem recurs
(`platform/ledger/findings.py`); and Codex CLI has an adapter (`harnesses/codex/`).

| Gap | State | Evidence |
|---|---|---|
| More coding-agent harnesses | ◐ | Adapters for Claude Code and Codex CLI (`src/agentfox/harnesses/`). No Cursor, Copilot CLI, Gemini CLI or others. `just new-harness` scaffolds one against the `HarnessAdapter` protocol. |
| Installing a policy pack from a remote repository | ✗ | `agentfox policy packs` has `list`, `show`, `test`, `validate`, `new` and `files`. Packs load from the wheel, `.agentfox/packs/` or an `agentfox.packs` entry point. No digest-pinned install from a repository. |
| Fleet view of developer machines | ✗ | No enrolment, per-machine policy version or rollback. |
| Smaller items | ✗ | A permission catalog with key presets; a request id on every error response; a public tracker of vendor hook-contract changes. |

### Docs site

Open items from the same comparison. Screenshots on the quickstart and task pages exist
now (`dashboard/public/docs/screens/`).

- The docs are still grouped by surface (Guides, Web app, Reference) rather than by job.
- No search.
- `llms.txt` only; no `llms-full.txt`.
- One API reference page plus the gateway's own `/openapi.json`; no page per endpoint.
- No changelog page; `CHANGELOG.md` is in the repository only.

---

## 3. Organisational and procurement gaps

None of these is code. Each needs a programme with a calendar.

| Requirement | State |
|---|---|
| SOC 2 Type II, ISO 27001 | ✗ |
| Third-party penetration test, vulnerability disclosure programme | ✗ (`SECURITY.md` gives a reporting address) |
| Completed SIG Lite or SIG Core questionnaire | ✗ |
| DPA, sub-processor register, GDPR and DPIA support | ✗ |
| BC/DR, RTO/RPO, backup and restore commitments | ✗ |
| Uptime SLA, support tiers, patch SLA | ✗ |
| Managed regions | ◐ self-host anywhere; no managed regions |
| AWS or Azure Marketplace listing | ✗ |
| Published pricing | ◐ a pricing page exists (`dashboard/app/(marketing)/pricing/`); nothing is priced |
| Analyst engagement (Gartner, Forrester) | ✗ |

RBAC with six roles and an audit log of operator actions are met in code.

---

## 4. Running in production

Install and upgrade steps, and the optional settings table, are in
[../deployment/systemd.md](../deployment/systemd.md); key rotation is in
[../deployment/key-rotation.md](../deployment/key-rotation.md). Settings are read as
`AGENTFOX_<name>` (`core/config.py`). The ones a production deployment must decide:

| Setting | What it does | When unset |
|---|---|---|
| `AGENTFOX_ENVIRONMENT` | Anything but `development`, `dev`, `test`, `testing` or `local` counts as production: `/api` needs a token and the secrets below are enforced. | Development: an unauthenticated request acts as whichever user it names. |
| `AGENTFOX_SERVICE_AUTH_SECRET`, `AGENTFOX_AUDIT_SIGNING_KEY` | The dashboard's sign-in secret and the audit-chain signing key. `core/config.py::assert_production_secrets` refuses a default or a placeholder our deploy files have shipped. | Outside development the gateway refuses to start. |
| `AGENTFOX_TOKEN_ENCRYPTION_KEY` | Encrypts every secret stored at rest. | Connecting a repository fails closed rather than storing a raw token. |
| `AGENTFOX_CRON_SECRET` (or Vercel's `CRON_SECRET`) | Bearer secret for `/api/internal/jobs/run`, which drives monitors, live probes, escalation scans, retention and key rotation. The `Run monitors` workflow (`.github/workflows/monitors.yml`) calls it every 30 minutes with the repository secrets `AGENTFOX_API_URL` and `AGENTFOX_CRON_SECRET`. | The endpoint answers 503; scheduled work runs only through `agentfox admin jobs run-due` or a systemd timer. |
| `AGENTFOX_FAIL_MODE` (default `open`) | What a check does when a detector times out or errors: `open` answers on the other detectors' findings, `closed` blocks. A pack's own `fail_mode` is honoured too. | `open`. |
| `AGENTFOX_JUDGMENT_FAIL_CLOSED` (default `false`) | Requires every workspace to deny when a judge it asked does not answer. | Each workspace decides. |
| `AGENTFOX_ALLOW_EGRESS` | Lets findings leave the machine. Slack and the finding webhook send nothing without it. | Off. |
| `AGENTFOX_SHOWCASE_ENABLED`, `AGENTFOX_SHOWCASE_ORG_ID` (`org_showcase`) | Runs the public showcase behind `/live`. Only the hosted deployment behind the marketing site turns it on. | Off. |

Run `agentfox admin db upgrade` before serving a new version. `agentfox doctor` checks
authentication, secrets and key rotation.

---

## 5. Deferred by decision

- **Building the wheels at deploy time.** The gateway on Vercel and the live demo still
  install committed wheels (`api/vendor/`, `demo/redteam-live-lang/vendor/`). A pre-commit
  hook rebuilds them when `src/agentfox/` changes, and CI fails a push that skips it.
- **Harnesses beyond Claude Code and Codex.** Cursor is next. The restructure that this
  waited on is finished ([ADR 0001](../adr/0001-repository-structure.md)).

Decided since the last edition: AgentFox stays horizontal (the PRD's positioning), and
promptfoo stays off the critical path as an optional reference (`oss-register.md`).

---

## Sources

Gartner: [Magic Quadrant for AI Governance Platforms](https://www.gartner.com/en/documents/8006369).
Procurement: [Konfirmity — SOC 2 customer security questionnaire](https://www.konfirmity.com/blog/soc-2-customer-security-questionnaire) ·
[Workstreet — security compliance questionnaires](https://www.workstreet.com/blog/security-compliance-questionnaires) ·
[Copla — vendor security assessment questionnaires](https://copla.com/blog/third-party-risk-management/guide-to-vendor-security-and-risk-assessment-questionnaires/).
Failproof AI comparison: https://docs.befailproof.ai, read 2026-10-07.
Vendor and acquisition sources for the competitive field are in
[competitor-analysis.md](competitor-analysis.md).

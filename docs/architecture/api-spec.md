# Appendix C — API Specification

Companion to [the PRD](../design/PRD.md)'s [§7 Architecture](../design/PRD.md#7-architecture) and [§6 Integration surface](../design/PRD.md#6-integration-surface). Principle **X-5**: the dashboard is a client of this API; there is no privileged back-channel. The CLI and SDK use the same surface.

Base: `http://localhost:8080` (self-host default). All control-plane routes under `/api`. Inline enforcement routes under `/v1` so they are drop-in for provider SDKs.

---

## C.1 Authentication

| Credential | Header | Used by | Scope |
|---|---|---|---|
| **Agent key** (`nom_agt_…`) | `Authorization: Bearer <key>` | Agents calling the inline gateway | Bound to one `Identity`; binds the tenant. Optional: unauthenticated inline traffic is served in the default org and recorded as shadow traffic |
| **API token** (`nom_api_…`) | `Authorization: Bearer <token>` | CLI, CI, scripts, integrations | Bound to a `User` + role. Mint with `agentfox admin auth issue` or `POST /api/tokens`; shown once |
| **Session cookie** | `agentfox_session` | Dashboard browser sessions | Holds an API token the dashboard forwards as `Bearer` |
| **Development header** | `X-AgentFox-User: <email>` | Local development and tests | Accepted only when `AGENTFOX_AUTH_MODE=development`, or `auto` with a dev/test/local environment. `agentfox admin auth status` reports it |
| **Service secret** | `X-AgentFox-Service-Secret` | Dashboard OAuth provisioning | `POST /api/auth/github/provision` only |
| **Cron secret** | `Authorization: <cron_secret>` | Scheduler | `GET` or `POST /api/internal/jobs/run` only; `AGENTFOX_CRON_SECRET` or `CRON_SECRET`; 503 if neither is set |

Keys and tokens are hashed at rest (`argon2id`), looked up by prefix, shown once at issuance, and carry `expires_at`. Credential rotation issues a new key (P2-1). Reads need any authenticated operator; writes need a role permitted for the route's family (§C.4).

---

## C.2 Inline enforcement (`/v1`)

### `POST /v1/chat/completions` — OpenAI-compatible proxy
### `POST /v1/messages` — Anthropic-compatible proxy

Drop-in: point `base_url` at the gateway, keep the existing client (X-1a, NFR-8). Request/response bodies are the provider's own. AgentFox adds optional headers:

| Header | Meaning |
|---|---|
| `X-AgentFox-Agent` | Agent slug. If absent, inferred from the credential; if neither resolves, a `shadow_agent` finding is raised (P1-2). |
| `X-AgentFox-Session` | Correlates multiple calls into one execution path. |
| `X-AgentFox-Environment` | `production` \| `staging` \| `development`. Selects the policy binding. |
| `X-AgentFox-Intent` | Declared task intent, used by intent-based containment (P3-4). |
| `X-AgentFox-Trust` | JSON map marking message indices as untrusted (`{"2":"retrieved","3":"tool_result"}`) for taint tracking. |

Response adds:

| Header | Meaning |
|---|---|
| `X-AgentFox-Trace` | Trace id — the handle for everything in Pillar 5. |
| `X-AgentFox-Verdict` | The enforced verdict: `allow` \| `tokenize` \| `mask` \| `redact` \| `abstain` \| `escalate` \| `block` |
| `X-AgentFox-Effective-Verdict` | What the policy would have done regardless of mode — differs from the verdict in observe mode |
| `X-AgentFox-Mode` | `observe` \| `enforce` for the deciding policy |
| `X-AgentFox-Decision` | Decision id. |
| `X-AgentFox-Latency-Ms` | Added enforcement latency (NFR-1 observability). |

**On block** → `HTTP 403` with `{"error": {"type": "agentfox_policy_violation", "message", "verdict", "trace_id", "decision_id", "policy_version", "rules_fired", "entities", "explanation", "suppressed"}}` (X-4: never block without an auditable reason).
**On escalate** → `HTTP 428` with `error.type = "agentfox_approval_required"` and `approval_id`
(an error status, so provider SDKs raise rather than parse a completion); poll
`GET /api/approvals/{id}` (an agent key may read its own agent's), and once it is `approved` send
the same request with `X-AgentFox-Approval: <id>` — it runs once (P2-3).
**On overload** → `HTTP 429` with `Retry-After` from the admission gate; `X-AgentFox-Priority` raises a request's priority.

### `POST /v1/guard/input` · `POST /v1/guard/output` · `POST /v1/guard/tool_call` · `POST /v1/guard/memory_write` · `POST /v1/guard/agent_message` · `POST /v1/mcp/call`

Direct enforcement without proxying — for teams that keep their own provider calls (X-1b). `guard/input` and `guard/output` read no credential. `mcp/call` governs a call to an MCP server tool, including schema-drift detection. The example below is illustrative; field names match `EnforcementResult.to_json()`.

```jsonc
// POST /v1/guard/tool_call
{
  "agent": "support-triage",
  "session_id": "s-1a2b",
  "tool": "payments.transfer",
  "arguments": {"amount": 25000, "currency": "USD", "to": "acct_991"},
  "provenance": {"to": "tool_result", "amount": "user"},   // taint sources
  "intent": "refund a duplicate charge"
}
```
```jsonc
// 200
{
  "verdict": "escalate",
  "decision_id": "dec_7f…",
  "trace_id": "trc_9c…",
  "policy_version": "pol_payments@4",
  "rules_fired": [
    {"rule_id": "payments.high_value", "effect": "escalate",
     "reason": "amount 25000 exceeds auto-approve limit 1000"},
    {"rule_id": "taint.high_impact_tool", "effect": "escalate",
     "reason": "argument 'to' originates from tool_result (untrusted)"}
  ],
  "approval_id": "apr_3d…",
  "findings": [],
  "latency_ms": 11
}
```

### `POST /v1/traces` — OTLP/HTTP ingest (X-1c)

Passive ingestion of existing OpenTelemetry spans. Accepts OTLP/JSON. Spans following OpenLLMetry semantic conventions are mapped into the agent-native span model; unrecognised spans are retained as context. This is how a team gets Pillar 1 and 5 value with *zero* integration.

Outside development the route requires a credential: an agent key (`Bearer nom_agt_…`, bound to that agent's tenant) or an operator token (`Bearer nom_api_…`) whose role may write to the registry. No credential, or an unrecognised one, is `401`; a read-only operator role is `403`. In development it accepts spans without a credential.

---

## C.3 Routes (generated)

The route tables below are generated from the running application, so they cannot drift
from the code. Regenerate after changing any route:
`uv run python scripts/gen/api_routes.py --write`. CI runs `--check`.

<!-- BEGIN GENERATED ROUTES: scripts/gen/api_routes.py --write -->

229 operations, generated from the running app's OpenAPI document. Request and response schemas: `GET /openapi.json` or the interactive `/docs`.

### Inline enforcement (`/v1`)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI-compatible inline proxy |
| `POST` | `/v1/guard/agent_message` | Authorise an inter-agent message |
| `POST` | `/v1/guard/input` | Enforce on content without proxying. |
| `POST` | `/v1/guard/memory_write` | Authorise a memory write |
| `POST` | `/v1/guard/output` | Enforce on content without proxying. |
| `POST` | `/v1/guard/tool_call` | Authorise a tool call |
| `POST` | `/v1/mcp/call` | Govern one MCP call for callers that are not in-process Python. |
| `POST` | `/v1/messages` | Anthropic-compatible inline proxy |
| `POST` | `/v1/traces` | OTLP/HTTP trace ingest |

### Platform and onboarding

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/attention` | What needs a human, ranked. The home page is built from this. |
| `GET` | `/api/detectors` | Which detectors exist, which are live, and how fast they are. |
| `POST` | `/api/detectors/{key}` | Switch a detector on or off for this workspace. Turning one on that is not |
| `GET` | `/api/health` | Liveness, plus what is currently not being checked. |
| `GET` | `/api/me` | The signed-in identity, for the account menu. |
| `GET` | `/api/memory` | List Entries |
| `POST` | `/api/memory/{entry_id}/revoke` | Pull an entry immediately — the concrete fix for 'no way to find and |
| `POST` | `/api/memory/{entry_id}/verify` | A human vouches for an entry — it stops decaying on the unverified TTL. |
| `GET` | `/api/metrics/breakdown` | Breakdown |
| `GET` | `/api/metrics/errors` | Steps that failed — a tool that threw, a model call that errored — grouped. |
| `GET` | `/api/metrics/rules` | How each rule behaved: fired, stopped something, or only watched. |
| `GET` | `/api/metrics/summary` | Summary |
| `GET` | `/api/onboarding` | Install state as a checklist, computed live. |
| `GET` | `/api/providers` | The neutrality surface, made inspectable. |
| `GET` | `/api/reliability` | Circuit-breaker state and live budget consumption. |
| `GET` | `/api/version` | Every version that participates in a decision, so a verdict can be reproduced. |
| `GET` | `/metrics` | Prometheus exposition. |

### Registry, discovery and findings (Pillar 1)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/agent-controls` | Kill-switch/quarantine state per agent. |
| `GET` | `/api/agents` | List Agents |
| `POST` | `/api/agents` | Create Agent |
| `GET` | `/api/agents/{slug}` | Get Agent |
| `PATCH` | `/api/agents/{slug}` | Update Agent |
| `GET` | `/api/agents/{slug}/access` | Get Access |
| `POST` | `/api/agents/{slug}/access` | Grant a tool, or change the existing grant for it (one grant per tool key). |
| `DELETE` | `/api/agents/{slug}/access/{capability_id}` | Remove Access |
| `POST` | `/api/agents/{slug}/kill` | Stop an agent now. Requires the stronger role — this is an incident action. |
| `GET` | `/api/agents/{slug}/lineage` | Agent Lineage |
| `GET` | `/api/agents/{slug}/posture` | Agent Posture |
| `POST` | `/api/agents/{slug}/quarantine` | Stop an agent while you investigate. Reversible and audited. |
| `POST` | `/api/agents/{slug}/resume` | Restart a stopped agent. Deliberately the same role as `kill` — restarting |
| `POST` | `/api/discovery/scan` | Sweep: lineage, unowned agents, registry drift, identity posture, delegation shape. |
| `GET` | `/api/discovery/shadow` | Shadow Agents |
| `POST` | `/api/discovery/submit` | Submit a redacted local scan for review |
| `GET` | `/api/findings` | List Findings |
| `GET` | `/api/findings/types` | Every finding type: its title, default severity, what it means and who raises it. |
| `GET` | `/api/findings/{finding_id}` | Get Finding |
| `PATCH` | `/api/findings/{finding_id}` | Patch Finding |
| `GET` | `/api/mcp-servers` | List Mcp |
| `POST` | `/api/mcp-servers` | Register an MCP server, and start monitoring it for tool drift. |
| `POST` | `/api/mcp-servers/{name}/scan` | Scan Mcp |
| `POST` | `/api/mcp-servers/{name}/tools` | Snapshot a listing *and* register each tool in the registry. |
| `GET` | `/api/tools` | List Tools |
| `POST` | `/api/tools` | Create Tool |

### Identity, credentials, approvals (Pillar 2)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/approvals` | List Approvals |
| `GET` | `/api/approvals/{approval_id}` | One approval. An operator may read any; an agent key only its own agent's. |
| `POST` | `/api/approvals/{approval_id}/approve` | Approve |
| `POST` | `/api/approvals/{approval_id}/deny` | Deny |
| `POST` | `/api/credentials/{credential_id}/revoke` | Revoke |
| `GET` | `/api/identities` | List Identities |
| `POST` | `/api/identities/{identity_id}/capabilities` | Add Capability |
| `POST` | `/api/identities/{identity_id}/check` | Check |
| `POST` | `/api/identities/{identity_id}/credentials` | Issue |
| `POST` | `/api/identities/{identity_id}/rotate` | Rotate |
| `GET` | `/api/tokens` | List Tokens |
| `POST` | `/api/tokens` | Mint a token for the caller's own use. The raw value is returned once — |
| `POST` | `/api/tokens/{token_id}/revoke` | Revoke Token |

### Policy (Pillars 2, 3, 12)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/policies` | List Policies |
| `POST` | `/api/policies` | Upsert Policy |
| `GET` | `/api/policies/effective` | The policy actually in force for a subject, with per-rule provenance. |
| `GET` | `/api/policies/lint` | Policy lint. `passed` is false when critical/high findings exist. |
| `POST` | `/api/policies/simulate` | Replay recorded traffic against a candidate policy. |
| `POST` | `/api/policies/validate` | Validate Policy |
| `GET` | `/api/policies/{key}` | Get Policy |
| `GET` | `/api/policies/{key}/canary` | Get Policy Canary |
| `POST` | `/api/policies/{key}/canary/advance` | Check the candidate cohort's health and advance, hold, or auto-roll-back. |
| `POST` | `/api/policies/{key}/canary/rollback` | Rollback Policy Canary |
| `POST` | `/api/policies/{key}/canary/start` | Start Policy Canary |
| `POST` | `/api/policies/{key}/mode` | Promote or demote a policy, optionally making a saved version live. |
| `GET` | `/api/policies/{key}/rego` | Get Rego |
| `POST` | `/api/policies/{key}/rules/{rule_id}` | Change one rule's action or switch it off, as a new saved version. |
| `POST` | `/api/policies/{policy_id}/approve` | Approve Policy |
| `POST` | `/api/policies/{policy_id}/reject` | Reject Policy |

### Guardrail tuning (Pillar 3)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/guardrails/feedback` | List Feedback |
| `POST` | `/api/guardrails/feedback` | "This was wrong", attached to the decision it is about. |
| `GET` | `/api/guardrails/latency` | Per-detector and per-agent p50/p95/max, plus how often the budget degraded. |
| `GET` | `/api/guardrails/precision` | Per-detector precision with the label count beside it. |
| `GET` | `/api/guardrails/recommendations` | Threshold suggestions, including the honest refusal to make one. |
| `GET` | `/api/guardrails/suppressions` | List Suppressions |
| `POST` | `/api/guardrails/suppressions` | Accept a false positive as a scoped, expiring exception. |
| `DELETE` | `/api/guardrails/suppressions/{suppression_id}` | Delete Suppression |

### Evaluation and red team (Pillar 4)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/eval/annotations/queue` | Eval results a human should look at: score within `band` of the scorer's |
| `GET` | `/api/eval/drift` | Read-only. Viewing drift persists nothing, so the number of drift findings |
| `POST` | `/api/eval/gate` | The CI entry point. Non-zero exit maps from ``passed: false``. |
| `POST` | `/api/eval/online` | Run Online |
| `POST` | `/api/eval/results/{result_id}/annotate` | Record a human's judgment on a borderline eval result. Requires a note — |
| `GET` | `/api/eval/runs` | List Runs |
| `POST` | `/api/eval/runs` | Create Run |
| `GET` | `/api/eval/runs/{run_id}` | Get Run |
| `GET` | `/api/eval/scorers` | Scorers |
| `GET` | `/api/eval/slos` | Slos |
| `POST` | `/api/eval/slos` | Declare a reliability target for one agent+scorer pair. |
| `GET` | `/api/eval/suites` | List Suites |
| `POST` | `/api/eval/suites` | Create Suite |
| `GET` | `/api/eval/suites/{key}` | Get Suite |
| `POST` | `/api/eval/suites/{key}/cases` | Add Case |
| `POST` | `/api/eval/suites/{key}/cases/from-trace` | Promote a production failure into a regression test. |
| `GET` | `/api/probes/targets` | List Targets |
| `POST` | `/api/probes/targets` | Register a target. It is created disabled; nothing is sent until opt-in. |
| `GET` | `/api/probes/targets/{target_id}` | Get Target |
| `PATCH` | `/api/probes/targets/{target_id}` | Update Target |
| `GET` | `/api/probes/targets/{target_id}/campaigns` | Campaigns |
| `POST` | `/api/probes/targets/{target_id}/opt-in` | Opt In |
| `POST` | `/api/probes/targets/{target_id}/opt-out` | Opt Out |
| `POST` | `/api/probes/targets/{target_id}/run` | Probe the target now. Same consent and caps as a scheduled run, and refused |
| `GET` | `/api/probes/warning` | What a person must read before enabling probes, plus the probe library, the |
| `GET` | `/api/redteam/campaigns` | List Campaigns |
| `POST` | `/api/redteam/campaigns` | Enqueues through jobs_db and processes within this same request |
| `GET` | `/api/redteam/probes` | List Probes |

### Audit, traces and evidence (Pillar 5)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/audit/checkpoint` | Checkpoint |
| `GET` | `/api/audit/entries` | Audit Entries |
| `POST` | `/api/audit/verify` | Verify Chain |
| `GET` | `/api/evidence` | List Evidence |
| `POST` | `/api/evidence` | Enqueues through jobs_db rather than calling evidence.build() |
| `GET` | `/api/evidence/{package_id}/download` | Download Evidence |
| `GET` | `/api/export/siem` | Export Siem |
| `POST` | `/api/legal-holds` | Place Hold |
| `GET` | `/api/retention` | Retention |
| `GET` | `/api/traces` | List Traces |
| `GET` | `/api/traces/resolve` | Their run id → our governance decision. |
| `GET` | `/api/traces/{trace_id}` | Get Trace |

### Compliance and risk (Pillar 6)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/board` | Board |
| `GET` | `/api/compliance/status` | Compliance Status |
| `GET` | `/api/controls` | List Controls |
| `POST` | `/api/controls/compute` | Compute Controls |
| `POST` | `/api/controls/sync` | Load the static control catalog and obligation calendar from YAML into this |
| `GET` | `/api/frameworks` | Frameworks |
| `POST` | `/api/frameworks/review` | Step 3 of the mapping review gate. |
| `GET` | `/api/frameworks/{key}` | Framework |
| `GET` | `/api/obligations` | Obligations |
| `POST` | `/api/risk/assessments/{slug}` | Create Assessment |
| `GET` | `/api/risk/classify/{slug}` | Classify Agent |
| `GET` | `/api/risk/register` | Get Register |

### Answerability, sources, entitlement, escalation (P7, P8, P10, P11)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/answerability/boundaries` | Every declared knowledge boundary, or one agent's with `?agent=<slug>`. |
| `PUT` | `/api/answerability/boundary` | Write Boundary |
| `POST` | `/api/answerability/check` | Would this question be refused, and what would we say instead? |
| `GET` | `/api/answerability/report` | Abstention and over-refusal side by side. |
| `POST` | `/api/entitlement/filter` | Return only what this human may see, and record what was withheld. |
| `GET` | `/api/entitlement/grants` | List Grants |
| `POST` | `/api/entitlement/grants` | Add Grant |
| `GET` | `/api/entitlement/over-permission` | How much more the agent can reach than its callers are entitled to. |
| `GET` | `/api/entitlement/principals` | List Principals |
| `PUT` | `/api/entitlement/principals` | Put Principal |
| `GET` | `/api/escalation/conversations/{session_id}` | The transcript plus why the policy did or didn't fire on it. |
| `GET` | `/api/escalation/handoffs` | List Handoffs |
| `POST` | `/api/escalation/handoffs/{handoff_id}/acknowledge` | Acknowledge |
| `GET` | `/api/escalation/missed` | **The 31% control.** Conversations that qualified for a hand-off and got none. |
| `GET` | `/api/escalation/policy` | Read Policy |
| `PUT` | `/api/escalation/policy` | Write Policy |
| `GET` | `/api/escalation/report` | Report |
| `POST` | `/api/escalation/scan` | Run detection and act on it: findings, retroactive hand-offs, SLA breaches. |
| `POST` | `/api/escalation/turns` | Record one turn with its signals. |
| `GET` | `/api/sources` | List Sources |
| `PUT` | `/api/sources` | Register or re-tier a source. |
| `POST` | `/api/sources/assess` | Would this answer, from these sources, pass? |
| `POST` | `/api/sources/connections` | Attach a real connector to a registered source — a database or an |
| `POST` | `/api/sources/context-check` | Would this document or chunk set be fit to enter the corpus? |
| `GET` | `/api/sources/health` | Which registered sources are stale, deprecated, or unowned. |
| `DELETE` | `/api/sources/{key}` | Retire a source. Deprecates by default rather than deleting. |
| `POST` | `/api/sources/{key}/validate` | Actually fetch the source and check its content, rather than trust the tier. |

### Memory and inter-agent messaging (P16, P17)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/agent-messages` | List Messages |
| `GET` | `/api/agents/{slug}/signing-key` | Key Status |
| `POST` | `/api/agents/{slug}/signing-key` | Mint (or rotate) an agent's HMAC signing key. Shown once — like an API |

### Jobs, monitors and integrations

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/agents/{agent_id}/approve` | Approve Agent |
| `POST` | `/api/agents/{agent_id}/reject` | Reject Agent |
| `DELETE` | `/api/alerts/slack` | Stop sending this tenant's alerts to its own Slack channel. |
| `GET` | `/api/alerts/slack` | Whether this tenant has its own Slack channel, and whether alerts can leave at all. |
| `PUT` | `/api/alerts/slack` | Send this tenant's monitor alerts to its own Slack incoming webhook. |
| `POST` | `/api/alerts/slack/test` | Send a test message to every channel this tenant's alerts go to, now. |
| `POST` | `/api/auth/github/provision` | Find-or-create the user behind a GitHub identity, and mint them a token. |
| `POST` | `/api/auth/logout` | Revoke the bearer token this request presents — the dashboard's Sign Out. |
| `POST` | `/api/integrations/github/connect` | Connect |
| `GET` | `/api/integrations/github/repos` | List Repos |
| `POST` | `/api/integrations/github/scan` | Trigger Scan |
| `GET` | `/api/integrations/github/scans/{scan_id}` | Get Scan |
| `POST` | `/api/integrations/github/webhook` | GitHub push webhook: a signed push to a monitored repository queues a rescan. |
| `POST` | `/api/integrations/github/webhook-secret` | Create or replace the GitHub connection's push-webhook secret (shown once). |
| `POST` | `/api/integrations/hosted-api/scan` | Scan Hosted Api |
| `GET` | `/api/internal/jobs/run` | The cron entry point. GET because that is what Vercel Cron sends; POST for |
| `POST` | `/api/internal/jobs/run` | The cron entry point. GET because that is what Vercel Cron sends; POST for |
| `GET` | `/api/jobs` | Includes dead-lettered jobs by default — that's the point (jobs.py's |
| `GET` | `/api/jobs/{job_id}` | Get Job |
| `POST` | `/api/jobs/{job_id}/retry` | Retry Job |
| `GET` | `/api/monitors` | Every monitor in the tenant, with its last result and when it next runs. |
| `POST` | `/api/monitors` | Watch a source by hand. The first run stores a baseline; later runs report changes. |
| `DELETE` | `/api/monitors/{monitor_id}` | Stop watching a source. Its findings are kept. |
| `GET` | `/api/monitors/{monitor_id}` | One monitor, with the findings it raised that are still open. |
| `PATCH` | `/api/monitors/{monitor_id}` | Rename, retune the interval, change config, or pause/resume (``enabled``). |
| `POST` | `/api/monitors/{monitor_id}/pause` | Stop scheduled runs. Open findings stay open; nothing is closed while paused. |
| `POST` | `/api/monitors/{monitor_id}/resume` | Resume scheduled runs from the monitor's next due time. |
| `POST` | `/api/monitors/{monitor_id}/run` | Run one monitor now, through the job queue, and return its result. |

### Playground (unauthenticated, rate-limited)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/playground/sessions` | Create a playground sandbox. |
| `POST` | `/api/playground/sessions/{session_id}/chat` | Chat |
| `POST` | `/api/playground/sessions/{session_id}/enforce` | Flip the baseline policy observe -> enforce (or back) for this sandbox only. |
| `GET` | `/api/playground/sessions/{session_id}/state` | Everything the live sidebar needs: recent traces (decisions + detector runs |
| `POST` | `/api/playground/sessions/{session_id}/tool-call` | Try a tool call directly, with no model in the loop. |

### Public showcase (unauthenticated, cached, rate-limited)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/public/showcase` | AgentFox probing its own demo agent: recent runs, attacks attempted, contained |

### Other

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Name the service and say where to go next. Unauthenticated. |
| `POST` | `/api/business/compile` | Compile written policy into rules and questions. Nothing is saved. |
| `GET` | `/api/business/rules` | List Business Rules |
| `POST` | `/api/business/rules` | Save Business Rule |
| `POST` | `/api/business/rules/{key}/mode` | Business Rule Mode |
| `GET` | `/api/coverage/threats` | Every published threat, and what this deployment actually does about it. |
| `GET` | `/api/custom-rules` | Get Custom Rules |
| `POST` | `/api/custom-rules` | Post Custom Rule |
| `POST` | `/api/custom-rules/try` | Match one text against a rule that has not been saved. Records nothing. |
| `DELETE` | `/api/custom-rules/{key}` | Remove Custom Rule |
| `POST` | `/api/import/{tool}` | Apply Import |
| `POST` | `/api/import/{tool}/plan` | Plan Import |
| `GET` | `/api/judgment/posture` | What is in force, what may be changed, and what the deployment forbids. |
| `PUT` | `/api/judgment/posture` | Replace the posture, refusing anything the deployment does not permit. |
| `GET` | `/api/library/packs` | List Packs |
| `POST` | `/api/library/packs/{pack_id}/install` | Install Pack |
| `GET` | `/api/proposals` | List change proposals, filtered by status, kind and scope. |
| `GET` | `/api/proposals/{proposal_id}` | One proposal with its diff, evidence, proof and decisions. |
| `POST` | `/api/proposals/{proposal_id}/apply` | Apply an approved proposal, or settle one whose canary has finished. |
| `POST` | `/api/proposals/{proposal_id}/decide` | Approve or reject; an org-level loosening needs two different approvers. |
| `POST` | `/api/proposals/{proposal_id}/rollback` | Undo an applied or canaried proposal through its applier. |
| `POST` | `/api/proposals/{proposal_id}/verify` | Record whether an applied change worked; ``verified: false`` rolls it back. |
| `POST` | `/api/waitlist` | Record an address. Unauthenticated, idempotent, and it sends nothing anywhere. |
| `GET` | `/health` | The same payload as `/api/health`, at the path probes default to. |

<!-- END GENERATED ROUTES -->

Not implemented, although earlier drafts of this appendix listed them: `/api/users` and
`/api/roles` (users are provisioned through sign-in and `agentfox admin auth`), policy
`/versions` and `/bind` (replaced by `POST /api/policies` versioning, `/{key}/mode` and
canary rollout), `POST /api/traces/{id}/replay` (use `POST /api/policies/simulate`),
`POST /api/eval/compare`, and `POST /api/compliance/packs/{key}/import`.

---

## C.4 Role → permission matrix

Every authenticated role can read. Writes are gated per route family by `WRITE_ROLES` in
`src/agentfox/apps/gateway/deps.py`, which this table mirrors:

| Write family | owner | admin | security | compliance | developer | auditor |
|---|---|---|---|---|---|---|
| `registry` (agents, tools, MCP servers, discovery, findings triage) | ✓ | ✓ | ✓ | — | ✓ | — |
| `identity` (credentials, capabilities, kill/resume) | ✓ | ✓ | ✓ | — | — | — |
| `approvals` (decide) | ✓ | ✓ | ✓ | — | — | — |
| `policy` (author, simulate, canary) | ✓ | ✓ | ✓ | — | ✓ | — |
| `policy_production` (change a policy's mode) | ✓ | ✓ | ✓ | — | — | — |
| `eval` (suites, runs, baselines, red team) | ✓ | ✓ | — | — | ✓ | — |
| `compliance` (controls, risk, framework review) | ✓ | ✓ | — | ✓ | — | — |
| `evidence` (packages, checkpoints) | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| `suppressions` (silence a detector) | ✓ | ✓ | ✓ | — | — | — |
| `jobs` (retry dead-lettered work) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `judgment_posture` (which judgment tiers run, and what leaves the box) | ✓ | ✓ | ✓ | — | — | — |
| `users` | ✓ | ✓ | — | — | — | — |

Filing guardrail feedback (a false positive) is open to any reader; *acting* on it by
suppressing a detector is a security decision, hence the separate family.

`judgment_posture` excludes `developer` for the same reason. A developer may change
thresholds and run evaluations all day; deciding that a customer's support ticket may
be sent to a third-party model is not a developer's call. It is also the one write in
this table that cannot exceed a bound set outside the product: `allow_egress` and
`judgment_pii_egress` come from the process environment and act as a ceiling, so a
posture write may narrow them and never widen them. Attempting to widen returns `409`
with the reason, rather than storing a preference that silently does nothing — see
`PUT /api/judgment/posture` and `src/agentfox/capabilities/judgment/posture.py`.

---

## C.5 Conventions

- **Errors**: control-plane routes use FastAPI's `{"detail": ...}` body with the HTTP status; inline `/v1` routes use the `{"error": {...}}` shape in §C.2. RFC 7807 is not implemented.
- **Pagination**: list routes take `limit` (bounded per route, e.g. ≤500 for memory, ≤1000 for guardrail feedback). There is no cursor pagination.
- **Idempotency**: `Idempotency-Key` is not implemented. Creation routes that take a natural key (agent slug, policy key, source key) upsert on it.
- **Versioning**: `/api` is v1 implicitly; breaking changes go to `/api/v2`. `/v1` inline routes track provider compatibility, not our version.
- **Rate limiting**: `/v1/*` goes through the admission gate (`429` + `Retry-After`); the playground is rate-limited per IP.
- **Audit**: security-relevant mutations (policy mode changes, kill switch, credential issue/revoke, approvals, token listing) write an `AuditEntry` or system-audit entry; the chain is verifiable with `POST /api/audit/verify` or `agentfox report verify`.

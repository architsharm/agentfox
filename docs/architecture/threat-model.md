# Appendix E — Threat Model

Two threat models, and conflating them is a common failure in this category:

- **E.1 — Threats to the customer's agents.** What the product defends against. Drives Pillars 3, 2 and 4.
- **E.2 — Threats to AgentFox itself.** We sit inline on the customer's critical path and hold their most sensitive text. We are a high-value target and a potential single point of failure.

Taxonomy anchors: OWASP LLM Top 10 (2025), OWASP Agentic Threats T1–T15, MITRE ATLAS. Mapped to controls in [Appendix B](../design/control-catalog.md).

---

## E.1 Threats to the customer's agents

### E.1.1 Injection & instruction hijacking

| Threat | Vector | Control | Residual risk |
|---|---|---|---|
| **Direct prompt injection** — user overrides the system prompt | User message | NOM-RTG-01 (P3-1): heuristic + structural + classifier detection, over normalised views of the text (homoglyphs, zero-width and encoded payloads, letter-spaced words, instructions hidden in markup a reader would not see) | Novel phrasings evade classifiers. Mitigated by defence-in-depth: even a successful injection must still pass tool authorisation (NOM-RTG-04). |
| **Indirect prompt injection** — payload arrives via a retrieved document or tool result | RAG chunk, web page, tool response, email body, tool-call arguments | P3-1 runs on **all** untrusted surfaces, not just user input, including `tool_args`; taint tagging marks the content | The highest-severity realistic attack on agents. Our answer is not "detect every payload" — it is "a tainted argument cannot reach an irreversible tool without approval" (P3-4). |
| **Sub-agent / A2A poisoning** | Output of one agent becomes input to another | Taint propagates across delegation; `max_taint` on capabilities | Cross-process propagation is MVP-partial (P2-5). |
| **Memory poisoning** (Agentic T1) | Persisted conversation/vector memory | Detectors run on memory reads; drift + red-team probes | We do not secure the vector store itself (§2.3 non-goal). |

**The architectural position worth stating.** Detection of injection is a losing arms race played alone. The durable defence is *containment*: assume the model can be convinced of anything, and constrain what a convinced model is permitted to do. That is why P3-4 (intent-based tool containment with argument provenance) is the differentiator and P3-1 is table-stakes.

### E.1.2 Data exposure

| Threat | Vector | Control |
|---|---|---|
| PII to a third-party model | Prompt construction | NOM-RTG-02 (P3-2) inbound Presidio-backed detection + redact/block |
| PII/secret leakage to a user or tool | Model output, tool arguments | NOM-RTG-02/03 outbound; both directions is the requirement |
| Credential exfiltration | Agent holds long-lived secrets | NOM-RTG-03 detection today; NOM-IAM-01 + credential brokerage (P2-6) removes the class — Phase 2/3 |
| System-prompt leakage (LLM07) | Extraction prompts | Output detector for prompt-shaped content + canary tokens |
| Exfiltration via inference API (ATLAS AML.T0024) | High-volume probing | NOM-RTG-08 consumption bounds + behavioural anomaly (P4-3d) |

### E.1.3 Excessive agency & tool abuse

| Threat | Control |
|---|---|
| Agent takes an irreversible action it should not (LLM06, Agentic T2) | NOM-IAM-02 default-deny least privilege with **argument-level** constraints; NOM-IAM-03 HITL on `irreversible` tools. An approval is bound to the agent, tool and arguments a person saw, lets exactly one retry through (`approved → used`), and cannot be granted while the agent is killed or quarantined |
| Privilege escalation via delegation (T3) | NOM-IAM-05 — child ⊆ parent enforced at write time |
| Confused deputy — agent used as a proxy to reach data the caller cannot | Capabilities bound to the *identity*, evaluated per call; taint provenance in the decision |
| Runaway loop / resource exhaustion (LLM10, T4) | NOM-RTG-08 depth + budget limits, loop breaking |
| Tool poisoning — malicious instructions inside an MCP tool description; silent schema swap | NOM-DSC-05 — snapshot digests, description-injection and poisoning-pattern scanning (`agentfox scan mcp` exits 1 on a critical finding), pinning; an `mcp_server` monitor re-reads a remote server's listing on a schedule and raises drift as a finding |
| A coding agent widens its own permissions by running the CLI | The coding-agent harness turns every `agentfox` command that changes what is blocked or granted (`permit`, capability and enforcement commands) into a permission prompt for the person (`harness/scripts/guard_blocking_commands.py`) |

### E.1.4 Correctness failures (the pillar security vendors omit)

| Threat | Control |
|---|---|
| **Silent failure** — plausible, confident, wrong (~78% of failures) | NOM-EVL-03 (P4-3) — groundedness, self-consistency, contract violation, behavioural anomaly, hedging, task-completion |
| Regression on release | NOM-EVL-01 CI gating |
| Drift after release | NOM-EVL-02 online scoring + PSI/KS |
| Cascading hallucination across agents (T5) | Groundedness scored at each hop; lineage shows blast radius |
| Undetected model substitution by a provider | Cross-model comparison (P4-8) + behavioural envelope |

### E.1.5 Repudiation

| Threat | Control |
|---|---|
| "Prove what the agent did on 3 March" (T8) | NOM-AUD-01 full execution path; NOM-AUD-02 tamper-evident chain |
| Insider alters history to hide an incident | Hash chain + checkpoints signed with a key outside the app DB; `auditor` role cannot mutate |
| Policy retro-fitting — "that rule was always on" | `PolicyVersion` immutability; every `Decision` binds the exact version in force |

---

## E.2 Threats to AgentFox

### E.2.1 We are inline on the critical path

| Threat | Impact | Mitigation |
|---|---|---|
| **Gateway outage takes the customer's agent down** | Catastrophic — the fastest way to be removed from production | NFR-2. P3-7 fail-open per policy and environment, chosen deliberately and audited; a pack's own `fail_mode` is honoured. A stored policy version that no longer validates no longer fails the request: it is skipped under the fail mode and named in the decision (`policy.unloadable`). SDK path degrades to local-only enforcement. **A governance tool that becomes an outage is uninstalled the same week.** |
| **Latency regression** | We become a performance problem | NFR-1 as a tested budget in CI; concurrent detectors with per-detector timeouts; heuristic fast path before any model-based detector; degrade-to-observe over budget |
| **False blocks** (PRD R3) | Trust destroyed; product disabled and never re-enabled | Observe mode by default; P2-7 simulation before enforcement; per-decision override with feedback; per-detector precision tracked and surfaced (P3-11) |

### E.2.2 We hold the most sensitive text in the company

| Threat | Mitigation |
|---|---|
| Our store becomes a new PII honeypot (PRD R8) | **Redaction at capture** (P5-5) — findings store offsets and redacted samples, not raw values. Retention bounded per data class. Encryption at rest and in transit. |
| Exfiltration through our own telemetry | Zero egress by default (NFR-4). No phone-home. Self-host is the only MVP mode. |
| Compromise of the signing key ⇒ forged checkpoints | Key outside the application database; customer-held in self-host; checkpoint verification is independent of us |
| Supply-chain compromise of a wrapped OSS dependency | Pinned versions, hashes, SBOM; adapter seam allows removing any single dependency (Appendix A exposure column) |

### E.2.3 We are a governance product, so our own governance is scrutinised

| Threat | Mitigation |
|---|---|
| Our audit chain has a bug ⇒ every compliance claim is void | Chain verification is unit- and property-tested against insertion, deletion, reordering and mutation; verification is a pure function over exported rows |
| A detector silently stops running and controls report `effective` | `DetectorRun.status` is recorded per request; NOM-RTG-06 makes degradation a *finding*; control status computed from coverage, not from configuration |
| Draft framework mappings presented as authoritative | `review_status` gate; DRAFT badge in UI; drafts ship in evidence packages chip-labeled `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` rather than excluded (Appendix B §B.6) |
| We claim coverage we do not have | Declared gap list per framework (Appendix B §B.4), rendered next to every coverage claim |

### E.2.4 Privileged position abuse

We can read every prompt and output the customer's agents produce. Controls: RBAC with an `auditor` role that cannot mutate; every access to traces and evidence writes its own `AuditEntry` (§C.5 — who looked at the evidence is audit-relevant); no support back-channel into customer data in self-host; the customer holds the signing key.

### E.2.5 The improvement loop is itself an attack surface

A loop that learns from labels and traffic, and changes configuration, is an agent with write access to
our own guardrails. It is governed as one: every change is a `ChangeProposal`, proven before it is staged,
attributable on the audit chain under `actor_type="automation"`, reversible, and rate-limited. The rules
below live in `capabilities/improvement/contract.py` and are tested exhaustively, because their failure would turn a
governance product into one that quietly rewrites itself.

| Threat | Vector | Control | Residual risk |
|---|---|---|---|
| **Label poisoning** — flood false-positive labels to justify raising a cut-off or suppressing a detector | Guardrail feedback, eval annotations | Every label audited; actor taken from authentication; one label per decision per person; auditors cannot label; proposals require distinct labellers and are proven by replay and held-out recall before staging | A colluding group of real, authorised labellers. Mitigated by the direction rule: the change they could induce loosens detection, and a loosening is never automatic |
| **Traffic shaping** — make a grant look used, or drift a baseline slowly enough to pass | Crafted production traffic | Automation only ever tightens; robust statistics over hold-out windows; proposals carry their evidence window for review | A slow, patient attacker shifting what "normal" means over months |
| **Insider laundering** — a deliberate loosening dressed as an automated proposal | A privileged operator | `may_apply_automatically` refuses every loosening at every autonomy level; an org-level loosening needs two distinct named approvers; the diff and its evidence are on the chain | Two colluding approvers. The same residual as any two-person control |
| **Goodhart's law** — the loop optimises the benchmark it is scored against | The loop's own proof step | Held-out campaigns with fresh seeds; the loop never tunes against its own gate. Observed in practice: obfuscation "detections" that were curly apostrophes | A proof set that drifts from real attacks over time |
| **A runaway improver** — a faulty change class applies many edits before anyone looks | A bug in a proposal generator | Daily per-tenant cap on automated applies; a rollback-rate budget that demotes the class; `improvement_frozen` kill switch; canary staging with a two-way health gate | Damage within one day's cap before the budget trips |
| **A quietly loosened control ships through canary** | A candidate that blocks *less* | The canary gate rolls back in both directions, with a minimum dwell time per step | A loosening too small to cross `max_block_rate_drop` |
| **Privacy leak through learned artefacts** | Raw conversation text, span attributes and approval arguments copied into a learned corpus | Redaction before anything is learned; learned artefacts carry provenance so deletion cascades; learning jobs bind to one tenant and never run in `system_scope` | Retention enforcement is not yet implemented for source tables (declared gap) |
| **Approval fatigue** — people approve without reading | Proposal volume | Dedupe by fingerprint; rank by impact; cap open proposals per owner; measure time-to-decision | Fatigue that looks like diligence |


### E.2.6 The control plane and what we expose

The gateway is reachable by agents, operators, the dashboard, schedulers and (for two
routes) the public. Each of those is an attack surface on us rather than on the customer's
agents.

| Threat | Vector | Mitigation |
|---|---|---|
| **Owner takeover through a published secret** | The service secret mints an owner token for any GitHub identity; the signing key makes the chain tamper-evident. Both ship with development defaults that are in this repository | Outside a development environment the process refuses to start while either is unset or a published value (`assert_production_secrets`, `InsecureConfigurationError`); `docker-compose.yml` will not start without both. The image no longer seeds demo users on boot; the first operator is created explicitly (`agentfox admin users create`) |
| **Impersonating an agent with a made-up key** | A `nom_agt_…` string that does not verify | A presented agent key that does not verify (wrong, revoked, expired, or a sandbox's) is a **401** on every route. No credential at all is still served, as shadow traffic in the default tenant, so it is observed rather than attributed to the agent the body names |
| **A stopped agent keeps acting** | The kill switch checked on only some surfaces; an approval granted during an incident | The kill switch is checked at the top of `Enforcer.evaluate()`, so every surface that reaches a decision refuses a killed or quarantined agent (completions, tool calls, guard input/output, memory writes, agent messages, streams). Approving is refused while the agent is stopped |
| **Stolen operator session** | A dashboard token that outlives sign-out | Signing out revokes that session's token; a GitHub sign-in keeps at most 5 live login tokens and revokes the oldest; tokens expire by default, and every revocation is recorded on the audit chain |
| **SSRF through a URL we fetch** | An OpenAPI spec, a remote MCP server, a provenance source or a probe target pointing at loopback, the private network or cloud metadata | `core/outbound.py` (`guarded_get`, `guarded_post`): http(s) only; every address the name resolves to is vetted and the connection pinned to the vetted one (no DNS rebinding); private and loopback refused unless `outbound_allow_private_hosts`; link-local (metadata), multicast and reserved always refused; GET redirects re-vetted per hop and never handed the caller's `Authorization`; POST redirects refused; bodies read under a size cap |
| **Forged push webhook** | `POST /api/integrations/github/webhook` is unauthenticated by nature | Acted on only when `X-Hub-Signature-256` verifies against the deployment's `github_webhook_secret` or the tenant connection's own (encrypted) secret, and only for monitors of tenants whose secret signed it. 503 when no secret is configured, 401 on a bad signature, 413 over 5 MB. A verified push can only queue a rescan of a repository already being monitored, and only for the watched branch |
| **Turning live probes into an attack tool** | A probe target URL pointing at someone else's system; probing at volume | Targets are created disabled; opting in is a separate call by `owner`/`admin`/`security` that must carry the exact warning text and records who agreed, on the target and the audit chain. Probes go only to the host registered at opt-in (checked before DNS), through `guarded_post`, with redirects refused; changing the URL clears the opt-in. Per-target probes per run, rate, interval and timeout are clamped to hard caps, jobs are bounded in targets and wall-clock, and `AGENTFOX_LIVE_PROBES_ENABLED=false` stops all of it. Probe requests carry `X-AgentFox-Probe` so the target can tag or drop them |
| **Probe data mistaken for production data** | Probe traffic written to a tenant's traces | Probe sessions start `afx-probe:`, campaigns are `runner="live"`, findings are `live_probe_escape`: three markers that separate them |
| **Abuse of the public showcase** | `GET /api/public/showcase` is unauthenticated | Off unless `AGENTFOX_SHOWCASE_ENABLED`; reads only the dedicated showcase tenant through the same session-level tenant filter as everything else; returns counts, probe keys and finding titles, never probe text or replies; cached for a minute and rate limited to 30 requests per minute per client address |
| **Data leaving through alerts** | Slack messages carry finding titles out of the deployment; a tenant-set URL could point anywhere | Nothing is sent with `allow_egress` off. A tenant's channel must be an `https://hooks.slack.com/` URL, is stored encrypted, and redirects are not followed. Messages are queued on the session and sent only after commit, so rolled-back work sends nothing |
| **Unauthenticated cron trigger** | `/api/internal/jobs/run` drives every tenant's scheduled work | Requires `AGENTFOX_CRON_SECRET` or `CRON_SECRET`, compared in constant time; 503 when neither is set. Running it is idempotent: schedules and monitors refuse to run before they are due |

The admission controller and rate limiters (including the showcase limiter) are per-process,
so N replicas allow N times the stated rate. That is a known, declared limitation, not a
mitigation we claim at cluster scope.

---

## E.3 Assumptions & out of scope

**Assumed:** the customer's network/host security, their IdP, their model provider's own security, and the sandbox isolating tool execution (§2.3 — E2B/Modal/Daytona's job, not ours).

**Explicitly out of scope:** training-time attacks on *models* and model supply chain (ATLAS training techniques, LLM04 in its training sense) — AgentFox does not train a model. Learning from labels and traffic to change *configuration* is in scope, and is covered in §E.2.5; vector-store security (LLM08 beyond symptom detection); T11 Unexpected RCE (sandbox concern); T14/T15 human-directed social attacks; non-text modalities in MVP (§6.3).

**Stated because a compliance product must:** none of the above is a claim of completeness. Appendix B §B.4 carries the framework gap list, and this section is its threat-side counterpart.

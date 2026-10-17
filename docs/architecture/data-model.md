# Appendix D — Data Model

Companion to [the PRD](../design/PRD.md). Implemented in `src/agentfox/core/models/` (SQLAlchemy 2.0), with schema changes as Alembic revisions in `migrations/versions/`. SQLite by default (zero-infra, offline — NFR-9); Postgres via `AGENTFOX_DATABASE_URL`.

All tables carry `id` (prefixed ULID-ish string), `created_at`, `updated_at`, and `org_id` — multi-tenancy is enforced structurally at the session level (`core/tenancy.py`), not just schema-present; see [../design/gap-analysis.md](../design/gap-analysis.md) Tier 1 §1.2. This appendix lists the key tables and columns; the models are the complete list.

---

## D.1 Pillar 1 — Discovery & Registry

**`agents`** — `slug` (unique), `name`, `description`, `purpose`, `owner_email`, `owner_team`, `environment`, `risk_tier` (`minimal|limited|high|prohibited` — EU AI Act aligned), `framework` (detected, P1-6), `status` (`active|inactive|shadow|retired`), `declared_models[]`, `declared_tools[]`, `data_classes[]`, `first_seen_at`, `last_seen_at`, `registered` (bool — false ⇒ shadow).

**`tools`** — `key` (e.g. `payments.transfer`), `name`, `kind` (`function|mcp|http|retrieval|subagent`), `impact` (`read|write|high_impact|irreversible`), `schema_json`, `mcp_server_id?`.

`tools.impact` is the axis policy reasons over. `irreversible` (money moved, email sent, record deleted) is the class that most warrants HITL (P2-3) and taint blocking (P3-4).

**`mcp_servers`** — `name`, `url`, `transport`, `pinned_version`, `trust_level`, `last_scanned_at`.
**`mcp_tool_snapshots`** — `mcp_server_id`, `captured_at`, `tools_json`, `digest`. Consecutive digests differing ⇒ schema drift finding (P1-5).

**`lineage_edges`** — `src_type`/`src_id` → `dst_type`/`dst_id`, `relation` (`uses_model|calls_tool|reads_data|delegates_to|connects_mcp`), `observed_count`, `first_observed_at`, `last_observed_at`, `declared` (bool). **Derived from spans, not from config** (P1-3 design note).

**`findings`** — the cross-pillar queue. `type` (`shadow_agent|tool_poisoning|schema_drift|unowned_agent|stale_credential|over_privileged|budget_breach|loop_detected|drift|silent_failure|redteam|chain_break|control_failing`, the `monitor_*` types of §D.7, `live_probe_escape`, …), `severity`, `status` (`open|triaged|suppressed|resolved`), `subject_type`/`subject_id`, `evidence_json`, `suppression_reason`, `suppressed_by`.

---

## D.2 Pillar 2 — Identity, Access & Authorization

**`identities`** — the NHI record. `agent_id`, `principal` (unique), `kind` (`agent|service|human`), `status` (`active|suspended|revoked`), `last_used_at`, `posture` (`healthy|stale|over_privileged|orphaned`).
**`credentials`** — `identity_id`, `key_prefix`, `key_hash` (argon2id), `issued_at`, `expires_at`, `rotated_from_id?`, `revoked_at?`, `last_used_at`. Plaintext exists only in the issuance response.
**`capabilities`** — `identity_id`, `tool_key` (glob allowed), `actions[]`, `constraints_json` (argument-level, e.g. `{"amount": {"lt": 1000}}`), `requires_approval` (bool), `max_taint` (`none|user|tool_result|retrieved`), `granted_by`, `expires_at?`.
**`delegation_edges`** — `parent_identity_id`, `child_identity_id`, `capability_diff_json`, `trace_id`. **Write-time invariant: child capabilities ⊆ parent capabilities.** Widening is rejected, not audited after the fact (P2-5).
**`approval_requests`** — `decision_id`, `trace_id`, `agent_id`, `tool_key`, `arguments_json`, `reason`, `requested_at`, `expires_at`, `status` (`pending|approved|denied|expired|used`), `resolver_user_id?`, `resolution_rationale?`, `timeout_action` (`deny|allow`, default `deny`). `tool_key` is `message:<surface>` for a held message, whose `arguments_json` carries a masked excerpt and `content_sha256`. On approval `expires_at` restarts as the redemption window. **`used` is final:** a retry presenting the approval for the same agent, tool and arguments flips `approved → used` in a conditional update, so an approval lets exactly one call through (P2-3).
**`users`**, **`api_tokens`** — control-plane RBAC (§C.4); the role is `users.role`. `api_tokens`: `user_id`, `name`, `key_prefix`, `key_hash` (argon2id), `expires_at?`, `revoked_at?`. Signing out sets `revoked_at` on that session's token.
**`github_connections`** — `github_user_id`, `github_login`, `access_token_encrypted`, `connected_by_user_id`, `webhook_secret_encrypted?` (the secret GitHub signs push deliveries with, encrypted; null means only the deployment-wide `github_webhook_secret` can verify this connection's deliveries).

---

## D.3 Pillar 3 — Runtime Guardrails

**`detector_runs`** — `trace_id`, `span_id`, `detector_key`, `detector_version`, `surface` (`input|output|tool_args|tool_result|retrieved`), `duration_ms`, `status` (`ok|timeout|error|skipped_budget`), `score`, `raw_json`.
`status=timeout|skipped_budget` is the P3-6 degradation signal and feeds NOM-RTG-06.

**`detection_findings`** — `detector_run_id`, `entity_type` (`PII.EMAIL`, `PII.SSN`, `SECRET.API_KEY`, `INJECTION.INSTRUCTION_OVERRIDE`, `SAFETY.HARM`, …), `score`, `start`/`end` offsets, `sample` (**redacted at capture** — P5-5), `action_taken` (`none|redact|mask|tokenize|block`).

**`taint_tags`** — `trace_id`, `path` (JSON pointer into the message/argument structure), `source` (`user|retrieved|tool_result|subagent|memory`), `trust` (`trusted|untrusted`), `propagated_from?`. The substrate for intent-based containment (P3-4).

**`budgets`** — `scope_type`/`scope_id`, `window`, `max_calls`, `max_tokens`, `max_cost_usd`, `max_depth`, and running counters (P3-10).

---

## D.4 Pillar 4 — Evaluation & Reliability

**`eval_suites`** — `key`, `name`, `version`, `description`, `tags[]`.
**`eval_cases`** — `suite_id`, `input_json`, `expected_json?`, `context_json?` (for groundedness), `labels[]`, `split`, `source_trace_id?` (promoted from production), `weight`.
**`scorers`** — `key`, `kind` (`exact|fuzzy|json_schema|regex|groundedness|self_consistency|safety|latency|cost|tool_trajectory|llm_judge|custom`), `config_json`, `judge_model?` (pinned — X-4), `rubric?`.
**`eval_runs`** — `suite_id`, `target_json` (agent | model | provider — enables P4-8), `scorer_keys[]`, `baseline_run_id?`, `status`, `started_at`, `finished_at`, `summary_json`, `runner` (`native|promptfoo`), `code_version`, `policy_version`.
**`eval_results`** — `run_id`, `case_id`, `scorer_key`, `score`, `passed`, `output_json`, `detail_json`, `duration_ms`, `cost_usd`.
**`baselines`** — `suite_id`, `run_id`, `label`, `thresholds_json` (per-scorer regression tolerance — the gate semantics of P4-1).
**`drift_windows`** — `agent_id`, `scorer_key`, `window_start`/`end`, `n`, `mean`, `p50`, `p95`, `psi`, `ks`, `baseline_window_id?`, `drifted` (bool).
**`slos`** — `agent_id`, `scorer_key`, `objective`, `window`, `target`, `current`, `error_budget_remaining`.
**`redteam_campaigns`** / **`redteam_findings`** — `runner` (`native|garak|pyrit|giskard|live`), `probes[]`, `target_json`, `status`, `summary_json`, `finished_at`, and per-finding `probe`, `severity`, `succeeded`, `owasp_id`, `atlas_id`, `evidence_json`. A live-probe campaign has `runner="live"` and `target_json.source="live_probe"`.
**`probe_targets`** — a deployed agent's endpoint that live probes may be sent to. `agent_slug`, `name`, `adapter` (`http|in_process`), `url?`, `registered_host?` (the one host the opt-in covers), `model?`, `auth_header_ciphertext?` (encrypted `Authorization` value), `config_json` (`forbidden_tools`, `leak_markers`, `probes`), `enabled` (default **false**), `opted_in_by?`, `opted_in_at?`, `opt_in_acknowledgement?` (the warning text agreed to), `interval_seconds`, `max_probes_per_run`, `rate_limit_per_minute`, `timeout_seconds` (each clamped to hard caps at run time), `next_due_at?`, `last_run_at?`, `last_campaign_id?`, `created_by`. Changing `url` clears the opt-in.

---

## D.5 Pillar 5 — Audit & Traceability

**`traces`** — `agent_id`, `session_id`, `environment`, `started_at`, `ended_at`, `status`, `verdict` (worst verdict in the trace), `intent`, `model`, `provider`, `token_usage_json`, `cost_usd`.
**`spans`** — `trace_id`, `parent_span_id?`, `kind` (`llm|tool|retrieval|guardrail|policy|approval|agent|subagent`), `name`, `started_at`, `ended_at`, `duration_ms`, `attributes_json` (OpenLLMetry semconv), `status`, `error?`.

**`audit_entries`** — the hash chain. `seq` (monotonic, unique), `occurred_at`, `actor_type`/`actor_id`, `action`, `subject_type`/`subject_id`, `payload_json` (redacted at capture), `payload_digest`, `prev_digest`, `digest`.

```
payload_digest = SHA-256(canonical_json(payload))
digest         = SHA-256(f"{seq}|{occurred_at_iso}|{action}|{payload_digest}|{prev_digest}")
```

**Invariants — enforced in code, not by convention (P5-2, NFR-5):**
- Append-only. No update or delete path exists in the ORM layer or the API (§C.3).
- `seq` is gapless. A gap is a detected break, not a missing row.
- `prev_digest` of entry *n* equals `digest` of entry *n−1*; entry 0 uses the genesis constant.
- Verification is a pure function of the exported rows — a third party can run it with no access to our systems.

**`audit_checkpoints`** — `seq`, `digest`, `signed_at`, `signature`, `key_id`. Signing key lives outside the application database (NFR-7, R8); customer-held in self-host.

**`evidence_packages`** — `scope_json` (agents × period × controls), `requested_by`, `built_at`, `manifest_json` (per-file SHA-256), `chain_verification_json`, `code_version`, `catalog_version`, `path`. Chain-of-custody per P5-7.
**`retention_policies`** — `data_class`, `retain_days`, `redact_fields[]`.
**`legal_holds`** — `scope_json`, `reason`, `placed_by`, `placed_at`, `released_at?`. Overrides retention deletion.

---

## D.6 Pillar 6 — Policy & Compliance

**`policies`** — `key`, `name`, `description`, `kind` (`declarative|rego`), `owner`.
**`policy_versions`** — `policy_id`, `version` (int, monotonic), `body` (YAML or Rego), `compiled_json`, `author`, `created_at`, `notes`. **Immutable.**
**`policy_bindings`** — `policy_version_id`, `scope_json` (agent/env/tool), `mode` (`observe|enforce`), `effective_from`, `effective_to?`. Observe-by-default is the R3 mitigation.
**`decisions`** — `trace_id`, `span_id`, `agent_id`, `identity_id`, `surface`, `tool_key?`, `verdict`, `rules_fired_json`, `policy_version_id` (**always the exact version in force — X-4**), `detector_run_ids[]`, `taint_summary_json`, `latency_ms`, `mode`, `approval_id?`.
**`simulation_runs`** — `policy_version_id`, `candidate_body`, `scope_json`, `replayed_count`, `diff_json` (`newly_blocked|newly_allowed|newly_escalated|unchanged`), `run_by` (P2-7).

**`controls`** — `key` (`NOM-RTG-01`), `title`, `objective`, `family`, `pillar`, `implemented_by[]` (FR ids), `evidence_sources[]`, `status_rule_json`, `catalog_version`.
**`framework_mappings`** — `control_key`, `framework` (`eu-ai-act|nist-ai-rmf|iso-42001|soc2|owasp-llm|owasp-agentic|mitre-atlas`), `reference` (`Art. 15`, `MEASURE 2.7`, `LLM01`…), `note`, `review_status` (`draft|reviewed`), `reviewed_by?`, `reviewed_at?`. **`draft` mappings ship in evidence packages chip-labeled `DRAFT — UNVERIFIED / NOT LEGAL ADVICE`** rather than being excluded (Appendix B §B.6).
**`control_statuses`** — `control_key`, `scope_json`, `status` (`effective|degraded|failing|not_implemented|not_applicable`), `computed_at`, `evidence_json`, `rationale`. Computed, never attested (P6-4).
**`risk_assessments`** — `agent_id`, `eu_ai_act_class`, `inherent_risk`, `mitigations_json`, `residual_risk`, `assessor`, `assessed_at`, `next_review_at`, `answers_json`, `signed_off_by?`.
**`obligations`** — `framework`, `reference`, `title`, `effective_date`, `applies_when_json`, and derived `in_scope_agent_ids[]`, `status` (P6-5).

---

## D.7 Continuous monitoring & scheduled work

**`monitors`** — something connected that AgentFox re-checks on a schedule. `kind` (`github_repo|hosted_api|mcp_server|deployed_agent`), `target` (`owner/repo`, a spec URL, an MCP server name, or a `probe_targets.id`), `name`, `config_json` (branch or ref, connection id, …), `interval_seconds` (default 6 h; clamped to 5 min – 30 days), `enabled`, `status` (`pending|baseline|ok|changed|failed|inconclusive`), `last_run_at?`, `next_run_at?`, `last_result_json`, `baseline_json` (the snapshot the next run diffs against; replaced only by a successful run), `last_error`, `consecutive_failures`, `created_by`. Unique on `(org_id, kind, target)`; indexed on `(enabled, next_run_at)`.
Findings a monitor raises have `subject_type="monitor"` and types `monitor_lethal_trifecta`, `monitor_ungoverned_model_call`, `monitor_governance_removed`, `monitor_new_tool`, `monitor_new_mcp_server`, `monitor_api_destructive_endpoint`, `monitor_api_new_endpoint`, and `monitor_failing` (raised after `monitor_failure_threshold` consecutive failures).

**`alert_channels`** — where a tenant's monitor alerts go, beyond the deployment-wide webhook. One row per tenant per `kind` (only `slack` today). `url_encrypted` (the incoming-webhook URL, a bearer credential; must be `https://hooks.slack.com/…`), `min_severity` (default `medium`), `enabled`, `created_by`.

**`jobs`** — deferred work with retries and a dead letter. `kind` (`monitors.run`, `probes.run`, `escalation.scan`, `canary.advance`, …), `payload_json`, `status`, `attempts`/`max_attempts`, `last_error`, `result_json`, `requested_by`, `enqueued_at`, `available_at?` (backoff), `started_at?` (stuck-job recovery), `finished_at?`, `schedule_id?`.
**`job_schedules`** — recurring per-tenant work that fills the queue. `kind`, `payload_json`, `interval_seconds`, `enabled`, `last_enqueued_at?`, `next_due_at?`, `created_by`. A schedule enqueues at most once per interval and never while its previous job is pending or running.

---

## D.8 Key relationships

```
Agent 1──n Identity 1──n Credential
  │            └──n Capability
  │            └──n DelegationEdge (child ⊆ parent)
  ├──n Trace 1──n Span
  │       └──n Decision ──1 PolicyVersion
  │              └──n DetectorRun ──n DetectionFinding
  │              └──0..1 ApprovalRequest
  │       └──n TaintTag
  ├──n LineageEdge  (observed)
  ├──n Finding
  ├──n RiskAssessment
  ├──n DriftWindow / SLO
  └──n EvalRun ──n EvalResult ──1 EvalCase ──1 EvalSuite

Monitor ──n Finding (subject_type=monitor)
Monitor[deployed_agent] ──1 ProbeTarget ──n RedTeamCampaign[runner=live]
GithubConnection ──n Monitor[github_repo]                 (via config_json.connection_id)

AuditEntry[seq] ──prev_digest──▶ AuditEntry[seq-1]        (hash chain)
AuditCheckpoint ──▶ AuditEntry[seq]                        (signed anchor)
EvidencePackage ──▶ {Traces, Decisions, AuditEntries, EvalRuns, ControlStatuses}
Control ──n FrameworkMapping ; Control ──n ControlStatus
```

## D.9 Indices that matter

`traces(agent_id, started_at)` · `spans(trace_id, started_at)` · `decisions(agent_id, verdict, created_at)` · `decisions(trace_id)` · `audit_entries(seq)` unique · `detection_findings(entity_type, created_at)` · `lineage_edges(src_id, dst_id, relation)` unique · `findings(status, severity, created_at)` · `eval_results(run_id, case_id, scorer_key)` unique · `control_statuses(control_key, computed_at)` · `monitors(org_id, kind, target)` unique · `monitors(enabled, next_run_at)` · `jobs(status, enqueued_at)`.

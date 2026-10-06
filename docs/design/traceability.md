# Traceability — requirement → implementation → test

Every functional requirement in the [PRD](PRD.md), the module that implements it, the
control it evidences, and the test that proves it.

**Status:** ✅ built · ◐ partial · ✗ specified, not built. Live, probe-computed status is in
[../status.md](../status.md). Older rows name tests by file and function; rows added
2026-10-06 give the path under `tests/`. Some module paths in the older rows predate the
package split; [ARCHITECTURE.md](../../ARCHITECTURE.md)'s code map is current.

---

## Pillar 1 — Discovery & Agent Registry

| FR | Status | Implementation | Control | Test |
|---|---|---|---|---|
| **P1-1** Agent & tool inventory | ✅ | `platform/registry/service.py::register_agent, observe_agent, upsert_tool, inventory` | NOM-DSC-01 | `test_registry_and_compliance.py::test_inventory_counts` |
| **P1-2** Shadow-agent detection | ✅ | `platform/registry/service.py::observe_agent, detect_shadow_agents` | NOM-DSC-02 | `::test_first_observation_creates_a_shadow_agent`, `::test_second_observation_does_not_duplicate` |
| **P1-3** Lineage & dependency map | ◐ graph + blast radius; no visual map | `platform/registry/service.py::derive_lineage, record_edge, lineage` | NOM-DSC-04 | `::test_lineage_derived_from_observed_traffic`, `::test_blast_radius_is_never_negative` |
| **P1-4** Ownership & metadata | ✅ | `models.py::Agent.is_owned`, `platform/registry/service.py::unowned_agents` | NOM-DSC-03 | `::test_unowned_agent_is_a_finding` |
| **P1-5** MCP inventory & hygiene | ◐ native checks; `mcp-scan` optional tool | `platform/registry/service.py::scan_mcp_server, upsert_mcp_server` | NOM-DSC-05 | `::test_tool_poisoning_detected`, `::test_schema_drift_detected_between_snapshots`, `::test_unpinned_server_flagged` |
| **P1-6** Framework auto-discovery | ✅ | `audit/otel.py::detect_framework` | NOM-DSC-01 | `test_enforcement_and_api.py::test_otlp_ingest_populates_the_registry` |
| **P1-7** Registry drift & attestation | ◐ detected on demand; no scheduled job | `platform/registry/service.py::attest_registry` | NOM-DSC-01/04 | `::test_registry_drift_detected` |
| **P1-9** Continuous monitoring of connected sources | ✅ GitHub, hosted-API specs, remote MCP servers, deployed agents; Slack and webhook alerts | `capabilities/monitoring/service.py::run_monitor, run_due, request_run`, `capabilities/monitoring/snapshots.py::diff_repo, diff_api`, `capabilities/monitoring/alerts.py`, `apps/gateway/routes/monitors.py`, `apps/cli/commands/monitors.py` (`agentfox scan monitors`) | NOM-DSC-05 | `tests/capabilities/monitoring/test_monitor_runs.py`, `tests/capabilities/monitoring/test_monitor_routes.py`, `tests/capabilities/monitoring/test_snapshots.py`, `tests/capabilities/monitoring/test_monitor_schema.py`, `tests/apps/cli/test_monitor_cli.py` |

## Pillar 2 — Identity, Access & Authorization

| FR | Status | Implementation | Control | Test |
|---|---|---|---|---|
| **P2-1** Non-human identity | ✅ | `platform/identity/service.py::ensure_identity, issue_credential, rotate_credential, revoke_credential, assess_posture` | NOM-IAM-01 | `test_policy_and_identity.py::test_credential_roundtrip`, `::test_rotation_keeps_old_key_alive_during_overlap` |
| **P2-2** Tool-scoped least privilege | ✅ | `platform/identity/service.py::grant_capability, check_capability` + `platform/policy/engine.py` | NOM-IAM-02 | `::test_default_deny`, `::test_argument_constraints_enforced`, `::test_most_specific_grant_wins` |
| **P2-3** Human-in-the-loop approvals | ✅ webhook-only notification; an approved retry is redeemed once; none granted while the agent is stopped | `platform/identity/service.py::request_approval, resolve_approval, redeem_approval, expire_stale_approvals`; `sdk.AgentFox.wait_for_approval`; `agentfox permit approvals` | NOM-IAM-03 | `::test_approval_lifecycle`, `::test_unanswered_approval_fails_closed`; `tests/platform/identity/test_approval_redemption.py`, `tests/apps/cli/test_approvals_cli.py`, `tests/runtime/test_kill_switch_every_surface.py` |
| **P2-4** SSO / SCIM / RBAC | ◐ RBAC + tokens complete; IdP seam unwired | `apps/gateway/deps.py::current_user, require`, `models.py::User`; `core/config.py::assert_production_secrets`; `POST /api/auth/logout`; `agentfox admin users create` | NOM-IAM-04 | `test_enforcement_and_api.py::test_auditor_cannot_mutate_anything`, `::test_developer_cannot_enforce_a_policy`; `tests/apps/gateway/test_auth_hardening.py`, `tests/apps/cli/test_first_operator.py` |
| **P2-5** Delegation & sub-agent identity | ◐ narrowing enforced; no cross-process propagation | `platform/identity/service.py::delegate, _covers` | NOM-IAM-05 | `::test_delegation_widening_rejected_at_write_time`, `::test_child_cannot_broaden_a_glob`, `::test_child_cannot_drop_an_approval_requirement` |
| **P2-6** Credential brokerage | ✗ | — | NOM-IAM-01 | — |
| **P2-7** Policy simulation | ✅ replays the candidate in context; promotion to enforce over HTTP needs a recorded simulation | `platform/policy/simulate.py::simulate, record_simulation` | NOM-IAM-06 | `test_enforcement_and_api.py::test_policy_simulation_reports_a_diff`; `tests/platform/policy/test_simulate_in_context.py`, `tests/apps/gateway/test_policy_save_and_promote.py` |

## Pillar 3 — Runtime Guardrails & Security

| FR | Status | Implementation | Control | Test |
|---|---|---|---|---|
| **P3-1** Prompt injection & jailbreak | ✅ | `guardrails/detectors/injection.py` | NOM-RTG-01 | `test_guardrails.py::test_injection_detected`, `::test_indirect_injection_scores_higher_than_direct`, `::test_encoded_payload_is_decoded`, `::test_benign_text_is_not_flagged` |
| **P3-2** PII / DLP both directions | ✅ | `guardrails/detectors/pii.py`, `adapters/presidio.py` | NOM-RTG-02 | `::test_pii_entities_detected`, `::test_credit_card_requires_luhn`, `::test_redaction_preserves_offsets_right_to_left` |
| **P3-3** Secrets leakage | ✅ | `guardrails/detectors/secrets.py` | NOM-RTG-03 | `::test_known_secret_formats`, `::test_entropy_alone_is_not_enough` |
| **P3-4** Tool-call containment (intent-based) | ✅ | `guardrails/taint.py`, `enforcement.py::guard_tool_call`, `policies/tool-containment.yaml` | NOM-RTG-04 | `test_enforcement_and_api.py::test_taint_contains_an_irreversible_tool`; `test_guardrails.py::test_taint_inferred_from_untrusted_content` |
| **P3-5** Content safety | ◐ lexicon + classifier adapter; weights not bundled | `guardrails/detectors/safety.py`, `adapters/classifiers.py` | NOM-RTG-05 | `test_evaluation.py` (via red-team `content_safety` probes) |
| **P3-6** Low-latency enforcement | ✅ | `guardrails/pipeline.py::DetectorPipeline` | NOM-RTG-06 | `test_guardrails.py::test_pipeline_degrades_rather_than_hanging`; `test_enforcement_and_api.py::test_enforcement_stays_inside_the_latency_budget` |
| **P3-7** Fail-open / fail-closed | ✅ | `guardrails/pipeline.py::fail_verdict`, `enforcement.py` | NOM-RTG-06 | `test_guardrails.py::test_pipeline_records_detector_error_without_failing_request` |
| **P3-8** Residency / VPC / self-host | ✅ default and only mode | `config.py::allow_egress`, `deploy/docker-compose.yml` | NOM-AUD-05 | `test_enforcement_and_api.py::test_health_and_version` (asserts `egress_allowed is False`) |
| **P3-9** Output schema enforcement | ◐ native validator; Guardrails-AI adapter optional | `guardrails/detectors/schema.py`, `adapters/rails.py` | NOM-RTG-07 | `test_guardrails.py::test_schema_validation`, `::test_schema_detector_extracts_fenced_json` |
| **P3-10** Rate, cost & loop containment | ✅ | `enforcement.py::_budget_state, _charge_budget`, `models.py::Budget` | NOM-RTG-08 | covered via `policies/tool-containment.yaml` rules `budget.exceeded`, `loop.runaway` |
| **P3-11** Detector swappability & benchmarking | ✅ | `guardrails/base.py` registry, `apps/gateway/app.py::detectors` | NOM-RTG-06 | `test_guardrails.py::test_pipeline_selects_by_surface` |

## Pillar 4 — Evaluation & Reliability Assurance

| FR | Status | Implementation | Control | Test |
|---|---|---|---|---|
| **P4-1** Offline eval + CI gating | ✅ an errored case fails the gate | `capabilities/evaluation/runner.py`, `capabilities/evaluation/gating.py::gate, to_junit, to_sarif` | NOM-EVL-01 | `test_evaluation.py::test_gate_passes_against_itself`, `::test_gate_respects_scorer_direction`, `::test_gate_reports_are_wellformed`; `tests/capabilities/evaluation/test_gate_errors.py` |
| **P4-2** Online eval + drift | ✅ | `capabilities/evaluation/runner.py::sample_production`, `capabilities/evaluation/drift.py::compute` | NOM-EVL-02 | `::test_psi_rises_on_shift`, `::test_ks_statistic` |
| **P4-3** Silent-failure detection | ✅ | `capabilities/evaluation/silent_failure.py` — all six signal families | NOM-EVL-03 | `::test_ensemble_flags_confident_and_wrong`, `::test_refusal_is_not_a_silent_failure`, `::test_groundedness_alone_can_trip_the_ensemble` |
| **P4-4** Automated red-teaming | ✅ probe suite, adapters, adaptive search; weekly posture schedule per tenant (opt-in); probe calls leave nothing in the production tables; `test redteam` exits 1 on an escape | `capabilities/evaluation/redteam.py`, `apps/jobs.py::redteam_posture` | NOM-EVL-04 | `::test_campaign_produces_posture`, `::test_campaign_blocks_injection_probes_when_enforcing`; `tests/capabilities/evaluation/test_redteam_isolation.py` |
| **P4-5** Scorer library & custom scorers | ✅ | `capabilities/evaluation/scorers.py` | NOM-EVL-01 | `::test_task_completion_does_not_punish_correct_answers` |
| **P4-6** Datasets & golden sets | ✅ | `models.py::EvalSuite/EvalCase`, `apps/gateway/routes/evaluation.py::promote_trace` | NOM-EVL-01 | `::test_runner_scores_every_case` |
| **P4-7** Reliability SLOs | ✅ | `capabilities/evaluation/drift.py::evaluate_slos` | NOM-EVL-05 | surfaced via `/api/agents/{slug}/posture` |
| **P4-8** Cross-model comparison | ✅ | `capabilities/evaluation/runner.py` target dispatch, `platform/providers/` | NOM-EVL-06 | `test_enforcement_and_api.py::test_control_plane_reads` |
| **P4-13** Live probing of deployed agents | ✅ opt-in per host, fixed probe set | `capabilities/evaluation/live_probes.py::register_target, opt_in, run_target, run_due`; `apps/gateway/routes/probes.py`; the `deployed_agent` monitor kind | NOM-EVL-04 | `tests/capabilities/evaluation/test_live_probes.py`, `tests/apps/gateway/test_probes_and_showcase.py`, `tests/capabilities/monitoring/test_deployed_agent_monitor.py` |
| **P4-14** Public showcase | ✅ off unless `AGENTFOX_SHOWCASE_ENABLED` | `apps/showcase.py::ensure_showcase, public_summary`; `GET /api/public/showcase`; `dashboard/app/live` | NOM-EVL-04 | `tests/apps/gateway/test_probes_and_showcase.py` (`::test_the_showcase_is_off_unless_enabled`, `::test_the_showcase_reads_only_its_own_tenant`) |

## Pillar 12 — Policy Composition & Lifecycle

| FR | Status | Implementation | Control | Test |
|---|---|---|---|---|
| **P12-1/2** Hierarchy and override semantics, enforced at runtime | ✅ | `platform/policy/hierarchy.py::resolve_effective`, `platform/policy/store.py::policies_in_force`, `runtime/enforcement/enforcer.py` | NOM-GOV-01 | `tests/platform/policy/test_hierarchy_runtime.py`, `tests/capabilities/business/test_ladder_mode.py` |
| **P12-3** Effective policy with provenance | ✅ each layer's mode shown | `platform/policy/store.py::effective_for`; `agentfox policy effective` | NOM-GOV-01 | `tests/apps/cli/test_policy_effective_modes.py` |
| **P12-4** Policy lint | ✅ run by `policy validate` | `platform/policy/hierarchy.py::lint_policy`; `agentfox policy validate` | NOM-GOV-01 | `tests/apps/cli/test_policy_validate_lint.py` |
| **P12-6** Canary rollout | ✅ cohorts, two-way gate, saving never changes what is in force | `platform/policy/canary.py::start_canary, evaluate_gate, canary_rollout` | NOM-GOV-01 | `tests/platform/policy/test_canary_cohorts.py`, `tests/platform/policy/test_mode_after_canary.py`, `tests/apps/gateway/test_policy_save_and_promote.py` |
| **P12-7** Non-developer rule authoring | ✗ | — | — | — |
| Stored versions load through one loader; an unloadable bound version follows the fail mode (`policy.unloadable`) | ✅ | `platform/policy/store.py::load_version_document` | NOM-RTG-06 | `tests/platform/policy/test_stored_version_loading.py`, `tests/runtime/test_pack_fail_mode.py` |

## Pillar 5 — Audit, Observability & Traceability

| FR | Status | Implementation | Control | Test |
|---|---|---|---|---|
| **P5-1** Full execution-path trace | ✅ | `audit/trace.py::start_trace, add_span, full_trace` | NOM-AUD-01 | `test_enforcement_and_api.py::test_clean_request_allowed_and_traced` |
| **P5-2** Tamper-evident audit log | ✅ | `audit/chain.py::append, verify, verify_range` | NOM-AUD-02 | `test_audit_and_evidence.py::test_detects_mutation/deletion/insertion/reordering`, `::test_forged_checkpoint_detected` |
| **P5-3** Auditor-ready evidence export | ✅ | `audit/evidence.py::build` + shipped `verify_chain.py` | NOM-AUD-03 | `::test_evidence_package_contents`, `::test_shipped_verifier_runs_standalone` |
| **P3-4a** Control-flow integrity — untrusted content may fill values, never choose the action | ✅ | `control_flow.py`; `enforcement.py::_control_flow_checks` on the `tool_args` surface | NOM-RTG-04, NOM-IAM-03 | `test_control_flow.py`, `test_control_flow_sycophancy_wiring.py` |
| **F9.2** Sycophancy — a false premise adopted rather than corrected | ✅ | `sycophancy.py`; `enforcement.py::_sycophancy_checks` on the `output` surface | NOM-RTG-12 | `test_sycophancy.py`, `test_control_flow_sycophancy_wiring.py` |
| **P5-4** SIEM / OTel integration, finding webhooks | ✅ | `audit/siem.py::export, to_cef, to_leef, to_otlp`; `webhooks.py` (signed `finding.created` POSTs after commit, egress-gated) | NOM-AUD-04 | `test_enforcement_and_api.py::test_siem_export_formats`; `test_webhooks.py` |
| **P5-5** Retention, redaction, legal hold | ✅ redaction + policy + hold; no deletion daemon | `audit/chain.py::redact_payload`, `models.py::RetentionPolicy/LegalHold` | NOM-AUD-05 | `test_audit_and_evidence.py::test_payload_redacted_at_capture`; `test_guardrails.py::test_sample_is_redacted_at_capture` |
| **P5-6** Trace search & replay | ✅ | `audit/trace.py::search_traces`, `platform/policy/simulate.py` | NOM-AUD-01 | `test_enforcement_and_api.py::test_policy_simulation_reports_a_diff` |
| **P5-7** Provenance & chain-of-custody | ✅ | `audit/evidence.py` manifest + `evidence.exported` audit entry | NOM-AUD-03 | `::test_manifest_digests_match_files`, `::test_exporting_evidence_is_itself_audited` |

## Pillar 6 — Policy & Compliance Management

| FR | Status | Implementation | Control | Test |
|---|---|---|---|---|
| **P6-1** Policy-as-code engine | ✅ native + OPA | `platform/policy/model.py`, `platform/policy/engine.py`, `platform/policy/opa.py`, `platform/policy/store.py` | NOM-GOV-01 | `test_policy_and_identity.py::test_strongest_effect_wins`, `::test_policy_versions_are_immutable`, `::test_rego_compilation_produces_a_module` |
| **P6-2** Control catalog & framework mapping | ✅ 43 controls × 7 frameworks | `compliance_data/controls.yaml`, `compliance/catalog.py`; `agentfox admin catalog validate` | NOM-GOV-02 | `test_registry_and_compliance.py::test_catalog_syncs_all_controls`, `::test_review_status_survives_resync` |
| **P6-3** Risk register & assessment | ✅ | `compliance/risk.py::classify, assess, register` | NOM-GOV-03 | `::test_classification_proposes_high_risk_for_hiring_agent`, `::test_ungated_irreversible_tool_raises_the_proposal` |
| **P6-4** Continuous compliance monitoring | ✅ | `compliance/status.py` — nine rule kinds | NOM-GOV-04 | `::test_status_is_computed_not_attested`, `::test_broken_chain_makes_the_audit_control_fail_hard` |
| **P6-5** Obligation calendar | ✅ | `compliance/obligations.yaml`, `compliance/risk.py::obligation_calendar` | NOM-GOV-05 | `::test_obligation_calendar_scopes_agents` |
| **P6-6** Board / exec dashboard | ✅ | `compliance/risk.py::board_view`, `dashboard/app/board` | NOM-GOV-06 | `::test_board_view_carries_its_caveat` |
| **P6-7** Policy packs | ◐ EU AI Act high-risk + baseline; verticals specified only | `policies/*.yaml` | NOM-GOV-01 | `test_policy_and_identity.py::test_mode_promotion_is_recorded` |
| **P6-8** Framework versioning | ◐ versioned catalog; no diff engine | `compliance/controls.yaml` `version`, `models.py::Control.catalog_version` | NOM-GOV-02 | `::test_review_status_survives_resync` |

## Cross-cutting

| ID | Status | Implementation | Test |
|---|---|---|---|
| **X-1** Three integration surfaces | ✅ | `apps/gateway/routes/inline.py` (proxy + guard + OTLP), `frameworks/sdk/` | `test_enforcement_and_api.py::test_openai_compatible_proxy`, `::test_anthropic_compatible_proxy`, `::test_otlp_ingest_populates_the_registry`, `::test_sdk_local_session_guards_a_tool` |
| **X-2** Provider & framework neutrality | ✅ | `platform/providers/` adapter layer, `audit/otel.py::detect_framework` | `::test_control_plane_reads` (`/api/providers`) |
| **X-3** Offline-first | ✅ | `platform/providers/echo.py`, every adapter's `available()` | whole suite runs with no key and no weights |
| **X-4** Deterministic decisions | ✅ | `platform/policy/engine.py`, `Decision.policy_version_ids` | `test_policy_and_identity.py::test_determinism`; `test_enforcement_and_api.py::test_decision_records_every_policy_version_in_force` |
| **X-5** Everything through the API | ✅ | `dashboard/lib/api.ts` — no DB access from the UI process | dashboard renders solely from `/api` |
| **X-6** Agent-native operation (harness + MCP) | ✅ | `harness/` (skills, commands, subagents, safety hook), `mcp_server.py` + `apps/cli/mcp_cli.py` (`agentfox mcp serve`, 24 read-only tools, stdlib JSON-RPC) | `test_mcp_server.py`; `test_harness.py` (harness ↔ live CLI drift, hook decisions) |

## Non-functional

| ID | Status | Evidence |
|---|---|---|
| **NFR-1** < 100 ms p95 added latency | ✅ tested | `test_enforcement_and_api.py::test_enforcement_stays_inside_the_latency_budget`; measured 2–6 ms on the heuristic path |
| **NFR-2** Availability / no single point of failure | ◐ | `platform/policy/opa.py` falls back to the native engine; `fail_mode=open` default |
| **NFR-3** Throughput | ✗ not load-tested | gateway is stateless; scale-out untested |
| **NFR-4** Data residency, zero egress | ✅ | `config.allow_egress=False`; hosted providers report unavailable |
| **NFR-5** Audit integrity | ✅ | four tamper modes individually tested |
| **NFR-6** Retention | ◐ | policies modelled; no deletion daemon |
| **NFR-7** Platform security posture | ◐ | argon2 credentials, redaction at capture, signing key external; no SOC 2 |
| **NFR-8** < 10 min time to first value | ✅ | `agentfox admin seed && agentfox demo` — offline, ~30 s |
| **NFR-9** Offline operation | ✅ | full suite passes with no network |
| **NFR-10** Determinism & replay | ✅ | `test_determinism`, simulation replay |

## Tranche 0 — delivered 2026-08-18

| ID | Requirement | Status | Implementation | Test |
|---|---|---|---|---|
| **PL-1** | Streaming (SSE) with inline enforcement | ✅ | `platform/providers/base.py::StreamChunk`, `platform/providers/echo.py::stream`, `platform/providers/remote.py` (OpenAI + Anthropic SSE), `enforcement.py::run_completion_stream`, `apps/gateway/routes/inline.py::_stream_openai/_stream_anthropic` | `test_tranche0.py` — 11 tests incl. `test_buffered_mode_never_forwards_blocked_output`, `test_streaming_and_non_streaming_agree_on_verdict`, `test_gateway_stream_block_emits_error_then_done` |
| **PL-2** | Database migrations | ✅ | `alembic.ini`, `migrations/env.py` (URL from Settings, `render_as_batch` for SQLite), baseline revision, `db.py::upgrade_db/downgrade_db/current_revision`, `agentfox admin db upgrade` | `test_migrations_round_trip`, `test_app_runs_on_a_migrated_schema` |
| **PL-3** | Kill switch & quarantine | ✅ every guard surface | `models.py::AgentControl`, `platform/registry/control.py`, `enforcement.py::_control_verdict` (checked before taint/detectors/policy), API `/agents/{slug}/kill|quarantine|resume`, `GET /api/controls`, `agentfox agents kill/quarantine/resume/controls` | 9 tests incl. `test_control_check_precedes_policy`, `test_kill_blocks_the_streaming_path_too`, `test_both_edges_are_audited`; `tests/runtime/test_kill_switch_every_surface.py` |
| **I-1** | LangGraph-native SDK | ✅ | `frameworks/langgraph.py::AgentFoxGuard` — `model_node`, `retrieval_node`, `tool_node`; trace id in graph state (survives checkpointing); escalation via LangGraph `interrupt()` when available | 8 tests incl. `test_tool_node_denies_before_the_body_runs`, `test_integration_imports_without_langgraph` |

**Design notes recorded during the build:**

- **Buffered streaming is the default.** It enforces output identically to the
  non-streaming path at the cost of first-token latency. `windowed` is opt-in and
  documented as unable to recall already-forwarded content — offered knowingly, never
  as a silent default.
- **`run_completion` and `run_completion_stream` share `preflight()`.** Extracted
  deliberately so streaming cannot drift from non-streaming enforcement;
  `test_streaming_and_non_streaming_agree_on_verdict` pins it.
- **Kill/quarantine are reversible and audited on both edges.** An irreversible kill
  switch is one nobody dares use during the incident it was built for.
- **`init_db()` stamps Alembic head on a fresh database**, so a create_all-built dev
  database does not later collide with `alembic upgrade`.

## Known gaps

Live IdP (OIDC/SAML) integration · managed cloud, billing · cross-org benchmarking ·
partner marketplace · non-text modalities · credential brokerage (P2-6) · automated
retention deletion · framework-mapping diff engine (P6-8) · non-developer rule authoring
(P12-7) · load testing (NFR-3).

**All 317 framework mappings are `review_status: draft`** and ship in evidence packages
chip-labeled `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` until a qualified reviewer completes
the gate in [Appendix B §B.6](control-catalog.md#b6-mapping-review-gate) — see
`audit/evidence.py` for the chip-labeling logic (corrected 2026-09-04).

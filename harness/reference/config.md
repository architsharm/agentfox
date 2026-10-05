---
title: AgentFox configuration (environment variables)
layer: reference
audience: agents, operators
source_of_truth: src/agentfox/config.py (Settings, env_prefix AGENTFOX_, legacy NOMETRIA_)
verified_against: commit 6863b8b, 2026-09-15
---

# Configuration

Sources, highest precedence first:

1. `AGENTFOX_*` environment variables
2. `NOMETRIA_*` environment variables, the pre-rename names, still read so existing
   deployments keep working; where both are set, `AGENTFOX_*` wins
3. the `[agentfox]` table of a TOML file
4. built-in defaults

Every variable below is listed under its `AGENTFOX_` name. Three are read only under the old
name: `NOMETRIA_AGENT`, `NOMETRIA_AUDIT_KEY` and `NOMETRIA_MCP_LOG_LEVEL`. The dashboard reads
only `NOMETRIA_API_URL`, `NOMETRIA_API_TOKEN`, `NOMETRIA_USER`, `NOMETRIA_PLAYGROUND_API_URL`,
`NOMETRIA_SERVICE_AUTH_SECRET`, `NOMETRIA_SITE_URL` and `NOMETRIA_SELF_HOSTED`.

The file is `$AGENTFOX_CONFIG` if set, which must exist. Otherwise it's `./agentfox.toml` in
the working directory, if present. `AGENTFOX_CONFIG=none` turns file loading off, which is
useful in CI and containers.

`agentfox init` writes a `agentfox.toml` whose keys are the Settings names below without the
prefix, for example `enforcement_budget_ms = 300`. Other tables and unknown keys are ignored
with a warning. List values can be TOML arrays in the file. As environment variables they
must be JSON, for example `AGENTFOX_ENABLED_DETECTORS='["pii.native","secrets.native"]'`.

Settings are cached per process, so restart after changing them.

## The ones that matter most

| Variable | Default | Why an agent cares |
|---|---|---|
| `AGENTFOX_DATABASE_URL` | `sqlite:///<repo-root>/agentfox.db` | **Point this at a scratch file for demos and experiments.** Postgres (`postgresql+psycopg://…`, `[postgres]` extra) for anything real. |
| `AGENTFOX_ENVIRONMENT` | `development` | Also decides whether the dev auth header is accepted. |
| `AGENTFOX_AUTH_MODE` | `auto` | `auto` \| `development` \| `token` \| `oidc`. Production must not accept `X-Nometria-User`; check with `agentfox auth status`. |
| `AGENTFOX_DEFAULT_POLICY_MODE` | `observe` | `observe` records, `enforce` blocks. |
| `AGENTFOX_FAIL_MODE` | `open` | What happens when a detector errors/times out. `closed` for high-risk agents. |
| `AGENTFOX_ALLOW_EGRESS` | `false` | Must be true for any real model provider or network fetch. |
| `AGENTFOX_DEFAULT_PROVIDER` | `echo` | Offline echo model. Others: `openai`, `anthropic`, `azure`, `bedrock`, `vertex`, `litellm`. |
| `AGENTFOX_ENABLED_DETECTORS` | `["injection.heuristic","pii.native","secrets.native","safety.lexicon","schema.json"]` | Add `pii.presidio`, `injection.classifier`, `injection.similarity`, `safety.granite` after installing their extras. |
| `AGENTFOX_EVIDENCE_DIR` | `<repo-root>/var/evidence` | Where `evidence export` writes zips. |
| `AGENTFOX_AUDIT_SIGNING_KEY` | `dev-insecure-checkpoint-key` | **Must be changed in production.** |
| `AGENTFOX_SERVICE_AUTH_SECRET` | `dev-insecure-service-secret` | Dashboard OAuth callback. **Must be changed in production.** |
| `AGENTFOX_TOKEN_ENCRYPTION_KEY` | unset | Fernet key for stored GitHub tokens; that feature fails closed without it. |
| `AGENTFOX_CRON_SECRET` (or `CRON_SECRET`) | unset | Required for `/api/internal/jobs/run`, which accepts GET (Vercel Cron) or POST. Returns 503 if unset. |
| `AGENTFOX_PLAYGROUND_CORS_ORIGIN` | unset | Comma-separated origins allowed to call the public playground from a browser, additive to localhost. List every host that serves the page: a missing origin shows as "Failed to fetch" in the browser while curl looks healthy. |

## Budgets and reliability

| Variable | Default |
|---|---|
| `AGENTFOX_ENFORCEMENT_BUDGET_MS` / `DETECTOR_TIMEOUT_MS` / `REQUEST_BUDGET_MS` | 300 / 40 / 350 |
| `AGENTFOX_FALLBACK_CHAIN` | `[]` (model degradation ladder) |
| `AGENTFOX_BREAKER_FAILURE_THRESHOLD` / `BREAKER_RECOVERY_SECONDS` | 5 / 30.0 |
| `AGENTFOX_ADMISSION_RATE_PER_SECOND` / `_BURST` / `_MAX_CONCURRENT` / `_SHED_BELOW_PRIORITY` | 200 / 400 / 256 / normal |
| `AGENTFOX_STREAMING_MODE` / `STREAM_WINDOW_CHARS` | `buffered` / 200 |
| `AGENTFOX_LOOP_MAX_STEPS` / `_MAX_REPEATS` / `_MAX_CYCLE_LENGTH` / `_MAX_STEPS_WITHOUT_PROGRESS` | 25 / 2 / 4 / 5 |
| `AGENTFOX_SERVICE_PROBE_INTERVAL_SECONDS` | 5.0 — how often the degradation gate probes dependencies; status endpoints always probe fresh |
| `AGENTFOX_DATA_ACCESS_STRICTNESS` | `standard` (escalate) \| `strict` (block) |
| `AGENTFOX_EMBEDDING_SIMILARITY_ATTACK_THRESHOLD` / `_BENIGN_MARGIN` | 0.6 / 0.05 — `injection.similarity` cut-offs |
| `AGENTFOX_PROMPT_INJECTION_CLASSIFIER_SECONDARY_THRESHOLD` | 0.92 — the backstop classifier's bar (llm-guard's default for that model) |
| `AGENTFOX_POLICY_ENGINE` / `OPA_URL` | `native` / `http://localhost:8181` |

## Improvement loop and scheduler

| Variable | Default | Meaning |
|---|---|---|
| `AGENTFOX_IMPROVEMENT_FROZEN` | `false` | Kill switch. While true nothing is applied automatically, but proposals are still filed. |
| `AGENTFOX_IMPROVEMENT_ACTOR_ID` | `agentfox-improver` | The name automated steps are recorded under on the audit chain. |
| `AGENTFOX_IMPROVEMENT_MAX_AUTO_CHANGES_PER_DAY` | 20 | Cap on automated applies per tenant per day. |
| `AGENTFOX_IMPROVEMENT_ROLLBACK_BUDGET` | 0.05 | A change kind rolled back more often than this drops one autonomy level. |
| `AGENTFOX_CANARY_MIN_DWELL_SECONDS` / `_MAX_BLOCK_RATE_DROP` | 3600 / 0.15 | Default canary dwell time, and how much *less* the candidate may block before it rolls back. |
| `AGENTFOX_SCHEDULER_ENABLED` | `true` | Whether cron runs queue scheduled work: canary advance hourly; compliance, drift and threshold proposals daily; red-team posture weekly (off by default). |
| `AGENTFOX_JOB_STUCK_AFTER_SECONDS` / `_BACKOFF_BASE_SECONDS` | 900 / 60 | When a running job counts as crashed, and the base of its exponential retry delay. |

## Providers and integrations

`AGENTFOX_OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_ENDPOINT/_API_KEY/_API_VERSION/_DEPLOYMENT`,
`AWS_REGION`, `BEDROCK_MODEL`, `VERTEX_PROJECT/_LOCATION/_MODEL`, `LITELLM_BASE_URL/_API_KEY`,
`LANGSMITH_*`, `LANGFUSE_*`, `EVAL_RUNNER` (`native`|`promptfoo`), `ONLINE_EVAL_SAMPLE_RATE` (0.25),
`DRIFT_PSI_THRESHOLD` (0.2), `REDACT_AT_CAPTURE` (true), `ACCEPT_RESTRICTED_MODEL_LICENSES` (false).

Never write provider keys into files the harness creates. Tell the user which variable to
export.

## Finding webhooks

| Variable | Default | Notes |
|---|---|---|
| `AGENTFOX_WEBHOOK_URL` | unset | http(s). Each new finding at or above the minimum severity is POSTed after its transaction commits |
| `AGENTFOX_WEBHOOK_SECRET` | unset | Adds `X-Nometria-Signature: sha256=<hex HMAC of the body>` |
| `AGENTFOX_WEBHOOK_TIMEOUT_SECONDS` | 3.0 | One retry on 5xx or timeout |
| `AGENTFOX_WEBHOOK_MIN_SEVERITY` | `high` | `critical` \| `high` \| `medium` \| `low` |

Nothing is sent unless `AGENTFOX_ALLOW_EGRESS=true`. The body is `{"event":
"finding.created", "finding": {...}, "org_id", "sent_at"}`. Receivers should de-duplicate on
`X-Nometria-Delivery`. Delivery is best-effort from a background thread: there is no durable
outbox, and a serverless process may freeze before sending.

## Read outside `Settings`

| Variable | Used by |
|---|---|
| `NOMETRIA_AGENT` | `agentfox.auto()` agent slug. Fallbacks: `OTEL_SERVICE_NAME`, `SERVICE_NAME`, `APP_NAME`, `K_SERVICE`, script name, `default-agent`. |
| `AGENTFOX_CONFIG` | Path to the TOML config file, or `none`. |
| `AGENTFOX_API_URL`, `AGENTFOX_API_TOKEN`, `AGENTFOX_USER` | `check/quickscan --submit` only. |
| `NOMETRIA_AUDIT_KEY` | The `verify_chain.py` bundled in evidence packages (checkpoint signatures). |

## Optional extras (`pip install "agentfox[...]"`)

`pii` (Presidio) · `classifiers` (transformers+torch: PIGuard, Granite Guardian, similarity) ·
`sql` (sqlglot — action assurance fails closed without it) · `langgraph` · `otel` · `postgres` ·
`rails` · `validators` · `redteam` (garak, pyrit) · `bedrock` · `vertex` · `prometheus` · `ragas` ·
`all` (permissive set, excludes cloud SDKs) · `restricted-classifiers` (non-OSI licences; also
needs `AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1`).

import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Output } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Configuration reference",
  description:
    "Every AgentFox setting: environment variable, agentfox.toml key, default and what it does.",
  path: "/docs/reference/config",
});

type Row = { key: string; env: string; def: string; what: string };

/**
 * Generated from src/agentfox/core/config.py by instantiating Settings() with no config file and
 * an empty environment, then written here as static data. Descriptions are hand-written
 * from the field comments. Every Settings field appears exactly once; regenerate when
 * Settings changes.
 */
const GROUPS: { id: string; title: string; rows: Row[] }[] = [
  {
    "id": "state",
    "title": "Database, state and deployment",
    "rows": [
      {
        "key": "database_url",
        "env": "AGENTFOX_DATABASE_URL",
        "def": "sqlite:///<state dir>/agentfox.db",
        "what": "Where everything is stored. SQLite by default; postgresql+psycopg://… with the postgres extra. A multi-worker server refuses SQLite at startup."
      },
      {
        "key": "sql_echo",
        "env": "AGENTFOX_SQL_ECHO",
        "def": "false",
        "what": "Log every SQL statement. For debugging only."
      },
      {
        "key": "evidence_dir",
        "env": "AGENTFOX_EVIDENCE_DIR",
        "def": "<state dir>/var/evidence",
        "what": "Where agentfox report evidence writes packages."
      },
      {
        "key": "org_id",
        "env": "AGENTFOX_ORG_ID",
        "def": "org_default",
        "what": "The organisation (tenant) records belong to when no token says otherwise."
      },
      {
        "key": "environment",
        "env": "AGENTFOX_ENVIRONMENT",
        "def": "development",
        "what": "development, staging, production, … Decides whether the development identity header is accepted when auth_mode is auto; anything not recognised as development counts as production."
      },
      {
        "key": "console_url",
        "env": "AGENTFOX_CONSOLE_URL",
        "def": "\"\"",
        "what": "Your dashboard's address, used to turn a decision id in a refusal into a link. Never guessed; empty omits the link."
      },
      {
        "key": "compliance_dir",
        "env": "AGENTFOX_COMPLIANCE_DIR",
        "def": "unset: the compliance packs",
        "what": "A directory to read controls.yaml, obligations.yaml and threats.yaml from instead of the capability packs. Set only to load your own catalog."
      },
      {
        "key": "policies_dir",
        "env": "AGENTFOX_POLICIES_DIR",
        "def": "unset: the built-in packs",
        "what": "A directory to read the shipped policy files from instead of the built-in capability packs."
      },
      {
        "key": "pack_maturity",
        "env": "AGENTFOX_PACK_MATURITY",
        "def": "stable",
        "what": "Which capability packs load: stable, incubating (stable and incubating) or sandbox (all). See agentfox policy packs list --all."
      }
    ]
  },
  {
    "id": "auth",
    "title": "Authentication and secrets",
    "rows": [
      {
        "key": "auth_mode",
        "env": "AGENTFOX_AUTH_MODE",
        "def": "auto",
        "what": "auto follows environment; development accepts the X-AgentFox-User header; token requires API tokens; oidc is reserved. Check with agentfox admin auth status."
      },
      {
        "key": "service_auth_secret",
        "env": "AGENTFOX_SERVICE_AUTH_SECRET",
        "def": "dev-insecure-service-secret",
        "what": "Shared between the gateway and the dashboard for the GitHub sign-in provisioning call, which mints owner tokens. Must be identical on both. Outside development the gateway refuses to start while it is the published default."
      },
      {
        "key": "token_encryption_key",
        "env": "AGENTFOX_TOKEN_ENCRYPTION_KEY",
        "def": "unset",
        "what": "Fernet key that encrypts every secret stored at rest: GitHub tokens, source credentials, alert URLs, probe auth headers, agent signing keys. Unset: those features fail closed."
      },
      {
        "key": "token_encryption_key_previous",
        "env": "AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS",
        "def": "unset",
        "what": "Retired encryption keys, comma-separated. They still decrypt and never encrypt; agentfox admin keys rotate moves everything to the current key, then remove them."
      },
      {
        "key": "cron_secret",
        "env": "AGENTFOX_CRON_SECRET",
        "def": "unset",
        "what": "Bearer secret for /api/internal/jobs/run. Unset: the route refuses every call. CRON_SECRET is also read."
      },
      {
        "key": "playground_cors_origin",
        "env": "AGENTFOX_PLAYGROUND_CORS_ORIGIN",
        "def": "unset",
        "what": "Comma-separated browser origins allowed to call the public playground, added to localhost."
      },
      {
        "key": "trusted_proxy_hops",
        "env": "AGENTFOX_TRUSTED_PROXY_HOPS",
        "def": "1 on Vercel, else 0",
        "what": "Proxies in front of the gateway that append to X-Forwarded-For. The per-visitor limits (playground, waitlist, showcase) read the visitor's address that many entries from the right. 0 ignores the header."
      },
      {
        "key": "max_request_bytes",
        "env": "AGENTFOX_MAX_REQUEST_BYTES",
        "def": "10000000",
        "what": "The largest request body the gateway reads, in bytes. A larger one is refused with 413 before it is buffered. 0 for no limit."
      },
      {
        "key": "anonymous_inline_per_minute",
        "env": "AGENTFOX_ANONYMOUS_INLINE_PER_MINUTE",
        "def": "0",
        "what": "Inline requests per minute per address from a caller with no credential (429 past it). 0 for no limit, the right setting for a self-hosted gateway serving its own unregistered agents; set it on a gateway open to the internet."
      },
      {
        "key": "onboarding_key_ttl_days",
        "env": "AGENTFOX_ONBOARDING_KEY_TTL_DAYS",
        "def": "30",
        "what": "How long an older setup key (afi_\u2026) stays valid after it is made. 0: never expires. The key the setup card makes now (nom_api_\u2026, which init writes for your app) never expires: rotate or revoke it."
      }
    ]
  },
  {
    "id": "policy",
    "title": "Policy and enforcement",
    "rows": [
      {
        "key": "default_policy_mode",
        "env": "AGENTFOX_DEFAULT_POLICY_MODE",
        "def": "observe",
        "what": "The mode of a policy that does not declare one. Packs that declare a mode keep it: tool-containment declares enforce."
      },
      {
        "key": "fail_mode",
        "env": "AGENTFOX_FAIL_MODE",
        "def": "open",
        "what": "What happens when a detector errors or exceeds its budget: open lets the request through and records the gap; closed refuses."
      },
      {
        "key": "taint_scope",
        "env": "AGENTFOX_TAINT_SCOPE",
        "def": "session",
        "what": "session: a call's provenance is the worst untrusted content in the run so far. argument: only what its own arguments were copied from. Any other value is an error. See Concepts."
      },
      {
        "key": "enforcement_budget_ms",
        "env": "AGENTFOX_ENFORCEMENT_BUDGET_MS",
        "def": "300",
        "what": "Latency ceiling for the whole pre-flight pipeline on one surface."
      },
      {
        "key": "detector_timeout_ms",
        "env": "AGENTFOX_DETECTOR_TIMEOUT_MS",
        "def": "40",
        "what": "Default per-detector budget."
      },
      {
        "key": "request_budget_ms",
        "env": "AGENTFOX_REQUEST_BUDGET_MS",
        "def": "350",
        "what": "Ceiling across every surface one governed call touches. Kept above enforcement_budget_ms."
      },
      {
        "key": "long_text_chars",
        "env": "AGENTFOX_LONG_TEXT_CHARS",
        "def": "200",
        "what": "Past this many characters, the injection classifier's check gets long_text_budget_ms instead of the default budget."
      },
      {
        "key": "long_text_budget_ms",
        "env": "AGENTFOX_LONG_TEXT_BUDGET_MS",
        "def": "1000",
        "what": "Budget for the injection classifier on long text, whose windows take longer to read on a CPU. A ceiling, not a wait."
      },
      {
        "key": "policy_engine",
        "env": "AGENTFOX_POLICY_ENGINE",
        "def": "native",
        "what": "native, or opa to evaluate through an Open Policy Agent sidecar (falls back to native if it is unreachable)."
      },
      {
        "key": "opa_url",
        "env": "AGENTFOX_OPA_URL",
        "def": "http://localhost:8181",
        "what": "The OPA sidecar, when policy_engine is opa."
      },
      {
        "key": "streaming_mode",
        "env": "AGENTFOX_STREAMING_MODE",
        "def": "buffered",
        "what": "buffered enforces streamed output exactly like non-streamed, at the cost of first-token latency; windowed forwards as it goes and cannot recall what it already sent."
      },
      {
        "key": "stream_window_chars",
        "env": "AGENTFOX_STREAM_WINDOW_CHARS",
        "def": "200",
        "what": "Window size for windowed streaming."
      },
      {
        "key": "approval_ttl_minutes",
        "env": "AGENTFOX_APPROVAL_TTL_MINUTES",
        "def": "30",
        "what": "How long a held call waits for a person before it is denied."
      }
    ]
  },
  {
    "id": "detectors",
    "title": "Detectors",
    "rows": [
      {
        "key": "enabled_detectors",
        "env": "AGENTFOX_ENABLED_DETECTORS",
        "def": "[\"injection.heuristic\", \"pii.native\", \"secrets.native\", \"safety.lexicon\", \"schema.json\"]",
        "what": "Which detectors run. A listed detector whose extra or weights are missing is unavailable and does not run."
      },
      {
        "key": "accept_restricted_model_licenses",
        "env": "AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES",
        "def": "false",
        "what": "Required (1/true) before a Meta model loads: safety.restricted (Llama Guard) or Prompt Guard 2 as injection.classifier. Their licences are not OSI-approved."
      },
      {
        "key": "prompt_injection_classifier_model",
        "env": "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_MODEL",
        "def": "leolee99/PIGuard",
        "what": "Primary model for injection.classifier: leolee99/PIGuard, protectai/deberta-v3-base-prompt-injection-v2, or Meta's meta-llama/Llama-Prompt-Guard-2-22M or -86M (gated; needs the licence flag above). Each is read with its own labels, threshold and window."
      },
      {
        "key": "prompt_injection_classifier_threshold",
        "env": "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_THRESHOLD",
        "def": "(the model's own)",
        "what": "Score a label must reach. Unset uses the model's published default: 0.5 for PIGuard and protectai, 0.9 for Prompt Guard 2 (LlamaFirewall's)."
      },
      {
        "key": "prompt_injection_classifier_secondary_model",
        "env": "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_SECONDARY_MODEL",
        "def": "protectai/deberta-v3-base-prompt-injection-v2",
        "what": "Backstop model consulted only when the primary finds nothing. Empty disables it."
      },
      {
        "key": "prompt_injection_classifier_secondary_threshold",
        "env": "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_SECONDARY_THRESHOLD",
        "def": "0.92",
        "what": "The backstop's score bar."
      },
      {
        "key": "embedding_similarity_model",
        "env": "AGENTFOX_EMBEDDING_SIMILARITY_MODEL",
        "def": "sentence-transformers/all-MiniLM-L6-v2",
        "what": "Embedding model for injection.similarity."
      },
      {
        "key": "embedding_similarity_attack_threshold",
        "env": "AGENTFOX_EMBEDDING_SIMILARITY_ATTACK_THRESHOLD",
        "def": "0.6",
        "what": "Cosine similarity to the nearest known attack before injection.similarity fires."
      },
      {
        "key": "embedding_similarity_benign_margin",
        "env": "AGENTFOX_EMBEDDING_SIMILARITY_BENIGN_MARGIN",
        "def": "0.05",
        "what": "How far above the nearest benign example that similarity must be."
      },
      {
        "key": "granite_guardian_model",
        "env": "AGENTFOX_GRANITE_GUARDIAN_MODEL",
        "def": "ibm-granite/granite-guardian-3.0-2b",
        "what": "Model for safety.granite."
      },
      {
        "key": "llama_guard_model",
        "env": "AGENTFOX_LLAMA_GUARD_MODEL",
        "def": "meta-llama/Llama-Guard-3-8B",
        "what": "Model for safety.restricted: meta-llama/Llama-Guard-3-8B or -1B (gated). Llama Guard 4 is not supported yet."
      },
      {
        "key": "nemo_rails_config_path",
        "env": "AGENTFOX_NEMO_RAILS_CONFIG_PATH",
        "def": "unset",
        "what": "A NeMo Guardrails config directory. rails.nemo is unavailable until this is set (rails extra)."
      },
      {
        "key": "guardrails_ai_validators",
        "env": "AGENTFOX_GUARDRAILS_AI_VALIDATORS",
        "def": "[]",
        "what": "Guardrails AI Hub validator slugs for rails.guardrails_ai (validators extra). Each must be installed separately."
      },
      {
        "key": "prompt_injection_classifier_secondary_inline",
        "env": "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_SECONDARY_INLINE",
        "def": "false",
        "what": "Run the classifier's advisory backstop model inline. Off: it runs after the response and its hit is recorded on the same trace."
      },
      {
        "key": "classifier_cache_size",
        "env": "AGENTFOX_CLASSIFIER_CACHE_SIZE",
        "def": "4096",
        "what": "Classifier scores kept per model, by hash of the text. 0 turns the cache off."
      },
      {
        "key": "grounding_nli_model",
        "env": "AGENTFOX_GROUNDING_NLI_MODEL",
        "def": "cross-encoder/nli-deberta-v3-small",
        "what": "Model for the opt-in grounding.nli detector. Read from the local cache only."
      },
      {
        "key": "model_server_url",
        "env": "AGENTFOX_MODEL_SERVER_URL",
        "def": "unset",
        "what": "Send model-backed detectors to an agentfox serve models process at this URL, under the same budgets. Unset: they run in this process."
      },
      {
        "key": "model_server_token",
        "env": "AGENTFOX_MODEL_SERVER_TOKEN",
        "def": "unset",
        "what": "Bearer token shared with the model server. It refuses to listen beyond loopback without one."
      },
      {
        "key": "model_server_detectors",
        "env": "AGENTFOX_MODEL_SERVER_DETECTORS",
        "def": "[]",
        "what": "Which detectors go to the model server. Empty: every model-backed one."
      },
      {
        "key": "model_device",
        "env": "AGENTFOX_MODEL_DEVICE",
        "def": "auto",
        "what": "Where a model runs in this process: cpu, cuda, mps, or auto (cuda, then mps, then cpu)."
      }
    ]
  },
  {
    "id": "judgment",
    "title": "Judgment tiers and egress",
    "rows": [
      {
        "key": "allow_egress",
        "env": "AGENTFOX_ALLOW_EGRESS",
        "def": "false",
        "what": "Master switch for anything leaving the machine: hosted model providers, hosted judgment tiers, webhooks, write-back to LangSmith or Langfuse. Off by default."
      },
      {
        "key": "judgment_backend",
        "env": "AGENTFOX_JUDGMENT_BACKEND",
        "def": "local",
        "what": "local keeps every judgment in-process; remote and auto may call a hosted judgment model, only with allow_egress on."
      },
      {
        "key": "judgment_tiers",
        "env": "AGENTFOX_JUDGMENT_TIERS",
        "def": "[\"deterministic\"]",
        "what": "Evaluators that may be consulted: deterministic (always on), local_model, local_llm, jev, llm. Each tier is forbidden from the decisions it measured worse on."
      },
      {
        "key": "judgment_redact_before_egress",
        "env": "AGENTFOX_JUDGMENT_REDACT_BEFORE_EGRESS",
        "def": "true",
        "what": "Redact locally detected personal data before a judgment leaves."
      },
      {
        "key": "judgment_fail_closed",
        "env": "AGENTFOX_JUDGMENT_FAIL_CLOSED",
        "def": "false",
        "what": "Deny an enforcing request when an LLM judge does not answer and a rule on that surface relies on it (pipeline.judge_outage). True also stops a workspace turning it off. A payload the egress gate refused is never an outage."
      },
      {
        "key": "judgment_pii_egress",
        "env": "AGENTFOX_JUDGMENT_PII_EGRESS",
        "def": "redact",
        "what": "block, redact or allow: what to do when a payload bound for a hosted tier contains personal data. Only block guarantees none leaves."
      },
      {
        "key": "judgment_llm_provider",
        "env": "AGENTFOX_JUDGMENT_LLM_PROVIDER",
        "def": "\"\"",
        "what": "Provider for the llm and local_llm tiers. Empty uses default_provider."
      },
      {
        "key": "judgment_llm_model",
        "env": "AGENTFOX_JUDGMENT_LLM_MODEL",
        "def": "\"\"",
        "what": "Model for those tiers. Empty uses the provider's default."
      },
      {
        "key": "judgment_llm_timeout_s",
        "env": "AGENTFOX_JUDGMENT_LLM_TIMEOUT_S",
        "def": "4.0",
        "what": "Seconds one LLM judge call may take before it is abandoned."
      },
      {
        "key": "judgment_inline",
        "env": "AGENTFOX_JUDGMENT_INLINE",
        "def": "when_relied",
        "what": "when_relied: judges run on the request path only when an enforcing rule on that surface could act on their findings, otherwise after the response. always: inline on every check."
      },
      {
        "key": "trusted_model_hosts",
        "env": "AGENTFOX_TRUSTED_MODEL_HOSTS",
        "def": "[]",
        "what": "Hosts you run that count as inside the deployment (a model server, a vLLM or LiteLLM box). A judgment call to one is local_llm, not egress."
      }
    ]
  },
  {
    "id": "providers",
    "title": "Model providers",
    "rows": [
      {
        "key": "default_provider",
        "env": "AGENTFOX_DEFAULT_PROVIDER",
        "def": "echo",
        "what": "echo is the offline provider: deterministic, no key, no network. Others: openai, anthropic, azure, bedrock, vertex, litellm."
      },
      {
        "key": "openai_api_key",
        "env": "AGENTFOX_OPENAI_API_KEY",
        "def": "unset",
        "what": "Key for the openai provider (gateway proxy and judgment tiers)."
      },
      {
        "key": "openai_base_url",
        "env": "AGENTFOX_OPENAI_BASE_URL",
        "def": "https://api.openai.com",
        "what": "OpenAI-compatible endpoint."
      },
      {
        "key": "anthropic_api_key",
        "env": "AGENTFOX_ANTHROPIC_API_KEY",
        "def": "unset",
        "what": "Key for the anthropic provider."
      },
      {
        "key": "anthropic_base_url",
        "env": "AGENTFOX_ANTHROPIC_BASE_URL",
        "def": "https://api.anthropic.com",
        "what": "Anthropic endpoint."
      },
      {
        "key": "azure_openai_endpoint",
        "env": "AGENTFOX_AZURE_OPENAI_ENDPOINT",
        "def": "unset",
        "what": "Azure OpenAI resource endpoint."
      },
      {
        "key": "azure_openai_api_key",
        "env": "AGENTFOX_AZURE_OPENAI_API_KEY",
        "def": "unset",
        "what": "Azure OpenAI key."
      },
      {
        "key": "azure_openai_api_version",
        "env": "AGENTFOX_AZURE_OPENAI_API_VERSION",
        "def": "2024-10-21",
        "what": "Azure OpenAI API version."
      },
      {
        "key": "azure_openai_deployment",
        "env": "AGENTFOX_AZURE_OPENAI_DEPLOYMENT",
        "def": "unset",
        "what": "Azure OpenAI deployment name."
      },
      {
        "key": "aws_region",
        "env": "AGENTFOX_AWS_REGION",
        "def": "unset",
        "what": "Region for Bedrock (bedrock extra)."
      },
      {
        "key": "bedrock_model",
        "env": "AGENTFOX_BEDROCK_MODEL",
        "def": "anthropic.claude-sonnet-4-20250514-v1:0",
        "what": "Bedrock model id."
      },
      {
        "key": "vertex_project",
        "env": "AGENTFOX_VERTEX_PROJECT",
        "def": "unset",
        "what": "Google Cloud project for Vertex (vertex extra)."
      },
      {
        "key": "vertex_location",
        "env": "AGENTFOX_VERTEX_LOCATION",
        "def": "us-central1",
        "what": "Vertex region."
      },
      {
        "key": "vertex_model",
        "env": "AGENTFOX_VERTEX_MODEL",
        "def": "gemini-2.0-flash",
        "what": "Vertex model."
      },
      {
        "key": "litellm_base_url",
        "env": "AGENTFOX_LITELLM_BASE_URL",
        "def": "unset",
        "what": "A LiteLLM proxy to route through. On loopback it counts as local and does not egress."
      },
      {
        "key": "litellm_api_key",
        "env": "AGENTFOX_LITELLM_API_KEY",
        "def": "unset",
        "what": "Key for that proxy."
      }
    ]
  },
  {
    "id": "budgets",
    "title": "Budgets, loops and reliability",
    "rows": [
      {
        "key": "loop_max_steps",
        "env": "AGENTFOX_LOOP_MAX_STEPS",
        "def": "25",
        "what": "Most steps one run may take before loop.runaway blocks it."
      },
      {
        "key": "loop_max_repeats",
        "env": "AGENTFOX_LOOP_MAX_REPEATS",
        "def": "2",
        "what": "Identical re-issued calls tolerated."
      },
      {
        "key": "loop_max_cycle_length",
        "env": "AGENTFOX_LOOP_MAX_CYCLE_LENGTH",
        "def": "4",
        "what": "Longest alternating cycle detected."
      },
      {
        "key": "loop_max_steps_without_progress",
        "env": "AGENTFOX_LOOP_MAX_STEPS_WITHOUT_PROGRESS",
        "def": "5",
        "what": "Steps that produce no new observation before the run counts as stuck."
      },
      {
        "key": "fallback_chain",
        "env": "AGENTFOX_FALLBACK_CHAIN",
        "def": "[]",
        "what": "Model degradation ladder, preferred first. Empty means fail rather than serve from a model the agent was not evaluated on."
      },
      {
        "key": "breaker_failure_threshold",
        "env": "AGENTFOX_BREAKER_FAILURE_THRESHOLD",
        "def": "5",
        "what": "Provider failures before the circuit breaker opens."
      },
      {
        "key": "breaker_recovery_seconds",
        "env": "AGENTFOX_BREAKER_RECOVERY_SECONDS",
        "def": "30.0",
        "what": "How long it stays open."
      },
      {
        "key": "admission_rate_per_second",
        "env": "AGENTFOX_ADMISSION_RATE_PER_SECOND",
        "def": "200.0",
        "what": "Admission control on /v1/*: sustained rate."
      },
      {
        "key": "admission_burst",
        "env": "AGENTFOX_ADMISSION_BURST",
        "def": "400",
        "what": "Burst allowance."
      },
      {
        "key": "admission_max_concurrent",
        "env": "AGENTFOX_ADMISSION_MAX_CONCURRENT",
        "def": "256",
        "what": "Concurrent requests admitted."
      },
      {
        "key": "admission_shed_below_priority",
        "env": "AGENTFOX_ADMISSION_SHED_BELOW_PRIORITY",
        "def": "normal",
        "what": "Under saturation, work below this priority is shed first."
      },
      {
        "key": "service_probe_interval_seconds",
        "env": "AGENTFOX_SERVICE_PROBE_INTERVAL_SECONDS",
        "def": "5.0",
        "what": "How long a dependency health probe is reused. Status endpoints always probe fresh."
      },
      {
        "key": "verified_state_max_age_seconds",
        "env": "AGENTFOX_VERIFIED_STATE_MAX_AGE_SECONDS",
        "def": "300",
        "what": "How fresh a state read must be to authorise an irreversible act."
      },
      {
        "key": "data_access_strictness",
        "env": "AGENTFOX_DATA_ACCESS_STRICTNESS",
        "def": "standard",
        "what": "standard escalates a query on an undeclared table; strict blocks it."
      },
      {
        "key": "sql_dialect",
        "env": "AGENTFOX_SQL_DIALECT",
        "def": "postgres",
        "what": "Dialect SQL artefacts are parsed in (sql extra). A wrong parse fails closed."
      },
      {
        "key": "memory_unverified_ttl_seconds",
        "env": "AGENTFOX_MEMORY_UNVERIFIED_TTL_SECONDS",
        "def": "86400",
        "what": "How long an unverified memory entry survives before it decays."
      },
      {
        "key": "agent_message_validity_seconds",
        "env": "AGENTFOX_AGENT_MESSAGE_VALIDITY_SECONDS",
        "def": "300",
        "what": "Oldest an inter-agent message signature may be and still verify."
      },
      {
        "key": "degraded_warn_ratio",
        "env": "AGENTFOX_DEGRADED_WARN_RATIO",
        "def": "0.05",
        "what": "Share of checks in the window answered without a selected detector above which the gateway logs a warning and /api/health reports unhealthy. Per process."
      },
      {
        "key": "degraded_window_seconds",
        "env": "AGENTFOX_DEGRADED_WINDOW_SECONDS",
        "def": "60",
        "what": "The sliding window for degraded_warn_ratio."
      },
      {
        "key": "degraded_warn_min_checks",
        "env": "AGENTFOX_DEGRADED_WARN_MIN_CHECKS",
        "def": "20",
        "what": "Fewer checks than this in the window never warn."
      },
      {
        "key": "agent_breaker_mode",
        "env": "AGENTFOX_AGENT_BREAKER_MODE",
        "def": "alert",
        "what": "Per-agent circuit breaker: off, alert (raise an issue), or pause (also refuse the agent's calls for the cool-down, then probe). Each agent can override."
      },
      {
        "key": "agent_breaker_window_seconds",
        "env": "AGENTFOX_AGENT_BREAKER_WINDOW_SECONDS",
        "def": "300",
        "what": "Window the breaker counts blocked decisions over."
      },
      {
        "key": "agent_breaker_min_calls",
        "env": "AGENTFOX_AGENT_BREAKER_MIN_CALLS",
        "def": "20",
        "what": "Decisions needed in the window before it can trip."
      },
      {
        "key": "agent_breaker_block_ratio",
        "env": "AGENTFOX_AGENT_BREAKER_BLOCK_RATIO",
        "def": "0.5",
        "what": "Share of blocked decisions that trips it."
      },
      {
        "key": "agent_breaker_cooldown_seconds",
        "env": "AGENTFOX_AGENT_BREAKER_COOLDOWN_SECONDS",
        "def": "300",
        "what": "How long a paused agent stays paused before probing."
      },
      {
        "key": "agent_breaker_probe_calls",
        "env": "AGENTFOX_AGENT_BREAKER_PROBE_CALLS",
        "def": "5",
        "what": "Calls let through to test recovery."
      }
    ]
  },
  {
    "id": "entitlement",
    "title": "Entitlement",
    "rows": [
      {
        "key": "entitlement_engine",
        "env": "AGENTFOX_ENTITLEMENT_ENGINE",
        "def": "native",
        "what": "native, or openfga. The OpenFGA adapter is a declared seam, not an implementation yet."
      },
      {
        "key": "openfga_url",
        "env": "AGENTFOX_OPENFGA_URL",
        "def": "unset",
        "what": "OpenFGA endpoint."
      },
      {
        "key": "openfga_store_id",
        "env": "AGENTFOX_OPENFGA_STORE_ID",
        "def": "unset",
        "what": "OpenFGA store."
      },
      {
        "key": "k_anonymity_threshold",
        "env": "AGENTFOX_K_ANONYMITY_THRESHOLD",
        "def": "5",
        "what": "Smallest group an aggregate answer may describe."
      }
    ]
  },
  {
    "id": "audit",
    "title": "Audit and evidence",
    "rows": [
      {
        "key": "audit_signing_key",
        "env": "AGENTFOX_AUDIT_SIGNING_KEY",
        "def": "dev-insecure-checkpoint-key",
        "what": "Signs audit-chain checkpoints. Keep it outside the database. Outside development the gateway refuses to start while it is the published default."
      },
      {
        "key": "audit_signing_key_previous",
        "env": "AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS",
        "def": "unset",
        "what": "Retired signing keys, comma-separated. Checkpoints they signed still verify; agentfox admin keys rotate verifies the chain and re-signs them with the current key, then remove them."
      },
      {
        "key": "audit_checkpoint_interval",
        "env": "AGENTFOX_AUDIT_CHECKPOINT_INTERVAL",
        "def": "100",
        "what": "Chain entries between signed checkpoints."
      },
      {
        "key": "redact_at_capture",
        "env": "AGENTFOX_REDACT_AT_CAPTURE",
        "def": "true",
        "what": "Redact detected sensitive values before they are written to the audit log."
      }
    ]
  },
  {
    "id": "improvement",
    "title": "Improvement loop and scheduler",
    "rows": [
      {
        "key": "improvement_frozen",
        "env": "AGENTFOX_IMPROVEMENT_FROZEN",
        "def": "false",
        "what": "Kill switch for the improvement loop: nothing is applied automatically; proposals are still filed."
      },
      {
        "key": "improvement_actor_id",
        "env": "AGENTFOX_IMPROVEMENT_ACTOR_ID",
        "def": "agentfox-improver",
        "what": "The identity automated changes are recorded under."
      },
      {
        "key": "improvement_max_auto_changes_per_day",
        "env": "AGENTFOX_IMPROVEMENT_MAX_AUTO_CHANGES_PER_DAY",
        "def": "20",
        "what": "Cap on automated applies per tenant per day."
      },
      {
        "key": "improvement_rollback_budget",
        "env": "AGENTFOX_IMPROVEMENT_ROLLBACK_BUDGET",
        "def": "0.05",
        "what": "A change class rolled back more often than this drops an autonomy level."
      },
      {
        "key": "canary_min_dwell_seconds",
        "env": "AGENTFOX_CANARY_MIN_DWELL_SECONDS",
        "def": "3600",
        "what": "Minimum time a canaried change runs before it can be settled."
      },
      {
        "key": "canary_max_block_rate_drop",
        "env": "AGENTFOX_CANARY_MAX_BLOCK_RATE_DROP",
        "def": "0.15",
        "what": "How much less the candidate may block before the canary rolls it back."
      },
      {
        "key": "scheduler_enabled",
        "env": "AGENTFOX_SCHEDULER_ENABLED",
        "def": "true",
        "what": "Whether scheduled jobs are queued."
      },
      {
        "key": "monitor_batch_limit",
        "env": "AGENTFOX_MONITOR_BATCH_LIMIT",
        "def": "5",
        "what": "AgentFox Enterprise (monitoring). Most due monitors one monitors.run job runs; the rest wait for the next runner call."
      },
      {
        "key": "monitor_failure_threshold",
        "env": "AGENTFOX_MONITOR_FAILURE_THRESHOLD",
        "def": "3",
        "what": "AgentFox Enterprise (monitoring). Failed runs in a row before a monitor raises a monitor_failing finding."
      },
      {
        "key": "job_stuck_after_seconds",
        "env": "AGENTFOX_JOB_STUCK_AFTER_SECONDS",
        "def": "900",
        "what": "A running job older than this counts as crashed and is recovered."
      },
      {
        "key": "job_backoff_base_seconds",
        "env": "AGENTFOX_JOB_BACKOFF_BASE_SECONDS",
        "def": "60",
        "what": "Base of the exponential retry delay."
      },
      {
        "key": "live_probes_enabled",
        "env": "AGENTFOX_LIVE_PROBES_ENABLED",
        "def": "true",
        "what": "Kill switch for scheduled probes against deployed agents. Each target also needs its own recorded opt-in."
      },
      {
        "key": "showcase_enabled",
        "env": "AGENTFOX_SHOWCASE_ENABLED",
        "def": "false",
        "what": "Probe the demo support agent in its own tenant every hour and publish the counts at GET /api/public/showcase."
      },
      {
        "key": "showcase_org_id",
        "env": "AGENTFOX_SHOWCASE_ORG_ID",
        "def": "org_showcase",
        "what": "The tenant the showcase lives in. The public endpoint reads nothing else."
      },
      {
        "key": "jobs_on_traffic",
        "env": "AGENTFOX_JOBS_ON_TRAFFIC",
        "def": "true",
        "what": "Also run due jobs off ordinary traffic, at most every 10 minutes per instance, for hosts whose cron runs once a day."
      }
    ]
  },
  {
    "id": "evaluation",
    "title": "Evaluation",
    "rows": [
      {
        "key": "eval_runner",
        "env": "AGENTFOX_EVAL_RUNNER",
        "def": "native",
        "what": "native, or promptfoo."
      },
      {
        "key": "promptfoo_bin",
        "env": "AGENTFOX_PROMPTFOO_BIN",
        "def": "promptfoo",
        "what": "The promptfoo executable."
      },
      {
        "key": "online_eval_sample_rate",
        "env": "AGENTFOX_ONLINE_EVAL_SAMPLE_RATE",
        "def": "0.25",
        "what": "Share of production traffic agentfox test online samples."
      },
      {
        "key": "drift_psi_threshold",
        "env": "AGENTFOX_DRIFT_PSI_THRESHOLD",
        "def": "0.2",
        "what": "Population stability index above which agentfox report drift reports drift."
      }
    ]
  },
  {
    "id": "integrations",
    "title": "Integrations: webhooks and trace correlation",
    "rows": [
      {
        "key": "webhook_url",
        "env": "AGENTFOX_WEBHOOK_URL",
        "def": "unset",
        "what": "Each new finding at or above webhook_min_severity is POSTed here. Needs allow_egress."
      },
      {
        "key": "webhook_secret",
        "env": "AGENTFOX_WEBHOOK_SECRET",
        "def": "unset",
        "what": "Adds X-AgentFox-Signature: sha256=<HMAC of the body>."
      },
      {
        "key": "webhook_timeout_seconds",
        "env": "AGENTFOX_WEBHOOK_TIMEOUT_SECONDS",
        "def": "3.0",
        "what": "Per-delivery timeout; one retry on 5xx or timeout."
      },
      {
        "key": "webhook_min_severity",
        "env": "AGENTFOX_WEBHOOK_MIN_SEVERITY",
        "def": "high",
        "what": "critical, high, medium or low."
      },
      {
        "key": "slack_webhook_url",
        "env": "AGENTFOX_SLACK_WEBHOOK_URL",
        "def": "unset",
        "what": "AgentFox Enterprise (monitoring). Slack incoming webhook for monitor findings opened, reopened or closed. Needs allow_egress. A tenant can also set its own (PUT /api/alerts/slack)."
      },
      {
        "key": "slack_min_severity",
        "env": "AGENTFOX_SLACK_MIN_SEVERITY",
        "def": "medium",
        "what": "critical, high, medium or low."
      },
      {
        "key": "github_webhook_secret",
        "env": "AGENTFOX_GITHUB_WEBHOOK_SECRET",
        "def": "unset",
        "what": "Verifies X-Hub-Signature-256 on /api/integrations/github/webhook. A connection may carry its own instead; with neither, push deliveries are refused."
      },
      {
        "key": "correlation_push",
        "env": "AGENTFOX_CORRELATION_PUSH",
        "def": "false",
        "what": "Write the verdict back onto the LangSmith or Langfuse run. Correlation itself needs no setting."
      },
      {
        "key": "correlation_timeout_seconds",
        "env": "AGENTFOX_CORRELATION_TIMEOUT_SECONDS",
        "def": "2.0",
        "what": "Timeout for that write-back."
      },
      {
        "key": "langsmith_api_key",
        "env": "AGENTFOX_LANGSMITH_API_KEY",
        "def": "unset",
        "what": "LangSmith key for write-back."
      },
      {
        "key": "langsmith_project",
        "env": "AGENTFOX_LANGSMITH_PROJECT",
        "def": "unset",
        "what": "LangSmith project."
      },
      {
        "key": "langsmith_api_url",
        "env": "AGENTFOX_LANGSMITH_API_URL",
        "def": "https://api.smith.langchain.com",
        "what": "LangSmith API."
      },
      {
        "key": "langsmith_ui_url",
        "env": "AGENTFOX_LANGSMITH_UI_URL",
        "def": "https://smith.langchain.com",
        "what": "LangSmith UI, for links."
      },
      {
        "key": "langfuse_public_key",
        "env": "AGENTFOX_LANGFUSE_PUBLIC_KEY",
        "def": "unset",
        "what": "Langfuse public key."
      },
      {
        "key": "langfuse_secret_key",
        "env": "AGENTFOX_LANGFUSE_SECRET_KEY",
        "def": "unset",
        "what": "Langfuse secret key."
      },
      {
        "key": "langfuse_project",
        "env": "AGENTFOX_LANGFUSE_PROJECT",
        "def": "unset",
        "what": "Langfuse project."
      },
      {
        "key": "langfuse_host",
        "env": "AGENTFOX_LANGFUSE_HOST",
        "def": "https://cloud.langfuse.com",
        "what": "Langfuse host."
      },
      {
        "key": "outbound_allow_private_hosts",
        "env": "AGENTFOX_OUTBOUND_ALLOW_PRIVATE_HOSTS",
        "def": "false",
        "what": "Let outbound calls an operator configures (API specs, custom models, probe targets, GitHub) reach loopback and private addresses. Link-local (cloud metadata), multicast and reserved addresses stay refused."
      }
    ]
  }
];

const OUTSIDE: { name: string; what: string }[] = [
  { name: "AGENTFOX_STATE_DIR", what: "Directory for the default database and evidence. It decides the defaults of database_url and evidence_dir, so it is not itself a setting." },
  { name: "AGENTFOX_CONFIG", what: "Path to the TOML file to read. It must exist. none, off or - turns file loading off." },
  { name: "AGENTFOX_AGENT", what: "Agent slug for agentfox.auto() when none is passed. Then OTEL_SERVICE_NAME, SERVICE_NAME, APP_NAME, K_SERVICE, the script name, and finally default-agent." },
  { name: "AGENTFOX_URL, AGENTFOX_API_KEY", what: "Your account's gateway and API key, read by agentfox.auto(), the SDK, the LiteLLM guardrail and the CLI: agentfox up, scan --submit, and findings, agents list, permit, declare, policy, report and test suites, which then read and write the account. agentfox login saves both in .agentfox/agentfox.env. The older names AGENTFOX_API_URL and AGENTFOX_API_TOKEN are still accepted." },
  { name: "AGENTFOX_LOCAL", what: "1 makes the CLI use this machine's database although an account key is configured: what coding-agent hooks record. An explicit AGENTFOX_DATABASE_URL does the same." },
  { name: "AGENTFOX_SOCKET", what: "Path of the coding-agent hook daemon's socket. Default: run/agentfoxd.sock under the state directory, or a short private path in the system temp directory when that is too long for a Unix socket. Moves only the socket." },
  { name: "AGENTFOX_USER", what: "Without an API key, the identity agentfox scan --submit sends to a development deployment." },
  { name: "AGENTFOX_RUN_DIR", what: "Where small runtime records go (which agentfox serve is running, which warnings were already shown). Default: run/ under the state directory." },
  { name: "AGENTFOX_AUDIT_KEY", what: "Then AGENTFOX_AUDIT_SIGNING_KEY. Read by the verify_chain.py inside an evidence package to check checkpoint signatures." },
  { name: "AGENTFOX_MCP_LOG_LEVEL", what: "Log level of agentfox serve mcp. Default WARNING." },
  { name: "CRON_SECRET", what: "Accepted in addition to cron_secret by /api/internal/jobs/run (Vercel Cron sets it)." },
  { name: "JEV_API_KEY", what: "Key for the hosted jev judgment tier. Without it that tier is unavailable." },
];

const DASHBOARD: { name: string; def: string; what: string }[] = [
  { name: "AGENTFOX_API_URL", def: "http://127.0.0.1:8080", what: "The gateway the dashboard calls, server to server. Include the scheme." },
  { name: "AGENTFOX_API_TOKEN", def: "unset", what: "A static operator token for the dashboard's own calls. A signed-in user's token takes precedence." },
  { name: "AGENTFOX_USER", def: "admin@example.com", what: "The development identity header value, used when there is no token. A gateway outside development refuses it." },
  { name: "AGENTFOX_PLAYGROUND_API_URL", def: "AGENTFOX_API_URL", what: "The gateway address the visitor's browser uses on the public playground page." },
  { name: "AGENTFOX_SERVICE_AUTH_SECRET", def: "unset", what: "Must equal the gateway's service_auth_secret, or GitHub sign-in fails at provisioning." },
  { name: "AGENTFOX_SITE_URL", def: "the public site", what: "Canonical URL used in page metadata." },
  { name: "AGENTFOX_SELF_HOSTED", def: "unset", what: "Marks a self-hosted dashboard in the interface." },
  { name: "GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET", def: "unset", what: "The GitHub OAuth app for sign-in. Unset: sign-in is unavailable. A GitHub sign-in token lasts 365 days; signing out revokes it at the gateway." },
  { name: "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET", def: "unset", what: "A Google OAuth client for \"Continue with Google\". Callback: /api/auth/google/callback. The button shows only when both are set." },
  { name: "MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET", def: "unset", what: "A Microsoft Entra app registration (any account type) for \"Continue with Microsoft\". Callback: /api/auth/microsoft/callback. The button shows only when both are set." },
];

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Configuration</h1>
      <p className="docs-lede">
        Every setting AgentFox reads: its environment variable, its <code>agentfox.toml</code>{" "}
        key, its default, and what it changes. Then the integration formats (webhooks, OTLP,
        SIEM, metrics) and the gateway&apos;s headers. The defaults are offline: no egress, the{" "}
        <code>echo</code> provider, and detector packs in observe.
      </p>

      <h2 id="sources">How a setting is resolved</h2>
      <ol>
        <li>
          <code>AGENTFOX_&lt;KEY&gt;</code> in the environment.
        </li>
        <li>
          The <code>[agentfox]</code> table of the file named by <code>AGENTFOX_CONFIG</code>,
          or of <code>./agentfox.toml</code> in the working directory.
        </li>
        <li>The default in the tables below.</li>
      </ol>
      <p>
        The key in the file is the setting name: <code>taint_scope = &quot;argument&quot;</code>{" "}
        in the file is <code>AGENTFOX_TAINT_SCOPE=argument</code> in the environment. Lists
        are TOML arrays in the file and JSON in the environment. Unknown keys are ignored
        with a warning naming them. Values are validated, and some (<code>taint_scope</code>,{" "}
        <code>webhook_min_severity</code>) stop startup on a typo rather than falling back.
        Settings are read once per process.
      </p>
      <Code>{`export AGENTFOX_FAIL_MODE=closed
export AGENTFOX_ENABLED_DETECTORS='["pii.native","secrets.native"]'
python -c "from agentfox.core.config import Settings as S; s = S(); print(s.fail_mode, s.enabled_detectors)"`}</Code>
      <Output>{`closed ['pii.native', 'secrets.native']`}</Output>
      <Callout kind="note" title="Defaults that depend on where you are">
        <code>&lt;state dir&gt;</code> below is <code>AGENTFOX_STATE_DIR</code> if set, the
        repository root in a source checkout, and otherwise{" "}
        <code>$XDG_DATA_HOME/agentfox</code> or <code>~/.agentfox</code>. See{" "}
        <Link href="/docs/reference/install">where state lives</Link>.
      </Callout>

      <nav aria-label="Groups">
        <p>
          {GROUPS.map((g, i) => (
            <span key={g.id}>
              {i > 0 ? " · " : ""}
              <a href={"#" + g.id}>{g.title}</a>
            </span>
          ))}
          {" · "}
          <a href="#webhooks">Webhook deliveries</a> · <a href="#otlp">OpenTelemetry</a> ·{" "}
          <a href="#siem">SIEM export</a> · <a href="#metrics">Metrics</a> ·{" "}
          <a href="#gateway">Gateway requests</a> · <a href="#compose">Docker Compose</a> ·{" "}
          <a href="#outside">Read outside Settings</a> ·{" "}
          <a href="#dashboard">Dashboard</a>
        </p>
      </nav>

      {GROUPS.map((group) => (
        <section key={group.id}>
          <h2 id={group.id}>{group.title}</h2>
          <div className="docs-table" tabIndex={0}><table>
            <thead>
              <tr>
                <th>Key and variable</th>
                <th>Default</th>
                <th>What it does</th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row) => (
                <tr key={row.key} id={"set-" + row.key}>
                  <td>
                    <code>{row.key}</code>
                    <br />
                    <code>{row.env}</code>
                  </td>
                  <td>
                    <code>{row.def}</code>
                  </td>
                  <td>{row.what}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </section>
      ))}

      <h2 id="webhooks">Webhook deliveries</h2>
      <p>
        With <code>webhook_url</code> set and <code>allow_egress</code> on, AgentFox POSTs a
        JSON body for each finding at or above <code>webhook_min_severity</code>:
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Part</th><th>What it is</th></tr>
        </thead>
        <tbody>
          <tr><td>Events</td><td><code>finding.created</code>; <code>finding.resolved</code>, <code>finding.suppressed</code>, <code>finding.reopened</code> on a status change; <code>webhook.test</code> from <code>agentfox.core.webhooks.send_test_event()</code>.</td></tr>
          <tr><td>Body</td><td><code>{`{"event", "finding", "org_id", "sent_at"}`}</code>. <code>finding</code> has the fields of <code>GET /api/findings/{"{id}"}</code>; it is null for a test.</td></tr>
          <tr><td><code>X-AgentFox-Signature</code></td><td><code>sha256=</code> and the hex HMAC-SHA256 of the raw body, keyed with <code>webhook_secret</code>. Verify before parsing; compare in constant time.</td></tr>
          <tr><td><code>X-AgentFox-Event</code></td><td>The event name.</td></tr>
          <tr><td><code>X-AgentFox-Delivery</code></td><td>A delivery id. A retry reuses it with the same body and signature: de-duplicate on it.</td></tr>
          <tr><td><code>X-AgentFox-Timestamp</code></td><td>Unix seconds. Not signed: check freshness with <code>sent_at</code>, which the signature covers.</td></tr>
          <tr><td>Retries</td><td>One retry after half a second on a timeout, connection error or 5xx. A redirect is a failure. Failures are logged and dropped; use the SIEM export to backfill.</td></tr>
          <tr><td>Queue</td><td>A background thread behind a 1,000-item queue, so delivery never slows the code that raised the finding. Nothing is sent for work that was rolled back.</td></tr>
        </tbody>
      </table></div>

      <h2 id="otlp">OpenTelemetry ingest</h2>
      <p>
        <code>POST /v1/traces</code> takes an OTLP/HTTP trace export, protobuf
        (<code>application/x-protobuf</code>, the exporters&apos; default) or JSON, either
        gzip-compressed. Protobuf needs <code>agentfox[otel]</code>; without it the server
        answers 415 and JSON still works. Outside development it needs an agent key or an
        operator token. Each agent a span names goes into the registry, and one nobody
        registered raises a <code>shadow_agent</code> finding. The agent is{" "}
        <code>agentfox.agent</code>, else <code>service.name</code>, else{" "}
        <code>gen_ai.agent.name</code>. Ingest records spans only: it runs no policy or
        detectors and keeps no parent-child structure.
      </p>
      <p>
        AgentFox has no push exporter. <code>GET /api/export/siem?format=otlp</code> returns
        decisions and findings as OTLP/JSON log records to forward yourself.
      </p>

      <h2 id="siem">SIEM export</h2>
      <p>
        <code>GET /api/export/siem</code> returns recent decisions and findings, oldest
        first, as <code>text/plain</code>. It needs a token when token auth is on.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Parameter</th><th>Default</th><th>Values</th></tr>
        </thead>
        <tbody>
          <tr><td><code>format</code></td><td><code>jsonl</code></td><td><code>jsonl</code>, <code>cef</code> (ArcSight), <code>leef</code> (QRadar), <code>otlp</code> (OTLP/JSON log records)</td></tr>
          <tr><td><code>since_days</code></td><td>7</td><td>How far back.</td></tr>
          <tr><td><code>limit</code></td><td>1000</td><td>Applied to decisions and to findings separately.</td></tr>
        </tbody>
      </table></div>
      <p>
        Findings are <code>governance.finding.&lt;type&gt;</code> events. CEF and LEEF severity
        runs 0 to 10 (block 8, escalate 6, a critical finding 10). A decision recorded without
        a trace exports with <code>agent: null</code>.
      </p>

      <h2 id="metrics">Prometheus metrics</h2>
      <p>
        <code>GET /metrics</code> serves the Prometheus text format with no token; keep it on
        a private network. Every series is computed from the last 24 hours of records at
        scrape time, so the <code>_total</code> series go down as records age out:{" "}
        <code>rate()</code> and <code>increase()</code> misread them. Alert on the value, for
        example <code>agentfox_detector_degraded_total &gt; 0</code> or{" "}
        <code>agentfox_open_findings{"{"}severity=&quot;critical&quot;{"}"} &gt; 0</code>.
        Others worth alerting on: <code>agentfox_detector_duration_ms_max</code>,{" "}
        <code>agentfox_missed_escalation_rate</code>, <code>agentfox_circuit_breaker_state</code>{" "}
        (1 is open). Observe-mode decisions carry <code>mode=&quot;observe&quot;</code>. The
        per-process <code>agentfox_checks_total</code> and{" "}
        <code>agentfox_checks_degraded_total</code> only go up until restart, so{" "}
        <code>rate()</code> works on those.
      </p>

      <h2 id="gateway">Gateway requests</h2>
      <p>
        Headers the proxy routes (<code>/v1/chat/completions</code>, <code>/v1/messages</code>)
        read and return. Routes and bodies are in the <Link href="/docs/reference/api">HTTP API reference</Link>.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Request header</th><th>What it does</th></tr>
        </thead>
        <tbody>
          <tr><td><code>X-AgentFox-Agent</code></td><td>The agent slug. Without it, no grant or agent-scoped policy applies.</td></tr>
          <tr><td><code>X-AgentFox-Session</code></td><td>Ties calls into one conversation; turns on loop checks (<code>loop_*</code> settings).</td></tr>
          <tr><td><code>X-AgentFox-Intent</code></td><td>The declared task.</td></tr>
          <tr><td><code>X-AgentFox-Trust</code></td><td>JSON map of message index to source, e.g. <code>{`{"1":"retrieved"}`}</code>.</td></tr>
          <tr><td><code>X-AgentFox-Environment</code></td><td>Default <code>production</code>.</td></tr>
          <tr><td><code>X-AgentFox-Provider</code></td><td>Which configured provider to forward to (default <code>default_provider</code>). Outside development, naming a provider other than the default needs an agent key or API token.</td></tr>
          <tr><td><code>X-AgentFox-Stream-Mode</code></td><td><code>buffered</code> or <code>windowed</code> for this request (below).</td></tr>
          <tr><td><code>X-AgentFox-Priority</code></td><td>Admission priority when shedding load (default <code>normal</code>).</td></tr>
          <tr><td><code>X-AgentFox-Approval</code></td><td>An approved <code>apr_…</code> id: the held request runs once.</td></tr>
          <tr><td><code>Authorization: Bearer nom_agt_…</code></td><td>Optional agent key.</td></tr>
        </tbody>
      </table></div>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Response header</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>x-agentfox-verdict</code>, <code>x-agentfox-applied-verdict</code></td><td>What happened to this request. Gate on this.</td></tr>
          <tr><td><code>x-agentfox-effective-verdict</code>, <code>x-agentfox-would-be-verdict</code></td><td>What the policy asks for; differs only in observe.</td></tr>
          <tr><td><code>x-agentfox-mode</code></td><td><code>observe</code> or <code>enforce</code>.</td></tr>
          <tr><td><code>x-agentfox-trace</code>, <code>x-agentfox-decision</code></td><td>Ids to look the decision up by.</td></tr>
          <tr><td><code>x-agentfox-latency-ms</code></td><td>Time spent in governance.</td></tr>
          <tr><td><code>x-agentfox-explain</code></td><td>Link to the trace in the app, when <code>console_url</code> is set.</td></tr>
          <tr><td><code>x-agentfox-degraded</code></td><td>A dependency was unavailable while serving the request.</td></tr>
        </tbody>
      </table></div>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Status</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td>200</td><td>Allowed; content may have been redacted or tokenised.</td></tr>
          <tr><td>428</td><td>Held for a person (<code>agentfox_approval_required</code>, with <code>approval_id</code> and <code>poll</code>). Retry with <code>X-AgentFox-Approval</code> once approved.</td></tr>
          <tr><td>403</td><td>Blocked (<code>agentfox_policy_violation</code>). Do not retry.</td></tr>
          <tr><td>429</td><td>Load shed before governance ran (<code>agentfox_admission_shed</code>). Retry after <code>Retry-After</code>.</td></tr>
          <tr><td>503</td><td>A dependency is down and <code>fail_mode</code> says refuse (<code>agentfox_service_degraded</code>).</td></tr>
        </tbody>
      </table></div>
      <p>
        <code>/v1/guard/*</code> answer 200 with a <code>verdict</code> field for every
        decision; 429 and 503 apply to every <code>/v1</code> route.
      </p>
      <h3 id="streaming">Streaming modes</h3>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th><code>streaming_mode</code></th><th>Behaviour</th></tr>
        </thead>
        <tbody>
          <tr><td><code>buffered</code> (default)</td><td>The whole answer is collected and checked before anything is sent. Output checks are identical to a non-streamed call; first-token latency is the cost.</td></tr>
          <tr><td><code>windowed</code></td><td>Chunks are forwarded as they arrive while detectors run over a growing window (<code>stream_window_chars</code>, 200). A block ends the stream but cannot recall what was already sent.</td></tr>
        </tbody>
      </table></div>
      <p>
        A streamed response sends headers before anything is decided, so it carries{" "}
        <code>x-agentfox-streaming: enforced</code> and an empty trace header; the decision
        arrives as an <code>{`{"agentfox": {...}}`}</code> data frame before{" "}
        <code>[DONE]</code>. A streamed Anthropic reply carries text only: do not stream tool
        use through <code>/v1/messages</code>. <code>agentfox.auto()</code> checks a stream
        only once it is exhausted.
      </p>

      <h2 id="compose">What deploy/docker-compose.yml sets</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Variable</th><th>Compose value</th><th>Why it differs from the default</th></tr>
        </thead>
        <tbody>
          <tr><td><code>AGENTFOX_DATABASE_URL</code></td><td>the bundled Postgres</td><td>Multi-worker servers refuse SQLite.</td></tr>
          <tr><td><code>AGENTFOX_ENVIRONMENT</code></td><td><code>production</code></td><td>Tokens required; the development audit key is refused.</td></tr>
          <tr><td><code>AGENTFOX_ENFORCEMENT_BUDGET_MS</code>, <code>AGENTFOX_DETECTOR_TIMEOUT_MS</code></td><td>100, 40</td><td>Raise both to run a slow model such as <code>safety.granite</code> on CPU.</td></tr>
          <tr><td><code>AGENTFOX_ENABLED_DETECTORS</code></td><td>the defaults plus <code>injection.similarity</code></td><td>Its weights are in the image.</td></tr>
          <tr><td><code>AGENTFOX_POLICY_ENGINE</code>, <code>AGENTFOX_OPA_URL</code></td><td><code>native</code>, <code>http://opa:8181</code></td><td>Set <code>opa</code> to use the sidecar; it falls back to native when unreachable.</td></tr>
          <tr><td><code>AGENTFOX_EVIDENCE_DIR</code></td><td><code>/var/agentfox/evidence</code></td><td>A volume, so evidence packages survive a restart.</td></tr>
          <tr><td><code>AGENTFOX_AUDIT_SIGNING_KEY</code>, <code>AGENTFOX_SERVICE_AUTH_SECRET</code></td><td>required</td><td>Compose refuses to start without them (<code>openssl rand -hex 32</code>).</td></tr>
          <tr><td><code>AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES</code></td><td><code>&quot;0&quot;</code></td><td>Below.</td></tr>
        </tbody>
      </table></div>

      <h3 id="gated-models">Licence-gated models (Llama Guard, Prompt Guard 2)</h3>
      <p>
        The published image never carries gated weights. To run <code>safety.restricted</code>{" "}
        (Llama Guard 3) or Prompt Guard 2:
      </p>
      <ol>
        <li>Accept Meta&apos;s licence for the model on Hugging Face.</li>
        <li>
          Build the image yourself with that account&apos;s token:{" "}
          <code>export HF_TOKEN=hf_…</code>, then{" "}
          <code>docker compose -f deploy/docker-compose.yml build gateway</code>. The token is a
          BuildKit secret and is not written to a layer. Without it the step is skipped.
        </li>
        <li>
          The build arg <code>GATED_MODELS</code> (space-separated, default{" "}
          <code>meta-llama/Llama-Guard-3-8B</code>) picks what to bake. Add{" "}
          <code>meta-llama/Llama-Prompt-Guard-2-22M</code> or <code>-86M</code> and set{" "}
          <code>prompt_injection_classifier_model</code>, or use{" "}
          <code>meta-llama/Llama-Guard-3-1B</code> with <code>llama_guard_model</code>.
        </li>
        <li>
          Add the detector to <code>AGENTFOX_ENABLED_DETECTORS</code> and set{" "}
          <code>AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1</code>. The code refuses to load
          these models without it.
        </li>
      </ol>

      <h2 id="outside">Read outside Settings</h2>
      <p>
        A few variables are read straight from the environment, because they decide where
        settings come from or are used by a separate program. None of them can go in{" "}
        <code>agentfox.toml</code>.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Variable</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          {OUTSIDE.map((v) => (
            <tr key={v.name}>
              <td>
                <code>{v.name}</code>
              </td>
              <td>{v.what}</td>
            </tr>
          ))}
        </tbody>
      </table></div>

      <h2 id="dashboard">Dashboard</h2>
      <p>
        The web app is a separate Next.js process with its own variables. Each{" "}
        <code>AGENTFOX_</code> name below falls back to its <code>AGENTFOX_</code> spelling
        (for example <code>AGENTFOX_API_URL</code>) when unset. They are read at request time,
        so one image can point at any gateway.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Variable</th>
            <th>Default</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          {DASHBOARD.map((v) => (
            <tr key={v.name}>
              <td>
                <code>{v.name}</code>
              </td>
              <td>{v.def}</td>
              <td>{v.what}</td>
            </tr>
          ))}
        </tbody>
      </table></div>

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <b>A hosted provider or webhook does nothing.</b> <code>allow_egress</code> is false.
          A configured key or URL with egress off sends nothing.
        </li>
        <li>
          <b>A detector you enabled never fires.</b> Its extra or weights are missing, so it is
          unavailable and skipped. <code>agentfox doctor</code> lists the available ones.
        </li>
        <li>
          <b>The development header is refused.</b> <code>environment</code> is not a
          development name, so <code>auth_mode = auto</code> requires tokens.{" "}
          <code>agentfox admin auth status</code> says which.
        </li>
        <li>
          <b>GitHub sign-in fails at provisioning.</b> <code>service_auth_secret</code> differs
          between the gateway and the dashboard.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/reference/install", label: "Install options", why: "extras, models and where state lives" },
          { href: "/docs/self-host", label: "Self-hosting", why: "the settings a server must change" },
          { href: "/docs/concepts#provenance", label: "Provenance", why: "what taint_scope trades" },
        ]}
      />
    </article>
  );
}

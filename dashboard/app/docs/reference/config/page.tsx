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
        "def": "inside the installed package",
        "what": "The control catalog shipped inside the package. Change only to load your own catalog."
      },
      {
        "key": "policies_dir",
        "env": "AGENTFOX_POLICIES_DIR",
        "def": "inside the installed package",
        "what": "The policy packs shipped inside the package."
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
        "what": "auto follows environment; development accepts the X-Nometria-User header; token requires API tokens; oidc is reserved. Check with agentfox admin auth status."
      },
      {
        "key": "service_auth_secret",
        "env": "AGENTFOX_SERVICE_AUTH_SECRET",
        "def": "dev-insecure-service-secret",
        "what": "Shared between the gateway and the dashboard for the GitHub sign-in provisioning call. Must be identical on both, and must be changed for any real deployment."
      },
      {
        "key": "token_encryption_key",
        "env": "AGENTFOX_TOKEN_ENCRYPTION_KEY",
        "def": "unset",
        "what": "Fernet key that encrypts stored GitHub access tokens. Unset: connecting GitHub fails closed."
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
        "what": "Required (1/true) before safety.restricted (Llama Guard, non-OSI licence) will load."
      },
      {
        "key": "prompt_injection_classifier_model",
        "env": "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_MODEL",
        "def": "leolee99/PIGuard",
        "what": "Primary model for injection.classifier."
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
        "def": "true",
        "what": "Refuse to send a judgment if the local redactor cannot load."
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
        "what": "Signs audit-chain checkpoints. Change it before any real deployment, and keep it outside the database."
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
        "what": "Adds X-Nometria-Signature: sha256=<HMAC of the body>."
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
      }
    ]
  }
];

const OUTSIDE: { name: string; legacy: string; what: string }[] = [
  { name: "AGENTFOX_STATE_DIR", legacy: "—", what: "Directory for the default database and evidence. It decides the defaults of database_url and evidence_dir, so it is not itself a setting." },
  { name: "AGENTFOX_CONFIG", legacy: "NOMETRIA_CONFIG", what: "Path to the TOML file to read. It must exist. none, off or - turns file loading off." },
  { name: "AGENTFOX_AGENT", legacy: "NOMETRIA_AGENT", what: "Agent slug for agentfox.auto() when none is passed. Then OTEL_SERVICE_NAME, SERVICE_NAME, APP_NAME, K_SERVICE, the script name, and finally default-agent." },
  { name: "AGENTFOX_API_URL, AGENTFOX_API_TOKEN, AGENTFOX_USER", legacy: "NOMETRIA_API_URL, NOMETRIA_API_TOKEN, NOMETRIA_USER", what: "Where agentfox scan --submit sends a redacted summary, and the credential it uses." },
  { name: "AGENTFOX_AUDIT_KEY", legacy: "NOMETRIA_AUDIT_KEY, then the *_AUDIT_SIGNING_KEY names", what: "Read by the verify_chain.py inside an evidence package to check checkpoint signatures." },
  { name: "AGENTFOX_MCP_LOG_LEVEL", legacy: "NOMETRIA_MCP_LOG_LEVEL", what: "Log level of agentfox serve mcp. Default WARNING." },
  { name: "CRON_SECRET", legacy: "—", what: "Accepted in addition to cron_secret by /api/internal/jobs/run (Vercel Cron sets it)." },
  { name: "JEV_API_KEY", legacy: "—", what: "Key for the hosted jev judgment tier. Without it that tier is unavailable." },
];

const DASHBOARD: { name: string; def: string; what: string }[] = [
  { name: "AGENTFOX_API_URL", def: "http://127.0.0.1:8080", what: "The gateway the dashboard calls, server to server. Include the scheme." },
  { name: "AGENTFOX_API_TOKEN", def: "unset", what: "A static operator token for the dashboard's own calls. A signed-in user's token takes precedence." },
  { name: "AGENTFOX_USER", def: "admin@example.com", what: "The development identity header value, used when there is no token. A gateway outside development refuses it." },
  { name: "AGENTFOX_PLAYGROUND_API_URL", def: "AGENTFOX_API_URL", what: "The gateway address the visitor's browser uses on the public playground page." },
  { name: "AGENTFOX_SERVICE_AUTH_SECRET", def: "unset", what: "Must equal the gateway's service_auth_secret, or GitHub sign-in fails at provisioning." },
  { name: "AGENTFOX_SITE_URL", def: "the public site", what: "Canonical URL used in page metadata." },
  { name: "AGENTFOX_SELF_HOSTED", def: "unset", what: "Marks a self-hosted dashboard in the interface." },
  { name: "GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET", def: "unset", what: "The GitHub OAuth app for sign-in. Unset: sign-in is unavailable." },
];

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Reference</p>
      <h1>Configuration</h1>
      <p className="docs-lede">
        Every setting AgentFox reads: its environment variable, its <code>agentfox.toml</code>{" "}
        key, its default, and what it changes.
      </p>

      <h2>When to use this</h2>
      <p>
        Look a setting up here when <Link href="/docs/install">Install and configure</Link> or a
        guide names one, and before you deploy (<Link href="/docs/self-host">Self-hosting</Link>).
        The defaults are offline-first: no egress, the <code>echo</code> provider, five
        dependency-free detectors, and detector packs in observe.
      </p>

      <h2 id="sources">How a setting is resolved</h2>
      <ol>
        <li>
          <code>AGENTFOX_&lt;KEY&gt;</code> in the environment.
        </li>
        <li>
          <code>NOMETRIA_&lt;KEY&gt;</code>, the pre-rename name, still read so existing
          deployments keep working. Where both are set, <code>AGENTFOX_</code> wins.
        </li>
        <li>
          The <code>[agentfox]</code> table of the file named by <code>AGENTFOX_CONFIG</code>,
          or of <code>./agentfox.toml</code> in the working directory. A file with an old{" "}
          <code>[nometria]</code> table is still read, with a warning.
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
      <Code>{`export NOMETRIA_FAIL_MODE=closed
export AGENTFOX_ENABLED_DETECTORS='["pii.native","secrets.native"]'
python -c "from agentfox.core.config import Settings as S; s = S(); print(s.fail_mode, s.enabled_detectors)"`}</Code>
      <Output>{`closed ['pii.native', 'secrets.native']`}</Output>
      <Callout kind="note" title="Defaults that depend on where you are">
        <code>&lt;state dir&gt;</code> below is <code>AGENTFOX_STATE_DIR</code> if set, the
        repository root in a source checkout, and otherwise{" "}
        <code>$XDG_DATA_HOME/agentfox</code> or <code>~/.agentfox</code>. See{" "}
        <Link href="/docs/install#state">where state lives</Link>.
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
          <a href="#outside">Read outside Settings</a> · <a href="#dashboard">Dashboard</a>
        </p>
      </nav>

      {GROUPS.map((group) => (
        <section key={group.id}>
          <h2 id={group.id}>{group.title}</h2>
          <table>
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
          </table>
        </section>
      ))}

      <h2 id="outside">Read outside Settings</h2>
      <p>
        A few variables are read straight from the environment, because they decide where
        settings come from or are used by a separate program. None of them can go in{" "}
        <code>agentfox.toml</code>.
      </p>
      <table>
        <thead>
          <tr>
            <th>Variable</th>
            <th>Also read</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          {OUTSIDE.map((v) => (
            <tr key={v.name}>
              <td>
                <code>{v.name}</code>
              </td>
              <td>{v.legacy}</td>
              <td>{v.what}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 id="dashboard">Dashboard</h2>
      <p>
        The web app is a separate Next.js process with its own variables. Each{" "}
        <code>AGENTFOX_</code> name below falls back to its <code>NOMETRIA_</code> spelling
        (for example <code>NOMETRIA_API_URL</code>) when unset. They are read at request time,
        so one image can point at any gateway.
      </p>
      <table>
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
      </table>

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
          { href: "/docs/install", label: "Install and configure", why: "state, extras and agentfox.toml in practice" },
          { href: "/docs/self-host", label: "Self-hosting", why: "the settings a server must change" },
          { href: "/docs/concepts#provenance", label: "Provenance", why: "what taint_scope trades" },
        ]}
      />
    </article>
  );
}

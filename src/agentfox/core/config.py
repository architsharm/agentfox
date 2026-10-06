"""Runtime configuration.

Defaults are deliberately offline-first (X-3 / NFR-9): no API key, no downloaded
weights, no network egress. Every upgrade to a hosted model or a wrapped OSS
classifier is configuration, never a rewrite.
"""

from __future__ import annotations

import logging
import os
import threading
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import PrivateAttr, field_validator
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Env var naming where this installation keeps the things it writes. Like
#: CONFIG_ENV_VAR, deliberately not a Settings field: it decides the default of
#: other fields, which are evaluated when this class is defined.
STATE_ENV_VAR = "AGENTFOX_STATE_DIR"


def _running_from_a_source_checkout() -> bool:
    """Is `REPO_ROOT` the repository, or a directory inside somebody's venv?

    `parents[2]` of `src/agentfox/core/config.py` is the repository root — and
    `parents[2]` of `<venv>/lib/python3.12/site-packages/agentfox/core/config.py` is
    `<venv>/lib/python3.12`. The expression is the same; what it names is not.
    """
    return (REPO_ROOT / "pyproject.toml").is_file() and (REPO_ROOT / "src" / "agentfox").is_dir()


def state_root() -> Path:
    """Where this installation writes its database and its evidence packages.

    In the repository, that is the repository — `agentfox.db` and `var/evidence/`
    where every contributor and every script already expects them.

    Installed from PyPI it cannot be, and the old default put both *inside the
    virtualenv's lib directory*: a governance database and signed auditor
    evidence in a tree that `pip install --upgrade`, a rebuilt venv or a stray
    `rm -rf .venv` throws away, with nothing said about it. The read-only side of
    this exact mistake is already commented at `compliance_dir` below — the
    catalog was empty in production because a repo-relative path finds nothing
    once installed. This is the writing side of it, and it fails the other way
    round: not empty, but silently disposable.
    """
    override = os.environ.get(STATE_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    if _running_from_a_source_checkout():
        return REPO_ROOT
    # Not the venv, and not the working directory either: `agentfox findings`
    # must show the same findings from whichever directory it is typed in.
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) / "agentfox" if xdg else Path.home() / ".agentfox").expanduser().resolve()


STATE_ROOT = state_root()

#: Environments where development conveniences (the unverified identity header, the
#: published default secrets below) are acceptable. Everything else — including any
#: name not in this set — is treated as production, because the failure direction
#: matters: a typo in a deployment variable must not silently open the door.
DEV_ENVIRONMENTS = frozenset({"development", "dev", "test", "testing", "local"})

#: The two secrets that ship with a value, so a laptop install works with no setup.
#: Both values are in this public repository, which makes them no secret at all: the
#: service secret authenticates the call that mints an *owner* token for any GitHub
#: identity, and the signing key is what makes the audit chain tamper-evident. A
#: production process refuses to start while either still has its published value
#: (see :func:`insecure_production_secrets`).
DEFAULT_SERVICE_AUTH_SECRET = "dev-insecure-service-secret"
DEFAULT_AUDIT_SIGNING_KEY = "dev-insecure-checkpoint-key"
#: Placeholders our own deploy files have shipped. Refused for the same reason: they
#: are published, so they are as good as the defaults to anyone who reads the repo.
PUBLISHED_SECRET_VALUES = frozenset(
    {
        DEFAULT_SERVICE_AUTH_SECRET,
        DEFAULT_AUDIT_SIGNING_KEY,
        "change-me-before-any-real-deployment",
        "change-me",
        "",
    }
)


class InsecureConfigurationError(RuntimeError):
    """A production deployment is configured with a published secret."""


#: Env var naming an explicit config file. Deliberately *not* a Settings field: it
#: decides where settings come from, so it cannot itself come from that file.
CONFIG_ENV_VAR = "AGENTFOX_CONFIG"
#: The pre-rename spelling of everything below. The product was called Nometria, and
#: its environment variables are set outside this repository: in Vercel, in Render,
#: in whatever a self-hoster already wrote down. Renaming the prefix without reading
#: the old one would take production down at the moment of deploy and give a
#: self-hoster a silent revert to defaults, which for a governance product means
#: quietly running on an empty policy set. So both are read, new wins, and the old
#: one keeps working until it is deliberately retired.
LEGACY_ENV_PREFIX = "NOMETRIA_"
LEGACY_CONFIG_ENV_VAR = "NOMETRIA_CONFIG"
LEGACY_CONFIG_FILENAME = "nometria.toml"
LEGACY_CONFIG_TABLE = "nometria"
#: The file `agentfox init` writes, looked up in the current working directory.
DEFAULT_CONFIG_FILENAME = "agentfox.toml"
#: The only table read from the file. Other tables are left for other tools.
CONFIG_TABLE = "agentfox"
ENV_PREFIX = "AGENTFOX_"

WEBHOOK_SEVERITIES = ("low", "medium", "high", "critical")
#: Readings of `Settings.taint_scope`; see the field for what each one measured.
TAINT_SCOPES = ("session", "argument")


class ConfigFileError(RuntimeError):
    """The config file the operator pointed at explicitly cannot be used."""


def resolve_config_file() -> Path | None:
    """Which config file settings would be read from right now, if any.

    ``NOMETRIA_CONFIG`` wins and must exist — the operator named it, so a typo is an
    error rather than a silent fall-back to defaults. ``NOMETRIA_CONFIG=none`` turns file
    loading off entirely. Otherwise ``./agentfox.toml``
    in the current working directory, only if present.
    """
    explicit = os.environ.get(CONFIG_ENV_VAR) or os.environ.get(LEGACY_CONFIG_ENV_VAR)
    if explicit and explicit.strip().lower() in {"none", "off", "-"}:
        return None  # explicit opt-out: env and defaults only (tests, CI, containers)
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigFileError(
                f"{CONFIG_ENV_VAR}={explicit!r} does not point at a readable file."
            )
        return path.resolve()
    for filename in (DEFAULT_CONFIG_FILENAME, LEGACY_CONFIG_FILENAME):
        candidate = Path.cwd() / filename
        if candidate.is_file():
            return candidate.resolve()
    return None


# The file resolved by the most recent Settings() construction on this thread, handed
# from ``settings_customise_sources`` (a classmethod, no instance yet) to
# ``model_post_init`` so the instance can say where it came from.
_resolved = threading.local()


class Settings(BaseSettings):
    """Source precedence, highest first: init kwargs > ``NOMETRIA_*`` environment
    variables > the ``[agentfox]`` table of the config file (see
    :func:`resolve_config_file`) > the defaults below. ``.env`` files are not read.
    """

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    _config_file: Path | None = PrivateAttr(default=None)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        path = resolve_config_file()
        _resolved.path = path
        # AGENTFOX_* first, then the pre-rename NOMETRIA_* at lower precedence, so a
        # deployment that still sets only the old names keeps working unchanged and
        # one that sets both gets the new name.
        legacy_env = EnvSettingsSource(
            settings_cls,
            env_prefix=LEGACY_ENV_PREFIX,
            case_sensitive=False,
        )
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, legacy_env]
        toml_source = _toml_source(settings_cls, path)
        if toml_source is not None:
            sources.append(toml_source)
        sources.extend([dotenv_settings, file_secret_settings])
        return tuple(sources)

    def model_post_init(self, __context: Any) -> None:
        self._config_file = getattr(_resolved, "path", None)
        _resolved.path = None

    @property
    def config_file(self) -> Path | None:
        """The config file these settings were read from, or ``None``."""
        return self._config_file

    # --- Persistence -----------------------------------------------------
    database_url: str = f"sqlite:///{STATE_ROOT / 'agentfox.db'}"
    sql_echo: bool = False

    # --- Deployment ------------------------------------------------------
    org_id: str = "org_default"
    environment: str = "development"
    # Where this deployment's dashboard is reachable, used to turn a decision id in
    # a blocked response into a link somebody can open.
    #
    # Empty by default and never guessed: the gateway cannot see how it is reached.
    # Behind a load balancer, in a container, or on a private network, the Host
    # header is whatever the proxy chose to send, and a link built from it sends an
    # engineer somewhere that does not exist — which is worse than no link, because
    # they conclude the dashboard is broken rather than unconfigured. So this is a
    # deliberate statement by whoever runs the deployment, and the response simply
    # omits the field until they make it.
    #
    # The gateway makes no request to it and does not check that it resolves.
    console_url: str = ""
    # NFR-4: zero egress by default. Nothing leaves the customer boundary unless
    # this is explicitly turned on.
    allow_egress: bool = False
    # Some features fetch a URL an operator names: the OpenAPI document for the
    # hosted-API scan, a knowledge-base endpoint or a document a source points at
    # (`core.outbound`). Those fetches are not gated by `allow_egress`: like the
    # GitHub connect flow they are requests an operator makes deliberately, and they
    # carry no customer data out. What they must never be is a way to make this
    # server read its own network, so loopback, private, link-local and reserved
    # addresses are refused. A self-hosted deployment whose spec or knowledge base
    # lives on its own network can turn this on; link-local (cloud metadata),
    # multicast and reserved addresses stay refused regardless.
    outbound_allow_private_hosts: bool = False

    # Where semantic judgments are made. "local" keeps every judgment in this
    # process: questions no local detector covers come back UNKNOWN, which the
    # judgment router already treats as "not authorised". "remote" and "auto"
    # may call a hosted judgment model, but only with `allow_egress` on and
    # only through `judgment.JudgmentGateway`, which redacts locally-detected
    # PII first. Default is local, because asking a third party whether a
    # string contains personal data discloses the string.
    judgment_backend: str = "local"
    # Which evaluators may be consulted, same opt-in shape as
    # `enabled_detectors`. "deterministic" is always present whether listed or
    # not — it needs no key, no weights and no network, and some decisions have
    # no other permitted decider. Adding a tier can only widen coverage: the
    # routing table in judgment/capability.py forbids each tier from deciding
    # the kinds it measured *worse* on, so enabling everything cannot make a
    # control worse than it is today.
    judgment_tiers: list[str] = ["deterministic"]
    # Redact before any judgment leaves, and refuse to send at all if the
    # local redactor cannot load. "We could not check" must mean "we do not
    # send"; see judgment/egress.py.
    judgment_redact_before_egress: bool = True
    judgment_fail_closed: bool = True
    # What happens when a payload bound for a hosted judgment tier contains
    # personal data. "block" refuses to make the judgment remotely at all,
    # "redact" masks what the local detector finds and sends the rest
    # (default), "allow" sends it as-is and logs a warning. Only "block"
    # guarantees a subject's data cannot reach a third party, because
    # redaction can only mask what the local detector found — measured at
    # 17.8% of it on presidio-research.
    judgment_pii_egress: str = "redact"
    # Which registered model provider answers when the `llm` or `local_llm`
    # tier is enabled. Empty uses `default_provider`. The provider interface is
    # the neutral one in providers/base.py, so this works with Azure, Bedrock,
    # Vertex, LiteLLM or a self-hosted endpoint without any of them being
    # special-cased. A LiteLLM/vLLM endpoint on loopback counts as `local_llm`
    # and does not egress; anything else counts as `llm` and is gated.
    judgment_llm_provider: str = ""
    # Which model that provider should judge with. Empty hands the choice to
    # the provider's own default — note that `CompletionRequest.model` defaults
    # to the literal string "default", which the hosted adapters pass straight
    # through and which is not a model name anywhere, so this sends "" instead
    # when unset rather than letting that reach the API.
    judgment_llm_model: str = ""

    # --- Enforcement (Pillar 3) -----------------------------------------
    # NFR-1: hard budget for the whole pre-flight pipeline, and per detector.
    # Was 100 — raised after benchmarking `injection.classifier`/`injection.similarity`
    # under real dataset load found this *pipeline*-level cap silently overriding
    # each detector's own, higher `timeout_ms`: `allowance = min(own_timeout_ms,
    # remaining_ms)` in pipeline.py means a detector's declared budget is a lie if
    # the shared pipeline ceiling is lower than it. Measured real-world cost for
    # the two model-backed detectors together: ~24ms typical, up to ~133ms on the
    # longest real documents in `deepset/prompt-injections` — 100ms was clipping
    # even ordinary-length inputs into silent, undisclosed degradation. Raised
    # again to 300ms after `injection.classifier` grew an ensemble secondary-
    # model backstop (a second sequential forward pass on the common "primary
    # found nothing" path) — measured up to ~153ms end-to-end alongside
    # similarity under load; 300ms keeps real margin over that while staying
    # under `request_budget_ms` below (also raised to preserve the invariant
    # that one surface's budget can't exceed the whole request's).
    enforcement_budget_ms: int = 300
    detector_timeout_ms: int = 40
    # P3-13: the *request*-level ceiling across every surface a single governed call
    # touches. The per-call budget alone is a comfortable lie — one completion
    # evaluates several messages, the output and every tool call. Raised alongside
    # `enforcement_budget_ms` so a single surface's budget can never exceed the
    # whole request's.
    request_budget_ms: int = 350
    # R3: observe-by-default. Enforcement is something a customer turns on
    # deliberately, after simulating it (P2-7).
    default_policy_mode: str = "observe"  # observe | enforce
    # P3-7: what happens when a detector errors or blows its budget.
    fail_mode: str = "open"  # open | closed
    #: P3-4: what a tool call's provenance is, for the taint rules
    #: (`taint.irreversible_tool` and friends). The one setting that decides it.
    #:
    #: ``session``  — the worst provenance anywhere in the run so far *or* in the
    #:   call's own arguments. Once untrusted content has entered the run, every
    #:   later irreversible call carries it, including one with no arguments.
    #: ``argument`` — only the provenance inferred or declared for this call's own
    #:   arguments. A value copied from a web page still taints the call it lands in;
    #:   a call whose arguments the user typed does not inherit the page.
    #:
    #: Measured on an AgentDojo replay with provenance inferred from executed tool
    #: outputs (the `inferred_provenance_summary.json` replay, not yet a published
    #: claim): session contained 588/588 attacks and let 24/97 benign tasks through
    #: (43/97 with read tools granted any provenance); argument let 37/97 through
    #: (62/97 tiered) and contained 527/588. Which trade to make is a product
    #: decision, so the default is the one every published number was measured under.
    taint_scope: str = "session"  # session | argument

    # --- Public playground demo -------------------------------------------
    # An extra CORS origin for the public, unauthenticated playground page
    # (`gateway/routes/playground.py`) when the dashboard and gateway are not
    # same-origin in the deployed environment. Additive to the hardcoded
    # localhost origins in `gateway/app.py`, never a replacement for them.
    #
    # Comma-separated, because one API can front several hosts: a primary dashboard and
    # a standby on another provider, or a custom domain during a move. While this took a
    # single origin, the standby's playground failed in the browser with "Failed to
    # fetch" while curl against the same API looked perfectly healthy.
    playground_cors_origin: str | None = None

    @property
    def playground_cors_origins(self) -> list[str]:
        """Each configured origin, trimmed, in order, with blanks and duplicates dropped."""
        out: list[str] = []
        for raw in (self.playground_cors_origin or "").split(","):
            origin = raw.strip().rstrip("/")
            if origin and origin not in out:
                out.append(origin)
        return out

    # --- Outbound finding webhooks ----------------------------------------
    # Every newly committed Finding at or above `webhook_min_severity` is POSTed
    # to `webhook_url` (see webhooks.py). Still gated by `allow_egress` above: a
    # configured URL with egress off sends nothing. With `webhook_secret` set,
    # each request carries `X-Nometria-Signature: sha256=<hmac of the raw body>`.
    webhook_url: str | None = None
    webhook_secret: str | None = None
    webhook_timeout_seconds: float = 3.0
    webhook_min_severity: str = "high"  # critical | high | medium | low

    # --- Monitoring connected sources (agentfox.monitoring) --------------------
    # A Slack incoming-webhook URL that receives a short message for every monitor
    # finding opened, reopened or closed at or above `slack_min_severity`. A tenant can
    # also set its own (`PUT /api/alerts/slack`). Like `webhook_url`, gated by
    # `allow_egress`: the message carries finding titles out of the deployment.
    slack_webhook_url: str | None = None
    slack_min_severity: str = "medium"  # critical | high | medium | low
    # The secret GitHub signs push deliveries to `/api/integrations/github/webhook`
    # with. A connection may carry its own instead (`POST
    # /api/integrations/github/webhook-secret`); with neither, the route refuses.
    github_webhook_secret: str | None = None
    # How many due monitors one `monitors.run` job runs. Each one downloads and scans
    # a repository or fetches a document, so this bounds a single serverless call.
    monitor_batch_limit: int = 5
    # After this many failed runs in a row a monitor raises a `monitor_failing`
    # finding (closed by the next successful run).
    monitor_failure_threshold: int = 3

    # --- Detector cut-offs that used to be hard-coded -------------------------
    #: A cut-off nothing can change without a code edit is a cut-off the improvement loop
    #: cannot tune and an operator cannot adjust. Read once when detectors register, like
    #: every other setting, so a change needs a restart.
    #: Cosine similarity to the nearest known attack before `injection.similarity` fires.
    embedding_similarity_attack_threshold: float = 0.6
    #: How far above the nearest benign anchor that similarity must sit.
    embedding_similarity_benign_margin: float = 0.05
    #: The backstop classifier's bar. 0.92 is llm-guard's own default for this exact model,
    #: chosen there because it over-triggers at lower bars (see adapters/classifiers.py).
    prompt_injection_classifier_secondary_threshold: float = 0.92

    # --- Improvement loop (governed self-improvement, Phase 0) -----------------
    #: Identity every automated change is recorded under on the audit chain.
    improvement_actor_id: str = "agentfox-improver"
    #: Kill switch for the improver. While true, no automated change is applied at any
    #: autonomy level; proposals are still filed so nothing is lost.
    improvement_frozen: bool = False
    #: Rate limit on automated applies per tenant per day, so a faulty class of change
    #: cannot apply dozens of edits before anyone looks.
    improvement_max_auto_changes_per_day: int = 20
    #: A change class whose rollback rate exceeds this drops an autonomy level.
    improvement_rollback_budget: float = 0.05
    #: Two-way canary gate defaults.
    canary_min_dwell_seconds: int = 3600
    canary_max_block_rate_drop: float = 0.15
    #: Recurring work. The cron drains the queue; schedules fill it.
    scheduler_enabled: bool = True
    #: A job `running` for longer than this is treated as crashed and recovered.
    job_stuck_after_seconds: int = 900
    #: Base for exponential backoff between attempts.
    job_backoff_base_seconds: int = 60

    # --- Live red-team probes and the public showcase ------------------------
    #: Kill switch for scheduled probes against deployed agents
    #: (`evaluation.live_probes`). Each target also needs its own recorded opt-in;
    #: this turns every target off at once without touching those records.
    live_probes_enabled: bool = True
    #: Run AgentFox against its own demo agent in a dedicated tenant and publish the
    #: results at `GET /api/public/showcase` (`evaluation.showcase`). Off by default:
    #: only the hosted deployment that backs the marketing site's /live page runs it.
    showcase_enabled: bool = False
    #: The tenant the showcase lives in. Nothing outside it is ever read by the
    #: public endpoint.
    showcase_org_id: str = "org_showcase"

    @field_validator("taint_scope")
    @classmethod
    def _check_taint_scope(cls, value: str) -> str:
        # A typo here must not quietly fall back to either reading: they contain
        # different attacks, and the operator chose one on purpose.
        value = value.strip().lower()
        if value not in TAINT_SCOPES:
            raise ValueError(f"must be one of {', '.join(TAINT_SCOPES)}")
        return value

    @field_validator("webhook_min_severity", "slack_min_severity")
    @classmethod
    def _check_webhook_min_severity(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in WEBHOOK_SEVERITIES:
            raise ValueError(f"must be one of {', '.join(WEBHOOK_SEVERITIES)}")
        return value

    # --- Cost & reliability (P15) ----------------------------------------
    # Degradation ladder, preferred-first. Empty means no fallback: fail rather than
    # silently serve from a model the agent was never evaluated against.
    fallback_chain: list[str] = []
    breaker_failure_threshold: int = 5
    breaker_recovery_seconds: float = 30.0
    # P15-6: admission control on the inline surface — shed work before it reaches
    # governance, never after (availability.py's `AdmissionController`). Defaults
    # generous enough that no self-host demo ever notices them; sizing these to a
    # deployment's real capacity is the operator's job, the same as the breaker
    # thresholds above.
    admission_rate_per_second: float = 200.0
    admission_burst: int = 400
    admission_max_concurrent: int = 256
    admission_shed_below_priority: str = "normal"
    # Gap 0.7: how long a service-availability probe's answer is reused before the
    # dependency is re-checked (availability.py's `probe_services`). This exists
    # because the probes are not free — the database probe opens a connection beyond
    # the request's own session, and with `policy_engine = "opa"` the policy probe is
    # an HTTP call to the sidecar. Paying either per request would make the module
    # that exists to prevent a latency problem into one. The status endpoints ignore
    # this and always probe fresh: an operator asking "is it up *now*" must not be
    # told what was true five seconds ago.
    service_probe_interval_seconds: float = 5.0

    # --- Streaming (PL-1) ------------------------------------------------
    # `buffered` enforces output identically to the non-streaming path at the cost of
    # first-token latency. `windowed` preserves latency but cannot recall content it
    # has already forwarded. Buffered is the default deliberately.
    streaming_mode: str = "buffered"  # buffered | windowed
    stream_window_chars: int = 200

    # --- Detectors -------------------------------------------------------
    enabled_detectors: list[str] = [
        "injection.heuristic",
        "pii.native",
        "secrets.native",
        "safety.lexicon",
        "schema.json",
    ]
    # Appendix A.4: restricted-licence model adapters refuse to load without this.
    accept_restricted_model_licenses: bool = False
    granite_guardian_model: str = "ibm-granite/granite-guardian-3.0-2b"
    # MIT, ~86M params, no licence gate — but a real CPU forward pass still
    # costs tens of ms per call versus a regex scan's fractions of one, and every
    # concurrent request pays it independently (P3-6's budget is per-request, not a
    # shared inference queue). Opt-in via `enabled_detectors`, same reasoning as
    # Granite Guardian: a customer must choose the latency/recall trade-off, not
    # inherit it from a default. leolee99/PIGuard, not the more commonly cited
    # protectai/deberta model — see PromptInjectionClassifierDetector's docstring
    # for the benchmarked reason (better recall AND far fewer false positives).
    prompt_injection_classifier_model: str = "leolee99/PIGuard"
    # MIT, ~86M params. High-bar ensemble backstop for the primary classifier
    # above — see PromptInjectionClassifierDetector's docstring for why a second
    # model, and why this specific one (it's the model this project moved away
    # from as primary, precisely because of its over-triggering; used here only
    # above `secondary_threshold`, only when the primary found nothing). Set to
    # "" / None to disable and run PIGuard alone.
    prompt_injection_classifier_secondary_model: str | None = (
        "protectai/deberta-v3-base-prompt-injection-v2"
    )
    # Apache-2.0, ~22M params — embeds text locally for cosine-similarity matching
    # against `guardrails/data/injection_corpus.json`. Same opt-in reasoning as the
    # classifier above; unlike the classifier, this one improves by editing that
    # corpus file, no retraining required.
    embedding_similarity_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Wrapped rail orchestrators (P3-1) -------------------------------
    # Both adapters were registered with their configuration hard-coded empty —
    # `NemoRailsDetector()` with no config path, `GuardrailsAiDetector()` with no
    # validators — and `available()` returns False when those are empty. There
    # was no setting anywhere to fill them, so installing `agentfox[rails]` or
    # `agentfox[validators]` changed nothing and the two detectors were
    # unreachable by construction. These are how they are turned on.
    #
    # A directory holding a NeMo Guardrails config (`config.yml` plus any Colang
    # files). Empty by default: NeMo's rails are programs, and which programs to
    # run is a deployment's decision, not a default.
    nemo_rails_config_path: str | None = None
    # Guardrails AI Hub validator slugs, e.g. ["valid_json", "detect_pii"]. Each
    # must already be installed (`pip install guardrails-ai-<slug-with-dashes>`)
    # because Hub validators carry licences independent of the Apache-2.0 core
    # (Appendix A.1), so none is ever enabled by inheritance.
    #
    # Prefer the per-validator `rails.hub.*` detectors: they report one entity
    # type per check, so existing policy rules match them and precision is
    # measured per validator. This composite reports everything as
    # SCHEMA.VIOLATION. It exists for the case those do not cover — several
    # validators evaluated as one Guard, which is what Guardrails AI's own
    # `use_many` composition is for.
    guardrails_ai_validators: list[str] = []

    # --- Entitlement (P10) -----------------------------------------------
    # native | openfga. The seam exists because no winner does: customers running
    # OpenFGA or Cedar keep them, and the much larger group who express permissions as
    # "this group can read this folder" get a control they can actually switch on.
    entitlement_engine: str = "native"
    openfga_url: str | None = None
    openfga_store_id: str | None = None
    k_anonymity_threshold: int = 5

    # --- Authentication --------------------------------------------------
    # auto | development | token | oidc
    #
    # `auto` follows `environment`: the unverified identity header is accepted in
    # development and refused everywhere else, including in any environment name we do
    # not recognise. A typo in a deployment variable must not silently open the door.
    auth_mode: str = "auto"

    # --- GitHub connect flow (dashboard "Sign in with GitHub" + repo scan) -----
    # The dashboard's OAuth callback runs the one privileged "find-or-create user and
    # mint a token" call before any user token exists — it authenticates with this
    # shared secret instead. Must match the dashboard's own copy of the same value.
    service_auth_secret: str = DEFAULT_SERVICE_AUTH_SECRET
    # Fernet key encrypting stored GitHub access tokens at rest. `None` means "not
    # configured" — connecting a repo fails closed rather than storing a raw token.
    token_encryption_key: str | None = None

    # --- Deferred job queue (PL-5) ----------------------------------------
    # POST /api/internal/jobs/run is the cron backstop for a job stuck in
    # "running" because the request that started it crashed or hit a platform
    # timeout mid-attempt. `None` means unset, and the route refuses every
    # call rather than defaulting to an insecure shared value the way
    # service_auth_secret does — this endpoint can run arbitrary tenants'
    # queued work, a materially different blast radius than the GitHub
    # provisioning call that secret guards. Vercel's own cron integration sets
    # this from the project's CRON_SECRET env var and sends it as
    # `Authorization: Bearer <value>` automatically once that env var exists.
    cron_secret: str | None = None

    # --- Action assurance (P9) -------------------------------------------
    # The dialect artefacts are parsed against. Wrong dialect means wrong parse, and
    # a wrong parse fails closed rather than passing through.
    sql_dialect: str = "postgres"
    # P9-7: how fresh a state read must be to authorise an irreversible act.
    verified_state_max_age_seconds: int = 300
    # P18 — "standard" escalates an undeclared table (a human should look);
    # "strict" blocks it outright. See data_access.analyse_access's own docstring.
    data_access_strictness: str = "standard"

    # --- Agent loop governance (PL-4) -------------------------------------
    # Mirrors agent_loop.LoopBudget's own defaults — kept here, not just as
    # dataclass defaults, so a deployment can tune them without a code change.
    loop_max_steps: int = 25
    loop_max_repeats: int = 2
    loop_max_cycle_length: int = 4
    loop_max_steps_without_progress: int = 5

    # --- Memory write governance (P14, NOM-RTG-13) -----------------------
    # How long an unverified memory entry survives before it decays — the
    # default-closed counterpart to Suppression's default-open `expires_at`.
    memory_unverified_ttl_seconds: int = 86_400

    # --- Inter-agent message security (P17, NOM-IAM-08) -------------------
    # A signature/nonce older than this is rejected even if it verifies.
    agent_message_validity_seconds: int = 300

    # --- Policy engine (Pillar 6) ---------------------------------------
    policy_engine: str = "native"  # native | opa
    opa_url: str = "http://localhost:8181"

    # --- Providers (X-2) -------------------------------------------------
    # `echo` is the offline provider: deterministic, no network, no key. It is what
    # makes the whole system demonstrable with `docker compose up` and nothing else.
    default_provider: str = "echo"
    openai_base_url: str = "https://api.openai.com"
    anthropic_base_url: str = "https://api.anthropic.com"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # I-11: the providers enterprises actually deploy on. 6 of 11 engineers run Azure
    # OpenAI, 4 Bedrock, 3 Vertex — a governance product that only speaks to
    # api.openai.com is unusable at exactly the companies that need governance.
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str | None = None
    aws_region: str | None = None
    bedrock_model: str = "anthropic.claude-sonnet-4-20250514-v1:0"
    vertex_project: str | None = None
    vertex_location: str = "us-central1"
    vertex_model: str = "gemini-2.0-flash"
    # I-10: govern through the routing layer teams already run, rather than compete.
    litellm_base_url: str | None = None
    litellm_api_key: str | None = None

    # --- Observability correlation (I-4 / I-6) ---------------------------
    # Correlation itself needs none of these: the join key travels in-band on a
    # traceparent or vendor header, so a team gets the link with zero configuration.
    # These only govern the optional write-back of our verdict onto their run.
    correlation_push: bool = False
    correlation_timeout_seconds: float = 2.0
    langsmith_api_url: str = "https://api.smith.langchain.com"
    langsmith_ui_url: str = "https://smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_project: str | None = None

    # --- Evaluation (Pillar 4) ------------------------------------------
    eval_runner: str = "native"  # native | promptfoo
    promptfoo_bin: str = "promptfoo"
    online_eval_sample_rate: float = 0.25
    drift_psi_threshold: float = 0.2

    # --- Audit (Pillar 5) ------------------------------------------------
    audit_signing_key: str = DEFAULT_AUDIT_SIGNING_KEY
    audit_checkpoint_interval: int = 100
    # P5-5 / R8: the audit log must not become a new PII liability.
    redact_at_capture: bool = True
    evidence_dir: Path = STATE_ROOT / "var" / "evidence"

    # --- Content paths -----------------------------------------------------
    # Packaged *inside* agentfox/ (not at the repo root) so `packages =
    # ["src/agentfox"]` in pyproject.toml bundles them into the wheel automatically —
    # a repo-root-relative path resolves fine from a source checkout but silently
    # finds nothing once installed (e.g. the Vercel deployment installs from the
    # vendored wheel, not the source tree), which is why the control catalog and
    # baseline policy pack were empty in production despite syncing without error.
    compliance_dir: Path = Path(__file__).resolve().parents[1] / "compliance_data"
    policies_dir: Path = Path(__file__).resolve().parents[1] / "policies_data"

    @property
    def restricted_models_allowed(self) -> bool:
        return self.accept_restricted_model_licenses


def _toml_source(
    settings_cls: type[BaseSettings], path: Path | None
) -> PydanticBaseSettingsSource | None:
    """The ``[agentfox]`` table of ``path`` as a settings source, or ``None``.

    Values go through the same field validation as every other source, so
    ``enabled_detectors = ["pii.native"]`` and ``allow_egress = false`` land as a
    list and a bool. Unknown keys are ignored (``extra="ignore"``) but named in a
    warning, since a misspelled key otherwise looks exactly like a setting that
    silently didn't apply.
    """
    if path is None:
        return None
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigFileError(f"{path} is not valid TOML: {exc}") from exc
    # A file written before the rename says [nometria]. Reading only [agentfox] would
    # find nothing there and fall through to defaults without an error, which is the
    # worst outcome: a governance product quietly running unconfigured.
    header = CONFIG_TABLE if CONFIG_TABLE in data else LEGACY_CONFIG_TABLE
    table = data.get(header)
    if table is None:
        log.warning("%s has no [%s] table; nothing read from it", path, CONFIG_TABLE)
        return None
    if not isinstance(table, dict):
        raise ConfigFileError(f"{path}: `{header}` must be a table")
    if header == LEGACY_CONFIG_TABLE:
        log.warning(
            "%s uses the old [%s] table; rename it to [%s]", path, LEGACY_CONFIG_TABLE, CONFIG_TABLE
        )
    unknown = sorted(set(table) - set(settings_cls.model_fields))
    if unknown:
        log.warning("%s: ignoring unknown [%s] key(s): %s", path, header, ", ".join(unknown))
    return TomlConfigSettingsSource(settings_cls, toml_file=path, toml_table_header=(header,))


def env(name: str, default: str | None = None) -> str | None:
    """One environment variable read outside `Settings`, with the legacy fallback.

    For the handful of switches that are read straight from the environment
    (a log level, the agent name `auto()` guesses) rather than through `Settings`.
    ``AGENTFOX_<name>`` wins; ``NOMETRIA_<name>`` keeps working, for the same reason
    `LEGACY_ENV_PREFIX` exists. An empty value counts as unset.
    """
    return os.environ.get(ENV_PREFIX + name) or os.environ.get(LEGACY_ENV_PREFIX + name) or default


def is_development(settings: Settings | None = None) -> bool:
    """Whether ``environment`` names a development environment (see DEV_ENVIRONMENTS)."""
    settings = settings or get_settings()
    return (settings.environment or "").lower() in DEV_ENVIRONMENTS


def insecure_production_secrets(settings: Settings | None = None) -> list[str]:
    """The published secrets this deployment is running with, outside development.

    Empty in development, where the defaults are the convenience they exist to be.
    Anywhere else each entry names the variable to set and why it matters.
    """
    settings = settings or get_settings()
    if is_development(settings):
        return []
    problems: list[str] = []
    if settings.service_auth_secret in PUBLISHED_SECRET_VALUES:
        problems.append(
            "AGENTFOX_SERVICE_AUTH_SECRET is unset or still a published value — anyone "
            "could call /api/auth/github/provision and mint an owner token. Set it to a "
            "random value (e.g. `openssl rand -hex 32`) and give the dashboard the same one."
        )
    if settings.audit_signing_key in PUBLISHED_SECRET_VALUES:
        problems.append(
            "AGENTFOX_AUDIT_SIGNING_KEY is unset or still a published value — anyone could "
            "forge audit checkpoints. Set it to a random value you keep outside the database."
        )
    return problems


def assert_production_secrets(settings: Settings | None = None) -> None:
    """Refuse to serve a non-development environment that runs on published secrets."""
    settings = settings or get_settings()
    problems = insecure_production_secrets(settings)
    if problems:
        raise InsecureConfigurationError(
            f"refusing to start in environment '{settings.environment}':\n  - "
            + "\n  - ".join(problems)
            + "\n(Set AGENTFOX_ENVIRONMENT=development only for a local, unexposed install.)"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def loaded_config_file() -> Path | None:
    """The config file the active (cached) settings were read from, if any."""
    return get_settings().config_file


def reset_settings_cache() -> None:
    """Test hook — settings are cached for the process lifetime otherwise."""
    get_settings.cache_clear()

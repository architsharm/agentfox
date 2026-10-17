# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Published benchmark numbers do not live here. They live in the result files under
`benchmarks/`, and `scripts/claims.py --check` binds every number quoted in a document to
the file it came from.

## [Unreleased]

### Fixed

- **Dashboard actions no longer land on `localhost`.** Add project, Add all and every
  other form action, and the sign-in and `/app/agents` redirects, came back on the
  server's own hostname. Opened at `127.0.0.1` or behind a proxy, that is another origin
  without the session cookie, so the action looked like a sign-out. They now return to
  the host the browser used.
- **`agentfox up`, found by running it end to end** on a sample project, locally, against
  a production-mode team server, through the Cloud path and as a Docker Compose stack:
  - A set-up agent works on its first call. The tools `up` declares are granted to the
    agent (locally and over the API), and a coding agent is offered a grant for the MCP
    servers it loads (the repository's and its user-level config's), so neither is
    refused by default-deny. Containment still applies: a refund whose recipient came
    from a tool result is still held.
  - A self-hosted stack started by `up` gets the control catalog and the shipped policy
    packs; the gateway image only serves, so before this it ran with no tool containment.
  - Before starting Docker, `up` names a port already in use and says the gateway image
    is a large download (its size read from the registry), asking first; a failed start says how to clean up.
  - `up` only reports a local API it started; another AgentFox on :8080 (a self-hosted
    stack, another project) is named, not claimed.
  - Running `up` again no longer records the same scan, and its draft agents and proposed
    policies, a second time.
  - A connected self-hosted server is asked for its dashboard address; the API URL is no
    longer shown as the dashboard.
  - "Watch first" says what still stops a call (destructive commands, protected paths,
    tampering); logs and pid files are git-ignored; plurals and long paths read properly.

### Added

- **`unicode.tags`, a default detector for text hidden in Unicode tag characters**
  (U+E0000 to U+E007F, "ASCII smuggling"): invisible to a person, read by a model. It
  reports `INJECTION.HIDDEN_TAG_TEXT`, so the baseline injection rules act on it, and
  skips the England, Scotland and Wales flag emoji, the block's one legitimate use (#15).
- **A Fly.io guide for the control-plane UI**, `deploy/FLY.md` (#11).
  `fly.dashboard.toml` now sets `HOSTNAME=0.0.0.0`, as `render.yaml` does.
- **A scanned multi-agent system comes out as its agents.** The repository scan reads
  each agent the code defines, the tools it is handed and which agent hands work to
  which (OpenAI Agents SDK handoffs and `as_tool`, LangGraph supervisors, swarms and
  `StateGraph` agent nodes, CrewAI crews and delegation, AutoGen teams and group chats,
  Google ADK `sub_agents`), statically. `scan --json` gains `agents` and `agent_edges`.
  A repository with two or more agents is proposed as one draft per agent with its own
  tools, joined by declared delegation edges, so the guardrail map shows sub-agents
  ("From code, no calls yet") and the agent that calls each one, and "apply to
  sub-agents" reaches them, before any traffic. The Proposed list groups a system under
  its orchestrator with an "Add all" action. A re-scan updates the drafts in place and
  never turns an agent someone added back into a proposal.
- **`agentfox up`, the guided setup.** One command from a fresh install to a governed
  project: it scans the repository, asks where AgentFox runs (this machine; self-hosted,
  either started here with Docker Compose and a first operator, or an existing server;
  or AgentFox Cloud with an API key), what to cover and how strict to start, then sets up
  the Claude Code and Codex hooks, `agentfox.auto()` in your entry point, the gateway
  environment for any language, the tools it found (impact inferred, never overwriting
  a declaration), your MCP servers, the scan in the dashboard, Enterprise monitoring and
  compliance where available, and the dashboard. It starts in observe by default. Each
  question has a recommended answer (`--yes` takes them all); answers are saved in
  `.agentfox/up.json` and credentials in `.agentfox/agentfox.env` (0600, git-ignored).
  `up` takes `demo`'s place in the Start panel; `agentfox demo` still works.
  Its scan step also reads the AI tools set up on this machine (`agentfox scan
  machine`, skipped with `--skip-machine`) and the repository's own skills, and a
  coding agent configured only at user level is offered too. It can add the AgentFox
  GitHub Action as `.github/workflows/agentfox.yml`, never over an existing one.
- `exposure.declared_mcp_servers()`: the servers a repository's MCP configs declare,
  once each by name, shared by `agentfox scan mcp` and `agentfox up`.

- **Delivery policies for coding agents** (`capabilities/delivery`). The hook now
  also catches an agent that is about to lose work it already got right: a service
  the task needs left attached to the session (including a harness background task),
  a damaged database opened before it was copied with its sidecars, deployed state
  torn down after a successful check, a closed replacement map with no diff check
  after the last write, one answer where every answer was asked for, and a stated
  numeric bar never measured. Each policy reads the task text once and intervenes at
  most once or twice per session. On by default; `AGENTFOX_DELIVERY=off` disables
  them, and `AGENTFOX_DELIVERY=only` runs them without the daemon.
- The Claude Code adapter binds **Stop**, probed live at 2.1.292: a refusal keeps
  the agent working with the reason as its next instruction. Existing installs get
  it by rerunning `agentfox admin hooks install --write`.
- **`messages` (and `trust`) on `/v1/guard/tool_call`.** The conversation that led to the
  call; an undeclared argument's provenance is inferred from it. Without it, or a
  declared `provenance`, nothing is inferred (now documented). The TypeScript SDK's
  `guardToolCall` options take `messages` and `trust`.
- **Built-in validators.** About seventy checks ported from the Guardrails AI validators
  (Apache-2.0) as native code, so none needs a separate install: system-prompt leaks,
  forbidden SQL and unknown columns, unsafe HTML, internal domains, fuzzy word lists,
  drug names, price quotes, format checks, local-model classifiers (jailbreak,
  toxicity, NSFW, bias, gibberish) and LLM judges routed through the judgment tier.
  Pick one under Policies → Add rule → **Use a built-in check**, give it its settings,
  and try it on a sample; it is watched and enforced like any other rule. Ones that
  need no settings can also be switched on as `validator.*` checks.
- Your own validators register through the `agentfox.validators` entry point.
- Importing a Guardrails AI guard maps each validator onto its port with the same
  settings, so `ValidLength`, `RegexMatch` and the rest import instead of being skipped.

### Changed

- **Open core and AgentFox Enterprise.** The repository is now an Apache-2.0 open core
  plus a source-available enterprise package in `ee/` (Business Source License 1.1: free
  in production for one workspace with up to four agents; each release becomes
  Apache-2.0 three years after it ships). Enterprise holds compliance status, reviews
  and sign-off, the risk register and board view, auditor evidence packages, fleet
  monitoring with Slack alerts, and external access checks. Everything else, including
  enforcement, containment, every detector and validator, custom rules, packs, data
  retention and legal holds, stays in the open core, which runs on its own.
- The open core finds the enterprise package through the `agentfox.extensions` entry
  point and never imports it; an import contract enforces that. CI runs the open core's
  suite without `ee/` and both suites with it.
- The dashboard shows enterprise areas only where the deployment has them
  (`/api/version` now reports `edition` and `features`). Retention moved to
  Settings → Retention; the Reports summary reads the new open-core `/api/overview`.
- The `rails.hub.*` detectors, which needed a `pip install` per validator, are replaced
  by the ports. `rails.guardrails_ai` stays for running your own Guard.

### Fixed

- Opening Compliance on a new workspace could fail: its parallel requests each loaded the
  control catalog and collided on the same control.
- An extension's CLI commands could be dropped depending on import order.
- **The gateway proxy now governs the tool calls a model asks for.** `/v1/chat/completions`
  and `/v1/messages` authorise every tool call in the response through
  `guard_tool_call` before returning it, as `agentfox.auto()` does in-process: a
  refused call is a 403, a held one a 428, and a stream holds tool-call fragments until
  they are authorised. Before, only the reply's text was checked.
- **Anthropic `tool_result` blocks are tool output, not user input.** They arrive inside a
  `role: "user"` message, and the gateway tainted them `user`, so a payee copied out of a
  tool result passed a grant that allows user content. They are now `tool_result`, named
  after the tool that produced them (`tool:<tool>#<i>`) on both shapes, so composition
  checks and `output_trust` declarations apply on the gateway as on the SDK.
- **`/v1/messages` returns tool calls.** A non-streamed reply now carries `tool_use`
  blocks and `stop_reason: "tool_use"`; it used to drop them.
- Value checks could not be saved from the dashboard ("a condition rule needs
  `condition`"), and trying one on a tool call ignored the tool: the dashboard's proxy
  dropped both fields. Suggested argument names for a value check now load too.

## [0.4.0] - 2026-10-12

### Added

- **New tool-call paths.** Every agent's tool-call sequences in production, the ones
  never seen before, and one click to add a path to the regression tests; a daily scan
  raises a `new_tool_path` issue whose fix adds the path (Test → Tool paths).
- **Agent circuit breaker.** An agent whose calls start getting blocked in a burst is
  flagged (default) or paused for a cool-down, then probed and closed after clean
  calls; Resume now from the agent's settings or the issue.
- **Your own access control.** A workspace registers its RBAC service (or an OPA or
  Cedar server); matching tool calls are posted to it with the end user before they
  run (`principal` on `/v1/guard/tool_call`, `fox.session(principal=...)`).
- **`govern(fox, *agents)`** for the OpenAI Agents SDK: one call guards every agent,
  hand-off and tool.
- Playground sandboxes come from a spare pool (about 2.5 s to start), and due jobs run
  off ordinary traffic as well as the daily cron.
- Policy import from agent-governance YAML, Codex CLI hooks, industry and regional
  packs, Rego and Cedar libraries, a coding-agent blocklist.

- **Key rotation** for the two keys that protect stored data.
  `AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS` and `AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS`
  (comma-separated) hold retired keys: secrets still decrypt and checkpoints still
  verify under them, while everything new uses the current key. `agentfox admin keys
  rotate` re-encrypts every encrypted column (atomic per column; a value no key
  decrypts is reported and left alone), verifies each tenant's audit chain, re-signs
  its previous-key checkpoints, records an `audit.key_rotated` entry with the key
  fingerprints (first 8 hex of SHA-256, never the key) and checkpoints the new head.
  `agentfox admin keys status` shows the fingerprints and what still needs a previous
  key. The job runner (`/api/internal/jobs/run`, `agentfox admin jobs run-due`) enqueues
  a `keys.rotate` job by itself while a previous key still protects something;
  `/api/version` reports `key_rotation` states and `agentfox doctor` has a `key
  rotation` line. See docs/deployment/key-rotation.md.
- Checkpoints record the signing key's fingerprint in `key_id` (was the constant
  `local`), and are written into the chain of the entry they anchor even inside
  `system_scope`. `chain.verify` accepts one key or several.
- The `verify_chain.py` in evidence packages accepts several comma-separated keys in
  `AGENTFOX_AUDIT_KEY`, for a chain that spans a rotation.
- One-time migration bridge: when both `AGENTFOX_<KEY>` and `NOMETRIA_<KEY>` were set
  and differed for `TOKEN_ENCRYPTION_KEY` or `AUDIT_SIGNING_KEY`, the `NOMETRIA_` value
  was used as the previous key. Removed again by rename stage B (below).

- **Capability packs.** A business use case or framework is one directory with a
  `pack.yaml` (id, version, maturity, owners, compliance mappings, vocabulary) and its
  policies, controls, ladder templates, red-team probes, optional checks, golden cases
  and fixtures. Built in: `baseline`, `tool-containment`, `coding-agent`, `eu-ai-act`,
  `compliance/catalog`, `payments/refunds`, `customer-support`. Your own load from
  `.agentfox/packs/` or an `agentfox.packs` entry point; only `stable` packs load unless
  `pack_maturity` (`AGENTFOX_PACK_MATURITY`) says otherwise.
- `agentfox policy packs list|show|test|validate|new`. Bare `agentfox policy packs` still
  prints the policy files on disk (now also `policy packs files`).
- A finding-type registry: `GET /api/findings/types` and `agentfox findings --types` list
  every type with its title, usual severity, meaning and owner; packs declare their own.
- A check registry: request-path checks register with `@check` from the capability
  that owns them, an `agentfox.checks` entry point or a pack.
- `mcp_tool_added_under_wildcard` finding (high): a registered MCP server added a tool
  that an existing wildcard grant already allows.
- `agentfox doctor` has a `legacy names` line listing every pre-rename `NOMETRIA_*`
  variable still set (in use, or set but not read) and any `nometria.toml` / `[nometria]`
  config in use.

### Changed

- **Get started's last step enforces everything that protects the agent** (baseline,
  its own protections, blocked words and topics), with a preview of what it would have
  stopped. Previews now count calls that went through and would be stopped.
- **Fewer, plainer issues.** One medium issue per tool an agent has not been given
  (granting it closes the issue); calls held for the approval their grant asks for
  are not issues; titles and refusal reasons are plain words.
- Loop detection counts within a turn, so a conversation that repeats itself across
  turns is not refused; a stopped loop is a recorded, blocked run.
- Runs are grouped by conversation; the SDK reads `AGENTFOX_API_TOKEN`.
- Reports show controls working out of every control that applies, not out of those
  measured; rates over nothing show a dash.

- **A cascade that only sends a message escalates instead of blocking.** A tool can be
  declared `effect: communication` (`agentfox declare tool --effect communication`, or
  `effect:` in a pack's `world.yaml`): its irreversible effect is a message leaving, not
  data destroyed, money moved or state changed. When every destructive tool a call's
  declared triggers reach is such a tool, `cascade_risk` reports
  `cascade-reaches-notification` (high) and the new `cascade.reaches_notification` rule
  in `tool-containment` holds the call for approval; one reached tool outside that class
  and it is `cascade.reaches_destructive` (block), as before. Never guessed from a tool's
  name: an undeclared tool counts as destructive. The demo world declares `email.send`
  this way, so an ordinary `tickets.update` is held for approval rather than refused.

- **Nometria to AgentFox, environment and headers (stage A).** Everything the product
  writes and documents is now `AGENTFOX_*`, `agentfox.toml` / `[agentfox]` and
  `X-AgentFox-*`: the gateway's response headers (`X-AgentFox-Trace`, `-Verdict`,
  `-Effective-Verdict`, `-Applied-Verdict`, `-Would-Be-Verdict`, `-Decision`, `-Mode`,
  `-Latency-Ms`, `-Explain`, `-Streaming`, `-Degraded`), the finding webhook's
  (`X-AgentFox-Event`, `-Delivery`, `-Timestamp`, `-Signature`: **update a webhook
  receiver that verifies `X-Nometria-Signature`**), the FastAPI middleware's, and what the
  SDK, the CLI and the dashboard send. The pre-rename names still work as input:
  `NOMETRIA_*` variables, `NOMETRIA_CONFIG`, `nometria.toml` and a `[nometria]` table are
  read below the new names, and `x-nometria-*` request headers are accepted, with
  `x-agentfox-*` winning when a request carries both. The process logs one startup
  warning naming each legacy setting in use; the dashboard warns once per legacy
  variable. `render.yaml`, `deploy/`, the docs and the plugins use only the new names.
  The self-host blueprint now prompts for `AGENTFOX_AUDIT_SIGNING_KEY` instead of
  generating it, so a blueprint sync can never rotate an existing deployment's key.
  Renaming the hosted deployment: `docs/deployment/vercel-env-rename.md` (since removed).
- The shipped policies and the control catalog moved from `policies_data/` and
  `compliance_data/` into the capability packs (`packs/<id>/policies/`,
  `packs/compliance/catalog/controls/`). `compliance_dir` and `policies_dir` still
  override them, and are now unset by default. `agentfox policy packs` and
  `agentfox admin catalog validate` print the new paths.
- The dashboard's finding labels come from the registry. `budget_breach` now reads
  "Detector over budget" (it is a detector's latency budget); it read "Budget
  exceeded", which describes `budget_exhausted`.

- The Claude Code operator plugin moved from `harness/` to `plugins/claude-code/`, and its
  runtime-neutral parts (`AGENTS.md`, `skills/`, `reference/`) to `plugins/shared/`. The
  marketplace entry now points at `./plugins/claude-code`; the install command
  (`claude plugin install agentfox@agentfox`) is unchanged. A local clone uses
  `claude --plugin-dir ./plugins/claude-code`. The maintainer command
  `/agentfox:harness-check` is now `/agentfox:plugin-check`, the drift checker is
  `scripts/check_plugins.py`, and the docs page is `/docs/plugin` (`/docs/harness`
  redirects).
- Coding-agent harnesses are adapters behind one interface, `agentfox.harnesses`
  (registered through the `agentfox.harnesses` entry-point group). Claude Code is the only
  one; installed hooks (`agentfox hooks run --harness claude`) behave exactly as before.
- Accepting a changed MCP tool listing is now a two-person change. A changed definition is
  held and filed as an `mcp.tool.accept` change proposal; `McpGovernor.register_tools(...,
  accept_changes=True)` now requires `actor=` (the reviewer) and raises `ValueError`
  without one, and the change applies only when a second, different person approves.
  `POST /api/mcp-servers/{name}/tools` with `accept_changes` counts as the signed-in
  person's approval and needs the role that approves policy proposals. The result carries
  `held`, `accepted`, `awaiting_second_approver` and `proposals`.
- `McpCallBlocked`, raised by the MCP governor, is now an `agentfox.AgentFoxError` like
  every other refusal. It is still a `RuntimeError`.

### Removed

- The `nometria` Python package shim and the `nometria` console script. Import from `agentfox` (e.g. `agentfox.frameworks.langgraph`) and run `agentfox`.
- **The last of the Nometria names (rename stage B). Breaking.** The `NOMETRIA_*`
  environment fallback (settings, `NOMETRIA_CONFIG`, the CLI's `NOMETRIA_API_URL` /
  `NOMETRIA_API_TOKEN` / `NOMETRIA_USER`, `NOMETRIA_AGENT`, `NOMETRIA_MCP_LOG_LEVEL`, the
  evidence package's `NOMETRIA_AUDIT_KEY`, the dashboard's `NOMETRIA_*`, the demos'
  `NOMETRIA_DEMO_MODEL` and `NOMETRIA_DATABASE_*`), the `nometria.toml` / `[nometria]`
  config file, acceptance of `x-nometria-*` request headers, the `legacy names` doctor
  line and the one-time `NOMETRIA_` key bridge are gone. Only `AGENTFOX_*`,
  `agentfox.toml` / `[agentfox]` and `X-AgentFox-*` are read; an old name is ignored
  without a warning. Key rotation (`*_PREVIOUS`) stays.
- **Breaking:** the dashboard session cookie is `agentfox_session` (was
  `nometria_session`). Everyone is signed out once and signs in again.
- **Breaking:** the LangGraph governance state key is `__agentfox__` (was
  `__nometria__`). Declare `__agentfox__` in your state schema. Graph state checkpointed
  before the upgrade keeps its governance state under the old key, where it is no
  longer read: an in-flight thread resumed across the upgrade starts a new trace.
- **Breaking:** OPA policy documents are pushed as `agentfox_<policy>` (were
  `nometria_<policy>`). An OPA sidecar that kept documents pushed by an older version
  holds both under the same package; restart it (pushed policies are in memory) or
  `DELETE /v1/policies/nometria_<policy>` for each.
- The secrets detector's entity for AgentFox API and agent keys (`nom_api_…`,
  `nom_agt_…`) is `SECRET.AGENTFOX_KEY` (was `SECRET.NOMETRIA_KEY`). The `SECRET.*`
  policy rules match it unchanged; a rule naming the old entity must be updated. The
  key prefixes themselves are unchanged, so issued keys keep working and keep being
  detected.

- The hidden pre-consolidation CLI names. `agentfox --help` shows thirteen verbs, and
  the old top-level names had kept running, hidden, with a "now called" hint. They no
  longer resolve. `agentfox hooks run` and `agentfox mcp serve` stay,
  because installed hook configs and MCP client configs call them. Where each old name
  lives now:

  | Old | New |
  |---|---|
  | `check` · `quickscan` | `scan` · `scan --sessions` |
  | `quickstart` · `version` · `seed` | `init` · `--version` / `admin version` · `admin seed` |
  | `analyse-action` | `test action` |
  | `eval run/gate/baseline/suites/online` · `eval drift` | `test …` · `report drift` |
  | `redteam run` · `redteam probes` | `test redteam` · `test probes` |
  | `audit verify` · `audit checkpoint` | `report verify` · `admin checkpoint` |
  | `evidence export` | `report evidence` |
  | `compliance status/risk/obligations/frameworks/board/review-packet` · `compliance review` | `report …` · `report signoff` |
  | `compliance sync/compute/validate` | `admin catalog …` |
  | `tools declare` · `tools set-triggers` · `tools list` | `declare tool` · `declare triggers` · `declare list tools` |
  | `access declare-scope` · `access declare-reference` | `declare scope` · `declare reference` |
  | `boundary set` · `boundary check` | `declare boundary` · `test boundary` |
  | `sources add` · `sources import` · `sources list` | `declare source` · `declare import-sources` · `declare list sources` |
  | `escalation set` · `escalation scan` | `declare escalation` · `report escalations` |
  | `entitlement principal` · `entitlement grant` · `entitlement report` | `declare principal` · `permit user` · `report entitlement` |
  | `capability grant/list/revoke` | `permit grant/list/revoke` |
  | `guardrails …` · `guardrails test` | `policy rules …` · `test rule` |
  | `proposals …` · `approvals …` | `policy proposals …` · `permit approvals …` |
  | `auth …` · `db …` · `users …` · `hooks …` | `admin auth …` · `admin db …` · `admin users …` · `admin hooks …` |
  | `mcp tools` | `admin mcp tools` |

### Fixed

- **Benchmark honesty.** Detector patterns and similarity-corpus entries that had been
  written from the misses of the datasets they are scored on, and the AgentDojo
  grader's tool list in the repository scanner, are removed; every published number
  was re-measured. Default held-out injection recall is 16.7% (had been reported as
  26.7%). The adaptive benchmark's "unmapped" operators now test characters the
  product does not map, and show the open gap that had been hidden.
- A due-jobs pass now runs on a freshly booted instance.

## [0.3.1] - 2026-09-26

The first release published to PyPI, which is the whole point of it: 0.3.0 was
tagged before `release.yml` had a `pypi` job, so `pip install agentfox` has never
worked and the README's first command has been a `git+https` URL. From this tag
the package is on PyPI and the name is held.

Published through Trusted Publishing — PyPI mints a short-lived token from the
release workflow's OIDC identity, so there is no API token in the repository's
secrets, nothing to rotate, and nothing that keeps working if it leaks.

Also in this release, all of it since 0.3.0:

- A blocked tool call no longer leaves its trace reading `allow`. `Trace.verdict`
  was only ever written by the completion path, so every trace the tool-call path
  refused reported that nothing had happened.
- Twenty Guardrails AI Hub validators wrapped one-per-detector, each with its own
  key, telemetry and suppressions, reporting into this project's entity taxonomy —
  and with that project's own telemetry switched off, because enabling a check
  must not start exporting spans to a third party.
- The vendored gateway wheel carries two fixes it had been missing since 0.3.0.
- The latency probe measures the mechanism rather than the CI runner.

## [0.3.0] - 2026-09-25

The MVP described in the README. The package was declared `0.1.0` while every document
said `MVP v0.3`; they now agree on `0.3.0`, which is what `pyproject.toml`,
`src/agentfox/__init__.py`, `agentfox version` and the API's `/health` all report.

> Note for the maintainer: replace this heading with a release date when you tag
> `v0.3.0`. `.github/workflows/release.yml` refuses to publish unless the tag, the
> `pyproject.toml` version and `__version__` all match.

### Added

- **Containment that does not depend on detection.** Tools are declared with an impact
  tier (`read`, `write`, `high_impact`, `irreversible`), agents hold explicit capability
  grants with argument constraints, and every argument carries the provenance of where it
  came from. An irreversible tool called with an argument that originated in untrusted
  content is refused because of where the value came from, not because anything
  recognised the payload. Measured with every detector switched off; the result is in the
  README.
- **Policy engine** with three shipped packs, `baseline`, `tool-containment` and
  `eu-ai-act-high-risk`, each bindable in `observe` (records what it would have done) or
  `enforce`. `agentfox policy simulate` replays recorded traffic against a candidate
  policy and exits non-zero when the change would newly block production traffic.
- **Detector and scorer pipeline** across six surfaces (`input`, `output`, `tool_args`,
  `tool_result`, `memory_write`, `agent_message`), wrapping permissive OSS primitives as
  optional extras: Presidio for PII, NeMo Guardrails, Guardrails AI, Granite Guardian,
  garak and PyRIT for red-team probes, sqlglot for SQL action assurance. Every verdict
  carries the rule that produced it.
- **Tamper-evident audit chain** with a verifier (`agentfox audit verify`, exits 1 when
  broken) and signed checkpoints (`agentfox audit checkpoint`).
- **Compliance layer**: a control catalog, framework mappings, and evidence packages.
  Mappings ship labelled `DRAFT, UNVERIFIED, NOT LEGAL ADVICE`, because they were
  produced by engineers rather than reviewed by compliance counsel.
- **Ways to run it**: the `auto()` library patch, `agentfox serve` for the gateway and
  control-plane API, an MCP server, a LangGraph integration, and Docker Compose,
  Render and Fly deployment configs under `deploy/`.
- **CLI** covering setup and operation: `init`, `demo`, `serve`, `version`, `doctor`,
  `check`, `scan`, `tools`, `policy`, `agents`, `audit`, `evidence`, `compliance`,
  `eval`, `redteam`, `access`, `proposals`, `db`.
- **Dashboard** (Next.js, `dashboard/`) and a hosted playground that hands every visitor a
  throwaway sandbox running the same enforcement code.
- **Benchmarks** with committed result files: containment under total detector bypass,
  AgentDojo end to end, Crescendo trajectory, and PII. A nightly workflow re-measures the
  offline deterministic ones and fails when a published claim no longer matches.
- **Drift checks that fail CI rather than rot**: `scripts/api_routes.py --check` holds the
  API reference to the running app, `scripts/claims.py --check` holds every published
  number to its result file, and `harness/scripts/check_harness.py` holds the agent
  harness to the live command line.
- **Agent harness** (`harness/`) packaged as a Claude Code plugin.
- **Phase 0 improvement loop**: proposals, findings hygiene, label integrity and a
  scheduler, with scheduled red-teaming shipped disabled so a deployment opts in.
- **Deferred job queue** behind evidence export and red-team campaigns, and Alembic
  migrations, because a deployment that cannot be upgraded is not a deployment.

### Known limits

The README lists these in full and the product measures them rather than hiding them:
detection is a speed bump and not a defence, compliance mappings are draft, containment is
exactly as good as the tool declarations behind it, multi-tenancy is single-org and
enforced at the session, there is no live IdP or SSO, and text is the only modality.
`docs/status.md` reports live coverage computed by probe rather than asserted.

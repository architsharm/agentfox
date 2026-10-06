# Code structure proposal: harnesses, capability packs, and a layout newcomers can follow

Status: decided 2026-10-06 (section 9). The fix branches this waited on (security, policy,
approvals, gates-detection, grounding, webapp, monitor-sources, monitor-probes,
contributor-guide) have merged. Section 10 records what is already done and what remains per
phase.

Evidence comes from an import and file analysis of `main` @ 3b326f5 and a survey of how
other projects handle the same two problems (sources at the end).

## 1. The two things we want to be cheap

1. **Add a coding-agent harness.** Today AgentFox governs Claude Code only. Cursor, Codex CLI,
   Gemini CLI, Copilot, Kiro and Windsurf all copy Claude Code's hook contract (JSON on stdin,
   allow/deny/ask out, exit 2 blocks) but differ in field names, event names, tool names and
   failure behaviour. Adding one today touches about 8 Python files: `hooks/harness.py`,
   `hooks/capability.py`, `cli/commands/hooks.py`, `policy/coding.py`, `discovery/sessions.py`,
   `discovery/exposure.py`, `discovery/repo.py`, `cli/onboarding.py`. Only the first two were
   designed as seams.
2. **Add a capability or business use case** (payments, customer support, healthcare, an EU AI
   Act framework). Today domain content is spread over 6+ places: policy YAML, `controls.yaml`,
   `business/compile.py` vocabulary (`_TOOL_HINTS`, `_ROLES`), `core/seed.py` demo agents,
   red-team probes in Python lists, and `benchmarks/claims.yaml`. Any check that runs on the
   request path must be wired into a hard-coded tuple at `runtime/enforcement/enforcer.py:245-270`.

The target: **a new harness is one directory and its tests; a new business use case is one pack
directory; neither edits core.**

## 2. What is wrong today (short list)

- **Layers leak.** `core/seed.py` is the only reason `core` imports 9 other packages, and it
  causes 7 package cycles. `runtime` imports `integrations` (for trace correlation) while
  `integrations` imports `runtime`. `policy` imports `prove.compliance` for one constant.
- **Shared vocabulary lives in the wrong place.** `SURFACES` and `taint_rank` sit in
  `detection/base.py`, so seven unrelated packages import detection just for constants.
- **Seven ingress paths into `Enforcer`** (gateway inline route, SDK, autoguard, LangGraph,
  FastAPI, MCP governor, hooks daemon), each with its own payload mapping. The SDK, LangGraph
  and autoguard now share one exception base (`agentfox.errors`); the MCP governor
  (`McpCallBlocked`) and FastAPI (an HTTP 403) still refuse in their own way.
- **"Harness" means three things:** the Claude Code plugin in `harness/`, the adapter in
  `hooks/harness.py`, and "eval harness" in evaluation.
- **Small registries everywhere, populated by hand-written import lists**, no entry points.
- **Outside `src/`:**
  - Benchmark folders don't match the claim ids they prove.
  - Shared benchmark code is reached through `sys.path` hacks.
  - Two demo folders hold diverged forks of the same files.
  - The dashboard is three sites in one flat tree (`app/coverage` vs `app/app/coverage`).
  - Wheels are committed in two places.
  - Untracked `__pycache__` leftovers of the old layout (`audit/`, `compliance/`, `judgment/`,
    `guardrails/`) still sit in `src/agentfox`.

## 3. Target layout

Single Python distribution for now. A uv workspace split (`agentfox-core`, `agentfox-server`,
per-harness packages) is possible later. Dagster and Phoenix did it once the contributor count
justified it, but today it would add release overhead without helping readers.

```
src/agentfox/
  core/              L0 kernel: config, db, ids, crypto, tenancy, outbound, models base
    vocab.py         surfaces, taint order, effect ranks, actor types (moved from detection/policy/improvement)
    errors.py        one AgentFoxError base; Blocked / ApprovalRequired used by every ingress
  platform/          L1: things every capability uses
    ledger/          audit chain + findings (today prove/audit, prove/findings) + finding-type registry
    policy/          model, engine, store, opa, hierarchy
    registry/  identity/  providers/  jobs/
  capabilities/      L2: one folder per capability, each self-registering
    detection/  grounding/  containment/  judgment/  business/
    discovery/  evaluation/  improvement/  monitoring/
  runtime/           L3: the Enforcer. Runs checks it finds in the check registry; no capability imports
  harnesses/         L4 ingress for coding agents
    base.py          HarnessAdapter protocol, AgentEvent, Decision, capability matrix
    claude_code/     adapter.py, install.py, tools.py, fixtures/*.json
    codex/  cursor/  gemini_cli/  copilot/   (added one at a time, each with captured fixtures)
  frameworks/        L4 ingress for app frameworks: sdk, autoguard, langgraph, fastapi, mcp governor
  exporters/         L4 egress: trace correlation, prometheus, otel, siem
  apps/              L5 entry points
    cli/  gateway/  mcp_server/  report/
  packs/             built-in packs (data, plus small optional Python), see section 5
  fixtures/          demo and seed data (today core/seed.py)
```

**Dependency rule:** a layer may import only layers below it. Capabilities don't import each
other except through declared interfaces. Enforced in CI with import-linter contracts (similar
to PostHog's tach), so the rule can't quietly erode.

The cycles listed by the analysis each have a one-line fix under this layout:

| Cycle | Fix |
|---|---|
| `core/seed.py` | Moves to `fixtures/`. |
| Constants | Move to `core/vocab.py`. |
| Trace correlation | Becomes an exporter that `runtime` emits events to, instead of a module it imports. |
| `EU_CLASSES` | Moves into the EU AI Act pack. |
| `infer_impact` | Duplicated in four places today; becomes one function in `platform/registry`. |
| CLI token issuance | Moves from `gateway/auth` to `identity`, so the CLI stops importing the gateway. |

## 4. Harness adapter interface

`hooks/harness.py` already has the right idea (`HookCall`, `parse`, `render`, an `_ADAPTERS`
dict). Make it a real protocol and move every Claude-specific constant behind it.

```python
class HarnessAdapter(Protocol):
    name: str                                  # "claude-code"
    maturity: Literal["stable", "incubating", "sandbox"]
    capabilities: dict[EventKind, EventCaps]   # can_block, can_modify, can_ask, can_inject, fails_open_on_timeout
    tool_map: dict[str, CanonicalTool]         # "Bash" -> shell, "Write" -> file.write, mcp__x__y -> mcp:x/y

    def parse(self, raw: dict) -> AgentEvent: ...
    def render(self, decision: Decision, event: AgentEvent) -> HookOutput: ...   # stdout, stderr, exit code
    def install(self, root: Path, scope: Scope) -> list[FileChange]: ...
    def hooked_agents(self, root: Path) -> list[str]: ...                        # today policy/coding.py
    def mcp_config_paths(self, root: Path) -> list[Path]: ...                    # today discovery/exposure.py
    def transcripts(self) -> Iterable[Session] | None: ...                       # today discovery/sessions.py
```

- **`AgentEvent.kind`** is one of `session.start`, `prompt.submit`, `tool.pre`, `tool.post`,
  `tool.error`, `permission.request`, `stop`.
- **Tools use canonical names** (`shell`, `file.read`, `file.write`, `web.fetch`,
  `mcp:<server>/<tool>`), so policies never mention `Bash` or `run_shell_command`. The
  coding-agent policy pack is already harness-neutral.
- **`Decision`** is one of allow, deny(reason), ask, modify(args), or context(text).
- **Explicit downgrade.** When a harness can't honour a decision, the engine downgrades on
  purpose and records it. For example, Windsurf cannot rewrite input, so `modify` becomes
  `deny`. Copilot's cloud agent treats `ask` as deny and lets calls through when a hook times
  out; both are declared in its capability matrix. The docs support matrix is generated from
  these declarations.
- **Integration tiers per agent.** Native hooks are the strongest. Agents without hooks
  (Zed, Continue, Junie, Aider) fall back to weaker tiers: the existing MCP gateway (sees only
  MCP tools), then AGENTS.md instructions (advisory only). An ACP proxy tier stays
  experimental until its spec settles.
- **Tests built from real captured payloads.** Each adapter ships `fixtures/<event>.json`
  payloads captured from the real tool, never hand-written. One shared conformance suite
  checks raw payload → `AgentEvent` and `Decision` → exact stdout and exit code for every
  adapter. Other projects that guessed at payload formats got them wrong.
- **One discovery mechanism, for internal and external adapters alike.** The built-in
  adapters register through the same entry point an external package would use
  (`agentfox.harnesses`).

**Naming:**
- The current top-level `harness/` (a Claude Code plugin that lets an operator *use*
  AgentFox) becomes `plugins/claude-code/`.
- Its runtime-neutral parts (AGENTS.md, skills, reference) move to `plugins/shared/`, so a
  Cursor rules bundle or Codex AGENTS.md package can reuse them.
- "Harness" then means only one thing: a coding agent we govern.

## 5. Capability packs for business use cases

A pack is a directory. Its format follows Semgrep (rule plus test side by side), Prowler (rich
metadata per check), Gatekeeper (allowed and disallowed samples) and Falco (maturity tiers).

```
packs/payments/refunds/
  pack.yaml        id, version, maturity, requires_core, owners, tags,
                   compliance mappings, required detectors, vocabulary (tool hints, roles)
  policies/*.yaml  rules in the existing policy format
  controls/*.yaml  compliance controls (optional)
  ladders/*.yaml   business threshold ladders (optional)
  probes/*.yaml    red-team probes for this use case (optional)
  checks/*.py      optional code: detectors or request-path checks, registered by decorator
  cases/           golden allow/deny events, run by `agentfox packs test`
  fixtures/        demo agents and tools for this use case (replaces the domain parts of seed.py)
  README.md        risk, remediation, example
```

**Runtime support needed:**

- **A check registry.** Checks already share one return contract (`{evidence_issues, risks}`),
  so turning the hard-coded tuple in `enforcer.py` into `for check in checks.enabled(agent)` is
  mechanical. Ladders join the same registry.
- **No new policy fields.** New checks emit `risks` codes, and policies match them with the
  existing `action_risk: "payments.*"` glob, so the policy schema stays fixed.
- **A finding-type registry.** Today finding types are free strings across 16 files. Packs
  declare their finding types, and the dashboard reads labels from the registry.
- **Pack discovery.** The built-in `packs/` directory, plus `<project>/.agentfox/packs`, plus the
  `agentfox.packs` entry point for `agentfox-pack-*` packages on PyPI. Only `stable` packs load
  by default.
- **Splitting `compliance_data/controls.yaml` per framework.** Today it holds all seven
  frameworks in one file; it becomes `packs/compliance/<framework>/`. The EU AI Act risk-class
  logic, now spread through core, policy and prove, moves into its pack.

**First packs, all extracted from content that already exists:**

| Pack | Built from |
|---|---|
| `baseline` | Existing baseline policy |
| `tool-containment` | Existing tool-containment policy |
| `coding-agent` | Existing coding-agent policy |
| `eu-ai-act` | EU AI Act policy and risk-class logic |
| `compliance/*` | One pack per framework from `controls.yaml` |
| `payments/refunds` | Vocabulary from `business/compile.py`, refund commitments, seed agents |
| `customer-support` | Demo support tools |

Healthcare and HIPAA come later; nothing exists for them today.

**Persistent capabilities.** Most packs need no new database tables. A capability that does
(a new control with its own store) defines its models and router in its own folder, and the
gateway includes routers from the capability registry instead of a hand-written list. This is
the largest change, so it comes last (phase 5).

## 6. Outside `src/`

```
plugins/              claude-code/ (was harness/), shared/ (skills, reference, AGENTS.md)
dashboard/            same URLs, organised with Next route groups:
  app/(marketing)/  app/(product)/app/  app/docs/  app/api/
  components/{product,marketing,docs}/   lib/{product,marketing,docs,generated}/
benchmarks/
  _common/            shared loaders, scoring, db reset (replaces sys.path hacks and 4-6 copies)
  <claim-prefix>/     one folder per claim family, named as in claims.yaml (agentdojo/, injection/, jev/ ...)
  claims.yaml
demo/
  kit/                one support-tools agent, seed script, verification (the two forks merged)
  crewai/  langgraph/
scripts/
  gen/                api_routes, docs_reference, coverage
  check/              claims, harness, vendored wheels (until wheels are dropped)
  ops/                deploy_smoke, quickscan.sh
deploy/               docker, render, fly, vercel (api/ stays at root only if Vercel requires it)
docs/                 architecture/, design/, adr/ - engineering docs only; user docs live in the dashboard docs site
justfile              one command surface: test, lint, check, dev, new-pack, new-harness
```

**Other changes:**
- **Stop committing wheels.** The Vercel and demo deploys build the wheel in their build step.
  This removes a whole class of merge conflicts and the pre-commit hook.
- **`scripts/probe`** (referenced from product code today) moves into `evaluation` or becomes a
  pack's probe set.
- **`jev_data.py`** moves into `benchmarks/jev/`.

## 7. Contributor experience

`ARCHITECTURE.md` (now merged) gets:
- the layer diagram above
- an "X never imports Y" invariants list
- three recipes:
  - **Add a pack:** `just new-pack payments/chargebacks` scaffolds the directory. Fill in
    YAML, add cases, then run `just test-pack payments/chargebacks`.
  - **Add a harness:** `just new-harness codex` scaffolds the adapter and fixture folders.
    Capture real payloads with `agentfox hooks capture`, then run the conformance suite.
  - **Add a check:** write a function returning `{risks}`, decorate it with `@check`, and
    reference its risk codes from a policy.

**Ownership and tiers:**
- Each pack and adapter declares owners. CODEOWNERS is generated from them.
- New packs and adapters start as `incubating` and move to `stable` once they pass a short
  quality checklist: cases, docs, owner, captured fixtures. This mirrors Falco's maturity tiers
  and Home Assistant's quality scale.

## 8. Migration plan (after the fix branches merge)

Each phase is one PR, keeps the full suite green, and needs no compatibility shims (agreed
earlier).

| Phase | Work | Size |
|---|---|---|
| 0. Hygiene | Delete stale `__pycache__` folders; `core/vocab.py`; one blocked/approval exception base used by all seven ingress paths (started as `agentfox/errors.py`); move `core/seed.py` to `fixtures/`. The Nometria → AgentFox rename is no longer in this phase (section 9) | small |
| 1. Layers | Create `platform/`, `capabilities/`, `frameworks/`, `exporters/`, `apps/`; break the cycles listed in section 3; add import-linter to CI | medium, mostly moves |
| 2. Harness SPI | `harnesses/base.py`; move all Claude-specific constants from cli, policy and discovery into `harnesses/claude_code/`; conformance suite; rename `harness/` to `plugins/` | medium |
| 3. Second harness | Codex CLI (contract closest to Claude's, so it proves the interface cheaply), then Cursor. Needs real payloads captured from each tool. Deferred until the restructure is done (section 9) | small each |
| 4. Packs | Check registry in the Enforcer; finding-type registry; pack loader and `agentfox packs` commands; extract the first packs listed in section 5 | medium-large |
| 5. Repo outside src | Benchmarks `_common` and renames; demo merge; scripts subfolders; dashboard route groups; justfile scaffolders. Building wheels at deploy time is deferred until the restructure is done (section 9) | medium |
| 6. Capability-owned models and routers | Move capability tables out of `core/models` and register routers from capabilities | large, optional |

Phases 0-2 give the biggest readability gain. Phase 3 proves the harness story, and phase 4
proves the business-pack story.

## 9. Decisions (2026-10-06)

1. **One distribution.** No workspace split now.
2. **Capabilities live under `capabilities/`.**
3. **`harness/` becomes `plugins/claude-code/`**, with the runtime-neutral parts in
   `plugins/shared/`.
4. **Deferred until the restructure is done:**
   - new harnesses (Codex first, then Cursor);
   - stopping the committed vendored wheels;
   - the rest of the Nometria → AgentFox rename (the `NOMETRIA_*` environment fallback, the
     `nometria` console script and the `x-nometria-*` headers), because production
     environments still set them.

## 10. Progress

**Done:**

- `ARCHITECTURE.md` (domain model, a tool call traced through the code, code map, invariants),
  a `justfile` as the command surface, and a rewritten `CONTRIBUTING.md`.
- The exception base: `agentfox/errors.py` defines `AgentFoxError`, `PolicyViolation`
  and `ApprovalRequired`. The SDK, LangGraph, `auto()` (`Blocked`) and the MCP governor
  (`McpCallBlocked`) all raise `AgentFoxError` subclasses; `Blocked` and `McpCallBlocked`
  are also `RuntimeError`s. FastAPI refuses over HTTP with a 403, which is its contract.
- Phase 0 (hygiene):
  - `core/seed.py` moved to `fixtures/seed.py`. `core` imports nothing outside `core`; the
    two session extensions that live elsewhere (monitor alerts, finding webhooks) are named
    in `core/db.py:SESSION_EXTENSIONS`.
  - `core/vocab.py` holds `SURFACES`, `TAINT_ORDER`/`taint_rank`, `EFFECT_RANK`,
    `COMPARATORS` and `AUTOMATION_ACTOR_TYPE`. `EU_CLASSES` stays put until the EU AI Act
    pack (phase 4).
  - The hidden pre-consolidation CLI names and the rename hints are gone. `hooks run` and
    `mcp serve` stay at their old paths because installed configs call them.
  - `Enforcer.evaluate` is split into named private steps over one `_Evaluation` record.
  - Planning codes and change-history prose are out of `src` docstrings and comments.
  - The stale `__pycache__` folders of the old layout are gone.
- One loader for stored policy versions (`policy/store.py::load_version_document`), used by
  the runtime and every read-only view.
- Phase 1 (layers):
  - `src/agentfox/` is `core/` < `platform/` (ledger, policy, registry, identity,
    providers, jobs) < `capabilities/` (detection, judgment, grounding, containment,
    business, discovery, evaluation, improvement, monitoring, compliance) < `runtime/` <
    `frameworks/`, `exporters/`, `hooks/`, `fixtures/` < `apps/` (cli, gateway,
    mcp_server, report, the job handlers, the showcase). `prove/` and `integrations/` are
    split across those homes; `harness/` and `hooks/` are unchanged until phase 2.
  - The cycles in section 3 are broken: `core/seed.py` is `fixtures/`; the constants are
    `core/vocab.py`; trace correlation is an exporter the runtime tells about each trace
    (`runtime/trace_exporters.py`); `infer_impact` is one function in
    `platform/registry/impact.py`; operator tokens are `platform/identity/operators.py`,
    so the CLI does not import the gateway; detection no longer imports grounding or
    containment; the ledger no longer imports detection.
  - import-linter enforces the layers and "core imports nothing outside core" in CI's
    lint job and `just lint`. Three edges are named exceptions: `EU_CLASSES`
    (policy -> compliance, until the EU AI Act pack in phase 4) and evaluation's
    in-process red-team runner and live-probe adapter (-> runtime).

**Remaining, per phase:**

| Phase | Remaining |
|---|---|
| 0. Hygiene | Done |
| 1. Layers | Done, except the three import-linter exceptions named above. Intra-layer cycles remain between `capabilities/detection` and `capabilities/judgment` (the judgment detector, and egress redaction through detection's PII detector) and between `capabilities/evaluation` and `capabilities/monitoring` (opting a probe target in creates its monitor) |
| 2. Harness SPI | All of it, including the `harness/` → `plugins/claude-code/` rename |
| 3. Second harness | Deferred (section 9) |
| 4. Packs | All of it |
| 5. Repo outside src | All of it except the `justfile` itself (the scaffolder recipes remain); wheels deferred (section 9) |
| 6. Capability-owned models and routers | All of it (optional) |

## Sources (from the research pass)

- **Harness hook docs:**
  - [Claude Code hooks](https://code.claude.com/docs/en/hooks)
  - [Cursor hooks](https://cursor.com/docs/agent/hooks)
  - [Codex hooks](https://learn.chatgpt.com/docs/hooks)
  - [Gemini CLI hooks](https://geminicli.com/docs/hooks/)
  - [GitHub Copilot hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference)
  - [VS Code agent hooks](https://code.visualstudio.com/docs/agent-customization/hooks)
  - Windsurf, Cline and Kiro were checked from search summaries only.
- **Cross-harness prior art:** polyhook, hookshot, Falco prempti.
- **Standards:** Agent Plugins 1.0 (excludes hooks), the ACP proxy-chains draft, the Agent
  Control Standard, and the OTel GenAI semantic conventions.
- **Plugin patterns:**
  - pluggy / pytest entry points
  - OpenTelemetry contrib
  - LangChain partner packages
  - LiteLLM (counter-example: every provider touches central files)
  - Home Assistant quality scale
  - Backstage community-plugins
  - Falco rule maturity
- **Layouts:** Langfuse, Phoenix, Prefect, Dagster, Supabase, PostHog `products/` with tach,
  uv workspaces, matklad's ARCHITECTURE.md.
- **Rule and pack formats:** Semgrep rules, Prowler checks, OPA Gatekeeper library, Elastic
  detection-rules, Splunk security_content, Nuclei templates.

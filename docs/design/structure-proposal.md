# Code structure proposal: harnesses, capability packs, and a layout newcomers can follow

Status: decided 2026-10-06 (section 9); phases 0-2, 4 and 5 are done; phase 3 is deferred. The fix branches this waited on
(security, policy, approvals, gates-detection, grounding, webapp, monitor-sources,
monitor-probes, contributor-guide) have merged. Section 10 records what is already done and
what remains per phase.

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
| 0. Hygiene | Delete stale `__pycache__` folders; `core/vocab.py`; one blocked/approval exception base used by all seven ingress paths (started as `agentfox/errors.py`); move `core/seed.py` to `fixtures/`. The rest of the product rename is no longer in this phase (section 9) | small |
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
   - the rest of the product rename (the pre-rename environment-variable fallback, console
     script and request headers), because production environments still set them. Since
     finished.

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
    split across those homes; `harness/` and `hooks/` were left for phase 2.
  - The cycles in section 3 are broken: `core/seed.py` is `fixtures/`; the constants are
    `core/vocab.py`; trace correlation is an exporter the runtime tells about each trace
    (`runtime/trace_exporters.py`); `infer_impact` is one function in
    `platform/registry/impact.py`; operator tokens are `platform/identity/operators.py`,
    so the CLI does not import the gateway; detection no longer imports grounding or
    containment; the ledger no longer imports detection.
  - import-linter enforces the layers and "core imports nothing outside core" in CI's
    lint job and `just lint`. Three edges were named exceptions: `EU_CLASSES`
    (policy -> compliance; removed in phase 4) and evaluation's in-process red-team
    runner and live-probe adapter (-> runtime).
- Phase 2 (harness SPI):
  - `src/agentfox/harnesses/` (L4): `base.py` holds the `HarnessAdapter` protocol (`parse`,
    `render`, `install`, `hooked_agents`, `mcp_config_paths`, `transcripts`, plus a
    `preview` for the install dry run), `AgentEvent`, `Decision` (allow, deny, ask, modify,
    context), `EventCaps` and `downgrade`, which steps a decision the harness cannot honour
    down on purpose and records it on the applied decision. The registry (`get`, `known`,
    `all`) reads the `agentfox.harnesses` entry-point group, with a built-in fallback for
    source checkouts; a built-in name cannot be taken by another package.
  - Every Claude-specific constant and branch is in `harnesses/claude_code/`: the wire
    contract and the probed capability rows (was `hooks/harness.py`, `hooks/capability.py`),
    the built-in tools and their impacts and canonical names, the settings path, schema,
    event order and merge (was the `hooks install` command), `hooked_agents` (was
    `policy/coding.py`) and the transcript scanner (was `discovery/sessions.py`).
    `hooks/` keeps the transport, plus `run.py`, which goes through the registry. The
    default `--harness` is "the only one registered".
  - MCP config discovery stays in discovery, as one neutral table
    (`exposure.KNOWN_MCP_CONFIGS`, Cursor and Claude Code rows included): finding MCP servers
    is not harness governance, and `capabilities/monitoring` (L2) scans connected repos and
    cannot import L4. The Claude Code adapter's `mcp_config_paths` selects its rows from it.
  - `tests/harnesses/conformance.py` runs every registered adapter against
    `fixtures/<kind>.json` (captured payloads) and `<kind>.expected.json`. Outputs were
    checked byte for byte against the pre-refactor adapter: no behaviour change.
  - import-linter: `harnesses` is in L4, and nothing outside `harnesses/` and `hooks/`
    imports `agentfox.harnesses.claude_code`.
  - `harness/` is `plugins/claude-code/`; `AGENTS.md`, `skills/` and `reference/` live in
    `plugins/shared/`. A Claude Code plugin cannot load components outside its own
    directory, and symlinks are dereferenced only for a git-hosted marketplace, so the
    plugin carries committed copies that `scripts/check/plugins.py` (was
    `harness/scripts/check_harness.py`) writes with `--write` and fails on in CI. The docs
    page moved to `/docs/plugin`, with a permanent redirect from `/docs/harness`. The
    evaluation code no longer calls its runner a harness.
- Phase 5 (repository outside `src/`), with no URL changed:
  - **Benchmarks.** One folder per claim family: `agentdojo_e2e/` is `agentdojo/`; the loose
    prompt-injection files are `injection/` and the generalization files `generalization/`
    (each with `data/` and `results/`). `judgment/` keeps both `judgment.*` and `jev.*`, because
    Jev is the judgment tier's model; `claims.yaml` says so. `benchmarks/` is a package and
    `benchmarks/_common` holds `wipe_db`, `fetch` and the PII span arithmetic; every
    `sys.path.insert` is gone and scripts run as `python -m benchmarks.<family>.<script>`. Only
    code that was copied verbatim moved: the per-dataset loaders, `score` and `run_config`
    differ in what they score, so they stayed. `jev_data.py` and `final_numbers.json` were never
    in the repository (they are ignored local research files, moved out on purpose earlier), so
    there was nothing to move.
  - **Demo.** `demo/kit/` holds the one support-tools agent, seed and verification. The CrewAI
    demo imports it; the LangGraph demo deploys on Vercel with `demo/redteam-live-lang` as its
    root directory, so it carries a committed copy in `kit/` that `scripts/check/demo_kit.py`
    keeps identical (CI, `just check`, `tests/repo/test_demo_kit.py`). The folders keep their
    names because the Vercel root directory cannot follow a rename from the repository.
  - **Scripts.** `scripts/gen/` (api_routes, docs_reference, coverage, new_harness),
    `scripts/check/` (claims, plugins, demo_kit, the vendored-wheel hook), `scripts/ops/`
    (deploy_smoke). `scripts/probe/` stays because `src` names it, and `scripts/quickscan.sh`
    stays because the README publishes its raw URL.
  - **Dashboard.** `app/(marketing)/`, `app/(product)/app/` and `/login`, `app/docs/`,
    `app/api/`; `components/{product,marketing,docs,ui}/`;
    `lib/{product,marketing,docs,generated}/`. The home page and `app/blog/` stay at the app root:
    inside a group Next hashes their Open Graph image URLs. The build's route manifest has the
    same 166 URLs, redirects and prerendered routes before and after.
  - **Deploy.** Already in shape: `deploy/` has the Dockerfiles, compose, the dashboard Render and
    Fly configs. `render.yaml` stays at the root (the Render button reads only there) and `api/`
    stays (Vercel's root directory for the gateway). The `neon-catchup-*.sql` files stay: no doc
    records them as applied.
  - **Docs and commands.** `docs/adr/` with ADR 0001; `just new-harness <name>` scaffolds an
    adapter from `scripts/templates/harness/`.

- Phase 4 (packs):
  - **Check registry.** `platform/checks.py` holds `@check(key, surfaces=, order=, kind=)`,
    `CheckContext` (session, settings, agent, surface, content, intent, the caller's
    evidence, trace, tool and arguments, memory entry, conversation window, pipeline) and
    `merge_content`. The seven content checks moved out of the runtime into the
    capabilities that own them (`grounding/checks.py`: evidence 10, disclosure 20,
    commitments 30, context 40, sycophancy 60; `containment/checks.py`: control flow 50;
    `detection/checks.py`: trajectory 70), and the business ladders are a `ladder`
    check (`business/checks.py`). `runtime/checks.py:BUILTIN_CHECK_MODULES` names those
    modules and the Enforcer iterates the registry; an import-linter contract forbids
    the runtime importing them. `agentfox.checks` entry points and packs' `checks/*.py`
    add more; those cannot fail a request.
  - **Finding-type registry.** `platform/ledger/finding_types.py`: 61 built-in types
    (title, default severity, description, owner), plus what packs declare.
    `raise_finding` warns on an unregistered type and refuses it under
    `AGENTFOX_STRICT_FINDING_TYPES`, which the test suite sets; a static test reads
    `src` for every type literal. `GET /api/findings/types`, `agentfox findings
    --types`, and the dashboard's labels are generated from it
    (`dashboard/lib/reference/finding-types.json`).
  - **Pack format and loader.** `platform/packs` (`PackManifest`, a pydantic model whose
    JSON Schema `agentfox policy packs validate --schema` prints), discovery from
    `src/agentfox/packs/`, the `agentfox.packs` entry-point group and
    `<project>/.agentfox/packs/`, the `pack_maturity` setting (stable by default) and
    `requires_core`. The policy store, the control catalog, obligations, the threat
    catalogue, the red team (`probes/`), the policy compiler (`vocabulary`), the
    fallback policies (`fallback`), policy lint (`condition_values`) and EU AI Act
    classification (`annex_iii_cues`, `prohibited_cues`) read from packs.
  - **First packs.** `baseline`, `tool-containment`, `coding-agent` (their policies),
    `eu-ai-act` (its policy, the risk classes, the classification cues, the tiers its
    policy protects as a fallback), `compliance/catalog` (controls, obligations, threats
    as one pack: most controls map to several frameworks, so a per-framework split would
    copy them), `payments/refunds` (the compiler's tool and role vocabulary, the
    refund-approval ladder template, the payments desk of the demo world),
    `customer-support` (the support desk of the demo world). Each has `cases/`. The
    commitment patterns stayed in grounding (they are not refund-specific) and no
    built-in red-team probe moved (none is domain-specific).
  - **CLI and scaffolding.** `agentfox policy packs` (bare: the policy-file table, as
    before) `list|show|test|validate|new`; `just new-pack <id>` and `just test-pack`
    over `src/agentfox/packs/_template/`.
  - **import-linter.** `agentfox.packs` is in the capabilities layer and nothing imports
    it; the `EU_CLASSES` exception is gone.
  - Behaviour: the same decisions, audit entries and findings for a recorded request
    set (seed world, demo, content checks, ladders, red-team campaigns, catalog). The
    dashboard's `budget_breach` label was corrected.

**Remaining, per phase:**

| Phase | Remaining |
|---|---|
| 0. Hygiene | Done |
| 1. Layers | Done, except the two import-linter exceptions named above (evaluation -> runtime). Intra-layer cycles remain between `capabilities/detection` and `capabilities/judgment` (the judgment detector, and egress redaction through detection's PII detector) and between `capabilities/evaluation` and `capabilities/monitoring` (opting a probe target in creates its monitor) |
| 2. Harness SPI | Done. `agentfox hooks capture` is not built (`just new-harness` was added in phase 5); the PreToolUse and PostToolUse fixtures were re-captured verbatim from Claude Code 2.1.292 |
| 3. Second harness | Deferred (section 9) |
| 4. Packs | Done. Remaining: compliance packs per framework if a framework ever ships controls of its own, packs' fixtures beyond the demo world's two desks (the HR screening agent has no pack), CODEOWNERS generated from pack owners, and a check registry entry for the action analysis and cascade/data-access risks, which still run in the runtime |
| 5. Repo outside src | Done, except: building wheels at deploy time (deferred, section 9); `docs/getting-started.md` and `docs/product-tour.md` are user docs still in `docs/` (fold into the website docs, then delete); three comments and one data string in `src/` still cite pre-phase-5 paths (`scripts/api_routes.py` in `apps/gateway/app.py` and `routes/inline.py`, `benchmarks/agentdojo_e2e/` in `discovery/exposure.py`, `benchmarks/data_generalization/` in `detection/data/injection_corpus.json`), left so this phase needed no wheel rebuild |
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

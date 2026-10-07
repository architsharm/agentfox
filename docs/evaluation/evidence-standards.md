# How to read our numbers

**Read this before quoting anything from [`benchmarks/`](../../benchmarks/README.md).** It states what each
kind of evidence here can and cannot establish, and the limits that apply before any number does.

## The four rules every number follows

1. **A public dataset or a committed fixture.** Named, licensed and linked, fetched by a re-runnable
   script. No number rests on data a reader cannot obtain.
2. **The real shipping code.** Benchmarks call the same enforcement path a production request takes, not
   a reimplementation written to score well.
3. **Per-example predictions are saved**, not just aggregates, so a reader can audit individual
   decisions rather than trusting a percentage.
4. **Negative and inconclusive results are reported next to positive ones.** Two capability areas here
   have no precision/recall number at all, and say why. One benchmark is blocked on dataset licensing and
   says so.

## What the limits are, stated before the numbers

**Static benchmarks overstate defences.** Every fixed dataset was written by someone who never saw our
output. [*The Attacker Moves Second*](https://arxiv.org/abs/2510.09023) reports over 90% attack success
against twelve published defences once attackers adapt. Our own
[adaptive benchmark](../../benchmarks/adaptive/README.md) reproduces that pattern against us, on purpose.

**Detection numbers are not robustness numbers.** Our injection recall is a measure of how expensive we
make an attack, not of whether an attack is possible. It is possible. Read
[containment](../../benchmarks/containment/README.md) for the claim that actually carries weight.

**Containment depends on declarations.** Tool impact tiers, capability grants, numeric constraints,
trigger declarations and access scopes are all declared by an operator. An irreversible tool recorded as
`read` is one a tainted argument can reach. `agentfox doctor` grades that readiness directly, and it is
the first thing to check before trusting any containment result in your own deployment.

**Compliance mappings are drafts.** Every framework mapping ships marked
`DRAFT — UNVERIFIED / NOT LEGAL ADVICE` until a named, qualified reviewer signs it
(`agentfox report review-packet`). Draft mappings are not legal conclusions.

**A benchmark is not a deployment.** Seed fixtures use real shipped policies and grants, but your agents,
tools and policies are different. Every script here runs against your own database if you point it there.

## What kind of evidence each result is

| Kind | What it establishes | What it does not |
|---|---|---|
| **Labeled-dataset score** (injection, PII, action safety) | How the shipping code scores against independently-authored ground truth | That an adaptive attacker cannot get through |
| **Detector-disabled replay** (containment, AgentDojo end to end) | What still holds when content inspection contributes nothing | That a model cannot be fooled — compromise is the premise, not the finding |
| **Adaptive search** (adaptive) | A realistic lower bound on attacker cost against our stack | An upper bound: gradient, reinforcement-learning and human attackers are stronger and are not implemented |
| **Self-constructed scenario** (entitlement, containment) | That a mechanism behaves correctly across varied real content | A classifier stress test; a correctly-built check scores well by construction |
| **Investigated, not benchmarkable** (source authority, secrets) | That we looked, and why a standard score does not apply | Anything about capability — read the reasoning, not a number |
| **Computed coverage** (`status.md`, `coverage-map.md`) | That a capability is wired and fires, verified by execution | That it is *good*; depth is the test suite's job |

## Numbers we refuse to quote

- **PINT.** Vendor-reported scores exist for competitors, but its dataset was never public and the
  repository is archived, so no one can reproduce it. We cite it only as market context, never as a score.
- **Anything from a marketing page we cannot reproduce**, ours or anyone else's.
- **Our own aggregate "coverage" percentages in a sales context.** They answer "is it wired", which is not
  the question a buyer is asking.

## If you get past it, tell us

We would rather know. Open an issue at <https://github.com/architsharm/agentfox/issues> with the payload
and the surface it reached. Findings that defeat a shipped detector are added to
[`tests/corpus/injection.py`](../../tests/corpus/injection.py) **when they are found, not when they are
fixed**, which is the rule that keeps the corpus honest — a known miss sitting in the corpus failing is
more useful than one quietly left out.

## Reproducing everything

```bash
uv run python -m benchmarks.containment.run_containment_benchmark
uv run python -m benchmarks.agentdojo.run_agentdojo_e2e   # superseded label-assigned run
uv run python -m benchmarks.adaptive.run_adaptive_benchmark
uv run python -m benchmarks.injection.run_prompt_injection_benchmark
uv run python scripts/gen/coverage.py --write
uv run python scripts/probe/run.py --md > docs/design/coverage-map.md
```

Everything above runs offline, with no API key and no model weights, against a throwaway database.
The AgentDojo headline (provenance inferred from the real tool outputs) needs AgentDojo installed in a
separate environment; its commands are under "Reproducing" in
[`benchmarks/agentdojo/README.md`](../../benchmarks/agentdojo/README.md). Detector changes
since some results files were written mean a few of them are due for a re-run; until then the
published figures are the ones those files hold.

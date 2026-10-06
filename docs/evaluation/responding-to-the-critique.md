# Responding to "the AI security industry is bullshit"

**For the buyer who has read the critique and wants to know whether any of this is worth paying for.** The
strongest public criticism of our category — most recently
[Sander Schulhoff's essay](https://sanderschulhoff.substack.com/p/the-ai-security-industry-is-bullshit),
backed by [*The Attacker Moves Second*](https://arxiv.org/abs/2510.09023), which he co-authored with
researchers from OpenAI, Google DeepMind and Anthropic — is largely **correct**, and we would rather say so
than argue with it.

This document states which parts we accept, which parts we think are wrong, and what we changed as a result.
Everything here is checkable from this repository.

---

## The parts we accept

**1. Adversarial robustness is unsolved, and adaptive attacks defeat published defences.** The paper reports
over 90% attack success against twelve defences once the attacker adapts. We do not claim to be the
exception. Our own held-out injection recall is **26.7%** with the default heuristic detector and
**66.7%** with the opt-in classifier ensemble, both published in
[`benchmarks/REPORT.md`](../../benchmarks/REPORT.md) alongside the rounds where it was 0%.

**2. Static guardrail benchmarks are misleading.** They are, and we have first-hand evidence. Swapping our
classifier roughly doubled recall *and* cut the false-alarm rate on a benign trigger-word stress set from
42.2% to 11.5%; adding an ensemble backstop to recover generalization recall pushed it back up to 41.3%. We
shipped that as a disclosed, switchable trade-off rather than quoting whichever number flattered us. We also
decline to quote a [PINT](https://github.com/lakeraai/pint-benchmark) score, because that dataset was never
public and the repository is archived.

**3. A guardrail that creates confidence is worse than no guardrail.** Agreed, and it is why the product's
primary control is not a detector at all.

**4. Permissions and classical security do the heavy lifting.** Agreed. The design the critique endorses —
[CaMeL](https://arxiv.org/abs/2503.18813)-style permission scoping — is the same shape as our capability
grants, argument-provenance ceilings and declared tool impacts.

**5. Most production failures are not attacks.** Agreed, and this is our founding premise rather than a
concession. Our own [failure-mode analysis](../design/failure-modes.md) reports resolution and escalation breakdowns at
**31.1%** of catalogued failures, execution and action failures **up 62%**, and hallucination-related
failures **under 10%**. A product aimed only at jailbreaks is aimed at the smallest slice.

---

## The parts we think are wrong

**"No really damaging instances have happened yet."** [EchoLeak](https://arxiv.org/abs/2509.10540)
(CVE-2025-32711, CVSS 9.3) was zero-click data exfiltration from Microsoft 365 Copilot; a GitHub Copilot flaw
(CVE-2025-53773) reached remote code execution on developer machines. The defensible version of the claim is
narrower: few *confirmed mass exploitations* in the wild. Damage also arrives without an attacker at all —
the coding agent that wiped 1.9 million production rows was nobody's exploit.

**Judging the whole category on one axis.** If adversarial robustness is unsolvable, that is an argument for
bounding what a compromised agent can *do*, not an argument that nothing is worth buying. The essay's own
figure — that in 99% of deployments adversarial robustness is not the real concern — points at governance,
entitlement and action safety, which is the category it dismisses.

**"Automated red-teaming provides no value."** Overstated. Probing a *deployment's own* grants, policies and
declared impacts is configuration regression testing, not a robustness certificate. Ours found five real bugs
in our own product, including a policy threshold that silently discarded 15 already-detected attacks.

**The implied standard that a bypassable control is worthless.** No security control survives that test.
Firewalls, spam filters and endpoint detection are all bypassable, all still bought, and all still useful,
because they raise cost and buy time.

**"Just hire someone who understands this deeply."** Good advice that does not scale to twenty product teams,
and it is also the advice of someone who sells training and advisory services. The expertise has to be
encoded in the platform, which is what our [operator plugin](../../plugins/claude-code/README.md) is for.

---

## What we changed because of it

| Change | Where |
|---|---|
| Built a benchmark that **deletes the detection layer entirely** and measures what still holds | [`benchmarks/containment/`](../../benchmarks/containment/README.md) |
| Replayed AgentDojo's ground truth end to end, 97 user tasks and 949 attack pairs, with provenance inferred from the real tool outputs, reporting benign utility alongside containment | [`benchmarks/agentdojo/`](../../benchmarks/agentdojo/README.md) |
| Published our own adaptive-attack success rate against ourselves (**73% at 50 attempts**), using the critique's own protocol — and fixed the three detector bugs it found | [`benchmarks/adaptive/`](../../benchmarks/adaptive/README.md) |
| Measured non-English parity instead of claiming multilingual support | [`benchmarks/multilingual/`](../../benchmarks/multilingual/README.md) |
| Measured gradual multi-turn (crescendo) attacks, which per-message detection cannot see | [`benchmarks/crescendo/`](../../benchmarks/crescendo/README.md) |
| Made containment readiness a first-class health check, ahead of detectors | `agentfox doctor` |
| Led the README with what holds when detection fails, not with detection accuracy | [README](../../README.md) |

## The claim, stated so it can be falsified

With **every detector disabled** — a total bypass, not a simulated miss:

- 8 of 8 attack scenarios were still contained, with zero detector signal, while 4 of 4 legitimate calls were
  still allowed.
- On AgentDojo (97 user tasks, 949 attack pairs, ground truth executed and replayed), with argument
  provenance inferred from the real tool outputs, **588 of 588 attack pairs** were contained at
  session-level taint. The price was benign utility: **24 of 97 benign tasks** ran without escalation to
  a human. Per-argument taint ran 37 of 97 benign tasks and contained 527 of 588 attack pairs.
- Our earlier AgentDojo figures (every acting attacker call contained, 42 of the 42; every legitimate
  call allowed, 552 of the 552) took provenance from the benchmark's labels and counted each task once per registered AgentDojo
  version. They are withdrawn; read them as the policy's behaviour given perfect provenance.

Check it yourself:

```bash
uv run python -m benchmarks.containment.run_containment_benchmark
uv run python -m benchmarks.agentdojo.run_agentdojo_e2e   # label-assigned upper bound
# inferred provenance: benchmarks/agentdojo/README.md, "Reproducing"
```

## What we still do not claim

- That our detection is good. It is the weakest layer and we publish its real numbers.
- That a model cannot be fooled. Assume it will be.
- That containment is free of assumptions: it is exactly as good as the declared tool impacts, grants,
  constraints, triggers and scopes behind it. An irreversible tool declared as `read` is one a tainted
  argument can reach. `agentfox doctor` now grades that readiness directly.
- That our compliance mappings are legal advice. All of them ship marked
  `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` until a qualified reviewer signs them.

# Finding a corpus we did not write

Every number so far came from a corpus I generated: the refund agent, then the
coding / HR / data-access domains. The ground truth is mechanical in each case,
but I also chose the failure modes, which means a result like "Jev judges what
text is about, not what it does" could be a description of my own test-writing
habits rather than of Jev.

So: what exists publicly, and does any of it fit?

## What is out there

| dataset | size | shape | licence | fits? |
|---|---|---|---|---|
| **[SafePyramid](https://huggingface.co/datasets/ByteDance/SafePyramid)** | 3,000 cases / **77,755 rule judgments** | conversation + in-context policy of 12–37 numbered rules + exact set of violated rule numbers | CC-BY-4.0 | **yes, directly** |
| [Agent-SafetyBench](https://huggingface.co/datasets/thu-coai/Agent-SafetyBench) | 2,000 cases | agent instruction + tool environments + `fulfillable` flag and failure modes | MIT | partly — needs agent runs |
| [τ²-bench](https://github.com/sierra-research/tau2-bench) | retail / airline / telecom | interactive tasks with a domain policy document per domain | MIT | policies yes, labels need runs |
| [ST-WebAgentBench](https://huggingface.co/datasets/ST-WebAgentBench/st-webagentbench) | 375 tasks / 3,057 policy instances | enterprise web tasks, 3-level policy hierarchy, violation-detection functions | Apache-2.0 | needs BrowserGym |
| [R-Judge](https://aclanthology.org/2024.findings-emnlp.79.pdf) | 569 records | agent interaction records with binary safety labels | — | too small |

Agent-SafetyBench, τ²-bench and ST-WebAgentBench all measure *an agent behaving*,
so getting labelled judgments out of them means running agents first and
labelling trajectories second. That is a different project. What we need is the
judgment itself already labelled, which is what SafePyramid has.

## Why SafePyramid is the right one

The unit of judgment is a **rule**, not a case. Each case supplies a policy of
12–37 numbered rules and the exact subset the conversation violates, so the
corpus is **77,755 labelled allow/flag decisions at 23.9% positive** across ten
domains and three difficulty levels. That is roughly 36× the refund corpus,
written by someone else, with the policy text supplied rather than invented.

```
domain                      rules     flag    rate       level  cases  rules/case
academic_integrity          7,696    1,917   24.9%       L0      1000          16
content_moderation          7,793    1,823   23.4%       L1      1000          29
critical_infrastructure     7,776    1,788   23.0%       L2      1000          33
defamation                  7,720    1,889   24.5%
discrimination              7,781    1,881   24.2%
fraud                       7,797    1,981   25.4%
intellectual_property       7,732    1,810   23.4%
privacy                     7,812    1,884   24.1%
sexual_content              7,827    1,783   22.8%
specialized_advice          7,821    1,846   23.6%
```

Three things it gives us that the generated corpora could not:

1. **Designed distractors.** 46,010 of the 59,153 non-violated rules are marked
   as deliberate near-misses. False blocks have been the harder error throughout
   this work, and this is a labelled stratum of exactly those.
2. **A difficulty axis.** L0 to L2 triples the rule count per case while holding
   conversation length constant, which separates "the policy got harder" from
   "the text got harder" — something I could not do with my own corpora.
3. **Rule interactions.** Rules carry `[overrides: Rule 16]` annotations and
   conditional waivers. Nothing I wrote tested a policy whose rules modify each
   other, and that is where routing between code and judgment is least obvious.

It also directly tests the parallel-questions finding: a case with 33 rules is
33 questions over one shared conversation, which is the batching shape Jev was
measured at 512 questions for.

## What it is not

SafePyramid is chatbot policy compliance over content-safety domains. It is not
agent tool use — no commands, no SQL, no refunds, no arithmetic predicates. The
code rung of the cascade has very little to own here, which makes it a sharp
test of the *judgment* rungs and a poor test of routing to code.

So it does not replace the generated corpora, it covers their blind side. The
honest split:

- **SafePyramid** — do the judgment findings survive on data we did not write,
  at scale, with real distractors and interacting rules?
- **generated corpora** — does routing to code help, which needs predicates
  that code can actually own?

If the agentic side needs the same treatment later, τ²-bench's three domain
policies are the cleanest starting point, but that means running agents and
labelling trajectories rather than reading labels off a file.

## Two parsing traps

Both cost real time and both silently corrupt the corpus rather than erroring.

**The rules are shuffled.** They appear in the policy as 1, 2, 3, 37, 4, 30,
5 … A parser that assumes ascending order drops every out-of-order rule; mine
did, and lost 2% of cases while looking like it had worked.

**The rubric text is a prefix, not a match.** A rule in the policy may end with
`[overrides: Rule 16]`, which the rubric omits. Comparing for equality flags
1,565 of 3,000 cases as broken when nothing is wrong.

`scripts/sp_corpus.py` has a `validate()` that checks both, plus that every
violated and distractor id resolves and that rule ids form a clean 1..N set. It
reports clean on 3000/3000 for v1.1.

```bash
python scripts/sp_corpus.py --download
python scripts/sp_corpus.py
```

`to_judgments()` emits one row per (case, rule) in the same shape as the other
corpora, so the cascade and sweep scripts can consume it unchanged.

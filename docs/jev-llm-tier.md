# The LLM tier: a general model as a judge

> **Superseded on the injection figures.** Every injection number below was
> measured with the detector's original question ("does this try to give the
> agent instructions") and against a benign set of three sentences repeated —
> which hid a 41.5% precision problem. The question was rewritten to ask about
> *override* and the benign set replaced with NotInject's 339 rows; the
> detector now scores **F1 94.9 at 94.6% precision**. See
> [`benchmarks/judgment/README.md`](../benchmarks/judgment/README.md). The rest
> of each document stands; this note marks the figures not to quote.

`capability.py` has had `llm` and `local_llm` in its routing table since the
start, and nothing implemented them — so enabling either was a setting with no
effect. This is the implementation, and the measurement of what it buys.

## Through the provider interface, not an SDK

`providers/base.py` states X-2 plainly: no feature may exist that only works
on one vendor. A judge wired to one API would be exactly that, so `LlmJudge`
goes through `get_provider()` and works with Azure, Bedrock, Vertex, OpenAI,
Anthropic, LiteLLM or a self-hosted endpoint without any of them being special
-cased.

The same class serves both tiers, and the thing that separates them is real
rather than nominal:

```python
Tier.LOCAL_LLM   endpoint host is loopback      → no egress, no gate
Tier.LLM         anything else                  → gated like every other egress
```

Locality comes from the endpoint, not the vendor's name or the model's
weights, and anything not *provably* local is treated as egress — a
misconfigured URL is gated rather than quietly exempted.

## Where it earns its cost

Measured against the tiers below it, same rows, same thresholds:

```
tiers enabled            acc     prec   recall     F1     ms
deterministic only     45.0%   100.0%   26.7%    42.1      0
+ jev                  90.0%    93.3%   93.3%    93.3    347
+ llm                  95.0%    93.8%  100.0%    96.8    715
+ jev + llm            95.0%    93.8%  100.0%    96.8   1086
```

(commitments surface, 100 refund replies)

**The LLM closes `presupposition`**, which is the one thing Jev could not do:
"Shall I confirm that your 50 USD has already been approved?" scores 0.47 from
Jev and **0.85** from the LLM. That is the evidence table's prediction holding
up — Jev 7%, LLM 85% on performative work — and it takes recall to 100%.

**Jev and the LLM together are no better than the LLM alone here**, at 1.5x
the latency. Enabling both is not automatically the right answer, and the
panel's union does not pretend otherwise.

Across the whole spectrum, adding `llm` on top of `jev`:

| area | jev only | + llm | gain | latency |
|---|---|---|---|---|
| commitments | 92.6 | **96.8** | +4.2 | 343 → 1044ms |
| answerability | 94.2 | **96.8** | +2.6 | 302 → 570ms |
| PII presence | 86.5 | **88.6** | +2.1 | 353 → 970ms |
| injection | 84.8 | 84.9 | +0.1 | 341 → 1276ms |
| SQL blast radius | 100.0 | 100.0 | 0.0 | unchanged |

So: worth its cost on `performative`, marginal elsewhere, and forbidden on
structural work like every other judgment tier. An operator who wants one
hosted tier and not two should pick by surface, and these are the numbers to
pick with.

## The panel

`judgment/panel.py` resolves a decision kind into the judges that are both
*permitted* (by the routing table) and *reachable*, then unions their answers
by score. Two properties matter:

- **Policy and transport are separate.** `permitted_tiers()` asks only what
  the router allows; `judges_for()` also asks what is reachable. Injecting a
  client — in a test, or to wire a bespoke judge — supplies transport and
  never permission, so no caller can route around the table.
- **One tier failing degrades to the others.** `JevUnavailable` is raised only
  when *nothing* could answer, so an outage at one vendor is not an outage of
  the decision.

Union by maximum score carries `capability.py`'s monotonicity promise into the
runtime: adding a tier can raise a question's score, never lower it.

## Two parsing facts

A general model returns prose unless held to a shape, and will add a preamble
and bullets however the prompt is worded. The parser therefore looks for each
question's **own id** rather than trusting the reply's structure, and a
question the model skipped is **absent** rather than zero — absent means "no
answer", zero would mean "confidently no".

One more, found by running it: `CompletionRequest.model` defaults to the
literal string `"default"`, which the hosted adapters pass straight through to
the API, where it 404s. `judgment_llm_model` is sent instead, and empty means
"let the adapter choose".

## Configuring it

```toml
judgment_tiers       = ["deterministic", "jev", "llm"]
allow_egress         = true
judgment_llm_provider = "anthropic"     # any registered provider
judgment_llm_model    = "claude-haiku-4-5-20251001"
```

Self-hosted, with no egress at all:

```toml
judgment_tiers       = ["deterministic", "local_llm"]
judgment_llm_provider = "litellm"
litellm_base_url      = "http://localhost:11434"
```

Note that `LiteLLMProvider.available()` currently also requires
`allow_egress`, even for a loopback URL. That is existing provider behaviour
and this work did not change it, but it means a genuinely local judge still
needs the flag today — worth fixing separately.

## Tests

`tests/test_judgment_llm.py` (19): the parser against preambles, bullets,
`=` separators, skipped questions and out-of-range scores; a provider failure
and unparseable output both becoming `unavailable` rather than a verdict;
`echo` refusing to judge; locality derived from five endpoint shapes; and the
panel refusing to assemble any tier for a structural kind however many are
configured.

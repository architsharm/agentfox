# Guard latency, head to head on one machine

On short messages, AgentFox's default checks take **63.1 ms at the median**. LLM Guard's prompt-injection scanner takes **56.1 ms** on the same messages, measured in the same session. With only its deterministic checks, AgentFox takes 7.4 ms. Prompt Guard 2 22M is the fastest model here at 25.5 ms.

Every system ran on the same 880 messages, on the same machine, on CPU, under the same Python, one request at a time. AgentFox appears at each of its levels.

| System | Detects | Short messages, p50 / p95 (ms) | Long messages, p50 / p95 (ms) |
|---|---|---|---|
| **AgentFox deterministic** (no model) | PII, secrets, injection patterns, unsafe content, schema, unicode, insecure code | 7.4 / 9.1 | 11.7 / 38.9 |
| **AgentFox default** (deterministic + ML classifier, cache off) | The above, plus prompt injection and jailbreaks by classifier | 63.1 / 77.6 | 117 / 412 |
| **AgentFox default, score cache on** | Same | 60.1 / 67.2 | 104 / 401 |
| **AgentFox extended** (default + similarity search, cache off) | The above, plus similarity to known attacks | 71.0 / 89.0 | 126 / 464 |
| **AgentFox with LLM judges, default mode** (gpt-4.1-mini, inline only when a rule relies on them) | The above, plus injection and PII judged by an LLM | 74.1 / 98.5 | 122 / 356 |
| **AgentFox with LLM judges always inline** (gpt-4.1-mini) | Same | 865 / 1,093 | 879 / 1,448 |
| LLM Guard, prompt-injection scanner | Prompt injection | 56.1 / 66.2 | 90.7 / 218 |
| Meta Prompt Guard 2 86M | Prompt injection and jailbreaks | 54.4 / 62.6 | 86.8 / 209 |
| Meta Prompt Guard 2 22M | Prompt injection and jailbreaks | 25.5 / 29.9 | 48.4 / 106 |
| Guardrails AI, DetectJailbreak validator | Jailbreaks | 99.4 / 107 | 149 / 325 |
| LLM Guard, nine default input scanners | Injection, PII, secrets, toxicity, gibberish, language, invisible text, token limit, regex | 249 / 316 | 348 / 650 |
| OpenAI omni-moderation (hosted, network included) | Harm categories, not injection | 387 / 484 | 395 / 509 |
| NVIDIA NeMo Guardrails, self-check input rail (gpt-4.1-mini) | One LLM policy check | 758 / 1,049 | 787 / 1,201 |

Source: [`results/summary.json`](results/summary.json); per-call rows are in `results/<system>.csv`. LLM Guard's nine scanners and Guardrails AI ran earlier the same day, on the same machine and Python. Every other row was measured in one session, back to back.

## Reading it

**Same model size, same speed.**
- **The model:** AgentFox's classifier (PIGuard), the model inside LLM Guard's scanner (ProtectAI deberta-v3-base v2) and Prompt Guard 2 86M are all base-size DeBERTa models. Each takes about 50 ms here.
- **The other ~7 ms:** AgentFox goes over HTTP to a local gateway, which adds about 5 ms. It also runs its PII, secrets and other checks on every call; together those take 7.4 ms at the median.
- **Why 22M is faster:** Prompt Guard 2 22M is about a quarter the size of the others.

**Long messages.**
- **Reading length:** AgentFox reads the first 4,000 characters in overlapping 256-token windows. LLM Guard and Prompt Guard stop at 512 tokens.
- **The cost:** that is more work per long input. Text over 200 characters gets a 1,000 ms check budget, so every long input here was read to the end (none ran out of time), at a long-message p95 of 412 ms.
- **The gain:** in exchange, an injection placed beyond the first 512 tokens of a long document is read at all.

**With an LLM judge.**
- **Default mode:** a judge waits inline only when an enforcing rule relies on it, so most checks cost about what the extended level does.
- **The gap to NeMo:** with every judge inline, AgentFox takes about 100 ms longer at the median than NeMo's single self-check call.
- **Where it goes:** AgentFox's judge returns three scores (injection override, exfiltration, personal data, about 18 output tokens), where NeMo's returns one word. Earlier measurements put about 90 ms of the gap on that answer.

**Hosted APIs.** About 260 ms of the OpenAI moderation figure is the network round trip from Bengaluru to the API. It is in the number because a hosted guard always pays it.

## What is and is not comparable

- **Scope differs.** AgentFox's default layer runs many detectors. LLM Guard's scanner, Prompt Guard and the Guardrails AI validator each detect one class of attack. OpenAI moderation does not look for injection at all; it flagged 0 of its 300 messages.
- **Speed, not accuracy.** This measures speed only. The flag rates in the per-call files only show that each system returned verdicts.
- **AgentFox goes over HTTP.** Its figures include a loopback HTTP round trip to the gateway, which adds about 5 ms. Everything else ran in-process, except the hosted API.
- **Threads.** The competitors used PyTorch's default of 6 threads. AgentFox's classifier runs on one batching worker per model.
- **One laptop.** These are numbers from one laptop, not a server.

## Setup

- **Machine:** Apple M1 Pro, 8 cores, 16 GB.
- **CPU only:** `AGENTFOX_MODEL_DEVICE=cpu` for AgentFox; the Mac GPU was disabled for the others.
- **Python:** uv-managed Python 3.12.13 for every system.
- **Library versions:**
  - AgentFox with the locked dependencies from `uv.lock` (torch 2.13.0, transformers 5.15.1);
  - llm-guard with torch 2.14.1 and transformers 4.51.3;
  - nemoguardrails 0.24.1;
  - guardrails-ai with the `guardrails_ai.detect_jailbreak` validator from PyPI.
- **Warm-up and pacing:** each system was warmed with 10 calls, then timed one message at a time on the client.
- **Messages:** [`results/messages.json`](results/messages.json).
  - **730 short messages:** attacks and benign controls from the attack suites of 73 of the 109 benchmark repositories, up to 10 per repository.
  - **150 long ticket histories:** built by joining suite messages, since every suite message is under 230 characters.
  - **Subsample:** the LLM-based, hosted and nine-scanner systems ran on a fixed 300-message subsample (seed 0).

**Why the Python build matters.** The same libraries ran AgentFox's model about 45% slower on a Miniconda build of Python than on the uv-managed build. The production image uses `python:3.12-slim`.

## Reproduce

Each competitor needs its own environment, because their pins conflict (llm-guard pins `transformers==4.51.3`, and this project needs 5).

```bash
uv export --frozen --no-hashes --no-emit-project --extra pii --extra classifiers > /tmp/req.txt
uv venv --managed-python -p 3.12 /tmp/h2h-af && uv pip install -p /tmp/h2h-af/bin/python -r /tmp/req.txt
uv venv --managed-python -p 3.12 /tmp/h2h-llmguard && uv pip install -p /tmp/h2h-llmguard/bin/python llm-guard
uv venv --managed-python -p 3.12 /tmp/h2h-nemo && uv pip install -p /tmp/h2h-nemo/bin/python nemoguardrails langchain-openai
uv venv --managed-python -p 3.12 /tmp/h2h-gai && uv pip install -p /tmp/h2h-gai/bin/python guardrails-ai guardrails-ai-detect-jailbreak

AGENTFOX_MODEL_DEVICE=cpu /tmp/h2h-af/bin/python benchmarks/latency/head_to_head/run_agentfox.py agentfox-L1 agentfox-L2 agentfox-L2-cache-on agentfox-L3 agentfox-L4 agentfox-L4-judge-inline
/tmp/h2h-llmguard/bin/python benchmarks/latency/head_to_head/run_local_models.py llmguard-pi llmguard-default pg2-86m pg2-22m
BENCH_SUBSAMPLE=300 /tmp/h2h-nemo/bin/python benchmarks/latency/head_to_head/run_nemo.py
/tmp/h2h-gai/bin/python benchmarks/latency/head_to_head/run_gai.py
BENCH_SUBSAMPLE=300 /tmp/h2h-llmguard/bin/python benchmarks/latency/head_to_head/run_openai_mod.py
```

- **Keys and access:** the LLM-based systems need `OPENAI_API_KEY`. Prompt Guard 2 needs Hugging Face access to Meta's gated models.
- **Output:** each run writes `work/percall/<system>.csv` (set `H2H_WORK` to change where).
- **Messages:** `build_messages.py <maps_dir> <out>` rebuilds the message set from the benchmark's repository maps.

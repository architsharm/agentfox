# Guard latency, head to head on one machine

On short messages, AgentFox's default checks take **58.4 ms at the median**. LLM Guard's prompt-injection scanner takes **51.1 ms** on the same messages, measured in the same session. Prompt Guard 2 22M is the fastest model here at 21.7 ms.

Every system ran on the same 880 messages, on the same machine, on CPU, under the same Python, one request at a time.

| System | Detects | Short messages, p50 / p95 (ms) | Long messages, p50 / p95 (ms) |
|---|---|---|---|
| AgentFox default (deterministic checks + ML classifier, cache off) | Prompt injection, jailbreaks, PII, secrets, unsafe content, schema, unicode, insecure code | 58.4 / 64.6 | 99.8 / 273 |
| LLM Guard, prompt-injection scanner | Prompt injection | 51.1 / 56.3 | 83.3 / 194 |
| Meta Prompt Guard 2 86M | Prompt injection and jailbreaks | 49.7 / 55.6 | 81.6 / 191 |
| Meta Prompt Guard 2 22M | Prompt injection and jailbreaks | 21.7 / 24.6 | 44.5 / 99.3 |
| Guardrails AI, DetectJailbreak validator | Jailbreaks | 99.4 / 107 | 149 / 325 |
| LLM Guard, nine default input scanners | Injection, PII, secrets, toxicity, gibberish, language, invisible text, token limit, regex | 249 / 316 | 348 / 650 |
| OpenAI omni-moderation (hosted, network included) | Harm categories, not injection | 411 / 548 | 446 / 552 |
| NVIDIA NeMo Guardrails, self-check input rail (gpt-4.1-mini) | One LLM policy check | 871 / 1,288 | 838 / 1,311 |
| AgentFox with the LLM judge inline (gpt-4.1-mini) | All of the default checks, plus injection and PII judged by an LLM | 1,025 / 1,436 | 1,070 / 1,777 |

Source: [`results/summary.json`](results/summary.json); per-call rows are in `results/<system>.csv`.

## Reading it

**Same model size, same speed.**
- **The model:** AgentFox's classifier (PIGuard), the model inside LLM Guard's scanner (ProtectAI deberta-v3-base v2) and Prompt Guard 2 86M are all base-size DeBERTa models. Each takes about 50 ms here.
- **The other ~7 ms:** AgentFox goes over HTTP to a local gateway, which adds about 5 ms. It also runs its PII, secrets and other checks on every call.
- **Why 22M is faster:** Prompt Guard 2 22M is about a quarter the size of the others.

**Long messages.**
- **Reading length:** AgentFox reads the first 4,000 characters in overlapping 256-token windows. LLM Guard and Prompt Guard stop at 512 tokens.
- **The cost:** that is more work per long input, and on CPU 51 of the 150 long inputs exceeded the 300 ms check budget before the classifier finished. Those checks returned without the classifier's result.
- **The gain:** in exchange, an injection placed beyond the first 512 tokens of a long document is read at all.

**With an LLM judge.**
- **The gap to NeMo:** AgentFox takes about 150 ms longer at the median than NeMo's single self-check call.
- **Where it goes:** about 90 ms is the answer. AgentFox's judge returns three scores (injection override, exfiltration, personal data, about 18 output tokens), where NeMo's returns one word. The rest is the default checks AgentFox runs on the same request.

**Hosted APIs.** About 260 ms of the OpenAI moderation figure is the network round trip from Bengaluru to the API. It is in the number because a hosted guard always pays it.

## What is and is not comparable

- **Scope differs.** AgentFox's default layer runs many detectors. LLM Guard's scanner, Prompt Guard and the Guardrails AI validator each detect one class of attack. OpenAI moderation does not look for injection at all; it flagged 0 of its 300 messages.
- **Speed, not accuracy.** This measures speed only. The flag rates in the per-call files only show that each system returned verdicts.
- **AgentFox goes over HTTP.** Its figures include a loopback HTTP round trip to the gateway, which adds about 5 ms. Everything else ran in-process.
- **Threads.** The competitors used PyTorch's default of 6 threads. AgentFox's classifier runs on one batching worker per model.
- **One laptop.** These are numbers from one laptop, not a server.

## Setup

- **Machine:** Apple M1 Pro, 8 cores, 16 GB.
- **CPU only:** `AGENTFOX_MODEL_DEVICE=cpu` for AgentFox; the Mac GPU was disabled for the others.
- **Python:** uv-managed Python 3.12.13 for every system.
- **Library versions:**
  - AgentFox with torch 2.14.1 and transformers 5.21;
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
uv venv --managed-python -p 3.12 /tmp/h2h-af && uv pip install -p /tmp/h2h-af/bin/python ".[pii,classifiers]"
uv venv --managed-python -p 3.12 /tmp/h2h-llmguard && uv pip install -p /tmp/h2h-llmguard/bin/python llm-guard
uv venv --managed-python -p 3.12 /tmp/h2h-nemo && uv pip install -p /tmp/h2h-nemo/bin/python nemoguardrails langchain-openai
uv venv --managed-python -p 3.12 /tmp/h2h-gai && uv pip install -p /tmp/h2h-gai/bin/python guardrails-ai guardrails-ai-detect-jailbreak

AGENTFOX_MODEL_DEVICE=cpu /tmp/h2h-af/bin/python benchmarks/latency/head_to_head/run_agentfox.py agentfox-L2 agentfox-L4-judge-inline
/tmp/h2h-llmguard/bin/python benchmarks/latency/head_to_head/run_local_models.py llmguard-pi llmguard-default pg2-86m pg2-22m
BENCH_SUBSAMPLE=300 /tmp/h2h-nemo/bin/python benchmarks/latency/head_to_head/run_nemo.py
/tmp/h2h-gai/bin/python benchmarks/latency/head_to_head/run_gai.py
BENCH_SUBSAMPLE=300 /tmp/h2h-llmguard/bin/python benchmarks/latency/head_to_head/run_openai_mod.py
```

- **Keys and access:** the LLM-based systems need `OPENAI_API_KEY`. Prompt Guard 2 needs Hugging Face access to Meta's gated models.
- **Output:** each run writes `work/percall/<system>.csv` (set `H2H_WORK` to change where).
- **Messages:** `build_messages.py <maps_dir> <out>` rebuilds the message set from the benchmark's repository maps.

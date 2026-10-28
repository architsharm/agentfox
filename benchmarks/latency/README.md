# Guard latency on 109 real agent repositories

A guard check with the default detectors adds **49.6 ms at the median and 260 ms at p95**. With only the deterministic checks it adds **2.1 ms**.

These are engine times over 41,540 recorded guard calls, replayed from 109 agent repositories on 2026-10-28. The machine was a laptop CPU running Python 3.12, as in the production image. The times exclude the network and the agent's own model.

| Layer | What runs | p50 per check (ms) | p95 per check (ms) | p50 per agent turn (ms) | Checks past the budget |
|---|---|---|---|---|---|
| L1 Deterministic | Pattern, PII, secrets, schema, unicode and code checks | 2.1 | 6.0 | 8.0 | 0% |
| L2 Default, cache off | L1 + ML prompt-injection classifier | 49.6 | 260 | 156 | 4.9% |
| L2 Default, cache on | Same; repeated text served from the score cache | 2.7 | 258 | 58.1 | 4.1% |
| L3 Extended | L2 + similarity search against known attacks | 9.4 | 262 | 73.9 | 5.3% |
| L4 Full | L3 + LLM judges (gpt-4.1-mini) | 68.7 | 949 | 1,017 | 9.5% |

- **Short messages are fast; long ones meet the budget.** Under 200 characters, a default check takes 49.0 ms p50 / 60.3 ms p95, and none runs out of time. Between 200 and 600 characters, it takes 166 ms p50, and 22.3% reach the 300 ms check budget before the classifier finishes. Those checks return without the classifier's verdict and are marked degraded. The p95s above are that budget, on a CPU with no GPU.
- **Tool calls** cost 2.2–2.7 ms at the median in every layer.
- **Session length** does not matter. Latency is flat across the turns of a session.
- **Repository kind and framework** barely matter. Medians are within a few milliseconds of each other.
- **LLM judges** are mostly off the request path. Input checks stay at 64 ms p50 with the judges on, because by default a judge waits inline only when an enforcing rule relies on it. Replies take about 0.85 s, because the commitment check on outputs runs inline.

The headline uses the cache-off numbers. The attack suite repeats text, so the cache-on numbers would flatter us. Against other guards on the same machine, see [`head_to_head/`](head_to_head/README.md).

## Methodology

Each repository was mapped with `agentfox init`. Its own agents, tools and handoffs then drove traffic through a fresh local gateway.

**Repositories.** We examined 119 agent repositories. 109 produced an agent map and were tested; the mapper found no agent in the other 10. [`results/01_repos.csv`](results/01_repos.csv) lists every repository with its URL and commit.

| Source | Repos tested |
|---|---|
| Public GitHub repositories | 76 |
| Held-out public repositories (added after the mapper work, never used to tune it) | 26 |
| Local projects: two demo agents in this repository, one test fixture, four private projects (anonymised) | 7 |
| Total | 109 (8,839 agents, 5,734 tools) |

- **Frameworks, by number of repositories:** LangGraph 42, custom code 19, CrewAI 17, AutoGen 16, OpenAI Agents SDK 16, JavaScript/TypeScript 13, Google ADK 12, Agno 9, Vercel AI SDK 9, Pydantic AI 9, and others.
- **Repository kinds:** 26 single-agent, 42 with independent agents, 41 multi-agent with handoffs.

**Scenarios.** Every call goes through the public guard endpoints, the same way an SDK or the proxy sends it.

1. **Single turn:** user message → tool call → tool result → reply.
2. **Multi-turn:** 5 turns in one session, benign controls first and attacks after, to see whether latency grows with history.
3. **Multi-agent:** user → root agent → handoff → sub-agent tool call → tool result → sub-agent reply → handback → final reply. This runs only for agents the map shows handing off.

**Content.** Messages come from the AgentFox attack suite built for each repository's map. They cover prompt injection, jailbreaks, data leaks and unsafe tool use, plus benign controls, each phrased against that repository's real agents and tools.

Where no agent in a repository has a tool, the suite is written as if each agent had one generic read tool, and the tool steps are left out. Without this, those repositories would replay empty messages.

**Layers.**
- **L1** runs the deterministic detectors.
- **L2** adds the ML prompt-injection classifier. It is measured with the score cache on and off.
- **L3** adds similarity search.
- **L4** adds the LLM judges (OpenAI gpt-4.1-mini) with the default `judgment_inline = "when_relied"`. It ran on a 40-repository subset (622 calls), because every call is a paid model request.

**Setup.**
- **Machine:** Apple M1 Pro, 8 cores, 16 GB, CPU only (`AGENTFOX_MODEL_DEVICE=cpu`).
- **Gateway:** one uvicorn worker on SQLite.
- **Software:** uv-managed Python 3.12.13 with the locked dependencies from `uv.lock`, and production defaults otherwise.
- **Each layer** starts a new gateway with an empty database and is warmed with 5 calls.

**Why the Python build matters.** On a Miniconda build of Python, the same libraries ran the classifier about 45% slower. The production image uses `python:3.12-slim`.

**Metrics.**
- **Engine time** is the gateway's own measured time per check. It excludes the network and the agent's model.
- **Local HTTP round trip** is recorded too.
- **A check is degraded** when a detector timed out or a dependency was unavailable.
- **Percentiles** use linear interpolation.

## By layer and step

Tool calls are the cheapest step in every layer. Text the classifier must read (inputs, tool results, replies) carries the cost. Figures are engine p50 / p95 in ms. Each layer has about 2,889 input and output checks and about 1,980 tool checks; L4 has 176 and 111.

| Step | L1 | L2 cache off | L3 | L4 with judges |
|---|---|---|---|---|
| User input | 1.8 / 2.2 | 49.3 / 67.6 | 9.3 / 64.2 | 64.0 / 78.9 |
| Tool call (arguments) | 2.2 / 2.8 | 2.4 / 2.9 | 2.6 / 3.1 | 2.7 / 3.3 |
| Tool result | 2.2 / 6.0 | 58.9 / 263 | 54.0 / 267 | 98.2 / 268 |
| Agent reply | 2.1 / 6.8 | 52.0 / 268 | 10.7 / 268 | 838 / 1,110 |
| Handoff to a sub-agent | 1.8 / 2.2 | 49.1 / 54.7 | 51.7 / 57.0 | 52.4 / 57.9 |
| Handback to the root agent | 2.6 / 5.5 | 94.0 / 267 | 16.9 / 209 | 26.5 / 52.9 |
| Final reply | 2.9 / 6.9 | 94.6 / 268 | 17.2 / 53.3 | 847 / 971 |
| All steps | 2.1 / 6.0 | 49.6 / 260 | 9.4 / 262 | 68.7 / 949 |

Local HTTP adds about 5 ms to each engine figure. For L1 across all steps the round trip is 6.7 / 10.7 ms.

L3's medians are lower than L2 cache off because L3 runs with the score cache on. Similarity search itself adds about 7 ms over L2 with the cache on.

## Per agent turn

With the default detectors, a full single-agent turn adds 156 ms at the median, and a multi-agent handoff turn adds 476 ms.

A turn's figure is the sum of every guard call it makes: 4 calls for a single turn, 7 for a multi-agent turn. Figures are engine p50 / p95 in ms.

| Scenario | Turns measured | L1 | L2 cache off | L3 | L4 with judges |
|---|---|---|---|---|---|
| Single turn | 1,090 | 8.0 / 16.4 | 156 / 571 | 73.9 / 581 | 1,017 / 1,511 |
| Multi-turn (per turn) | 1,635 | 8.1 / 17.1 | 156 / 584 | 72.0 / 588 | 937 / 1,277 |
| Multi-agent handoff | 164 | 17.2 / 31.7 | 476 / 1,170 | 322 / 908 | 2,007 / 2,266 |

The calls in a turn were sent back to back. An agent that runs some checks in parallel with its model pays less.

## What moves latency, and what does not

Message length is the main driver. Session length, repository kind and framework barely matter. Figures are engine p50 / p95 in ms.

**Session length.** Per-check latency is flat from turn 1 to turn 5, with about 1,092 checks per turn. The p95 rises from turn 3 because the attacks start there, and they are longer messages.

| Turn in session | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| L1 | 2.0 / 2.5 | 2.0 / 2.6 | 2.1 / 6.4 | 2.1 / 6.4 | 2.1 / 6.5 |
| L2 cache off | 49.3 / 62.7 | 49.0 / 60.8 | 49.7 / 265 | 49.9 / 266 | 49.9 / 267 |

**Message size.** The classifier reads text in 256-token windows, so its cost grows with length.

| Content length | Checks | L1 | L2 cache off | Past the budget |
|---|---|---|---|---|
| Under 200 characters | 8,000 | 2.0 / 2.5 | 49.0 / 60.3 | 0% |
| 200–600 characters | 2,220 | 4.5 / 7.0 | 166 / 268 | 22.3% |
| 600–1,500 characters | 8 | 7.7 / 8.4 | 266 / 270 | 62.5% |

**Repository kind.**

| Repository kind | Repos | Checks (L2) | L1 | L2 cache off |
|---|---|---|---|---|
| Single agent | 26 | 1,650 | 1.9 / 3.0 | 49.0 / 145 |
| Independent agents | 42 | 3,500 | 2.1 / 6.0 | 49.5 / 256 |
| Multi-agent with handoffs | 41 | 5,078 | 2.1 / 6.2 | 50.3 / 263 |

**Framework.** This table includes frameworks with at least 4 repositories. Each repository counts once, under the first framework listed for it.

| Framework | Repos | Checks | L2 cache off |
|---|---|---|---|
| LangGraph | 26 | 2,106 | 49.3 / 256 |
| Custom code | 9 | 626 | 49.3 / 171 |
| Agno | 8 | 1,024 | 51.4 / 267 |
| AutoGen | 7 | 840 | 50.9 / 267 |
| CrewAI | 6 | 768 | 51.5 / 267 |
| JavaScript/TypeScript | 6 | 578 | 50.5 / 258 |
| Google ADK | 4 | 484 | 50.4 / 256 |
| OpenAI Agents SDK | 4 | 484 | 49.4 / 255 |

The guard does no framework-specific work per check.

## Concurrency

On CPU, one gateway worker sustains 16.8 default checks per second for a single client. Throughput rises to 50.3 per second at 16 clients, as the classifier batches requests, while each request waits longer. Deterministic checks alone sustain about 139 per second.

Each cell is the median of 3 runs of 200 input checks, drawn from the runnable attack and control messages of 40 repositories. Each check is timed as a local HTTP round trip.

| Layer | Clients | Throughput (checks/s) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| L1 Deterministic | 1 | 94.4 | 6.4 | 10.5 | 11.9 |
| | 4 | 139.2 | 14.1 | 42.7 | 170 |
| | 8 | 138.7 | 20.6 | 224 | 488 |
| | 16 | 115.5 | 25.7 | 644 | 931 |
| L2 Default, cache off | 1 | 16.8 | 54.1 | 60.7 | 64.0 |
| | 4 | 30.1 | 125 | 150 | 164 |
| | 8 | 40.6 | 183 | 266 | 296 |
| | 16 | 50.3 | 283 | 394 | 441 |
| L2 Default, cache on | 1 | 88.2 | 7.1 | 11.2 | 11.8 |
| | 4 | 127.5 | 15.4 | 77.9 | 237 |
| | 8 | 116.4 | 22.7 | 231 | 695 |
| | 16 | 112.1 | 38.9 | 598 | 1,023 |
| L3 Extended (cache on) | 1 | 57.1 | 13.1 | 17.4 | 18.2 |
| | 4 | 75.9 | 47.4 | 59.2 | 112 |
| | 8 | 72.4 | 99.6 | 137 | 238 |
| | 16 | 74.3 | 196 | 321 | 391 |

The cache-on rows repeat messages across runs, so most of their checks are cache hits. Every check also writes its record to the database. This setup (one worker, SQLite, a laptop CPU) is a floor per worker, not a ceiling: production capacity scales with workers, a server database and a GPU.

## Startup and network

A local gateway is healthy in 8.7–11.9 s. Its first check takes 62–122 ms; after that, the figures above apply.

| Layer | Startup to healthy (s) | First check after startup (ms) |
|---|---|---|
| L1 Deterministic | 8.7 | 62 |
| L2 Default | 11.9 | 122 |
| L3 Extended | 10.6 | 118 |
| L4 Full | 10.4 | 121 |

The hosted gateway runs on Vercel in us-east (iad1).
- From Bengaluru, a warm health round trip is 310 ms p50 and 485 ms p95.
- A cold serverless start takes 7.4 s.

Network time is not in the engine figures. For low latency, run the gateway in the agent's region, or self-host it next to the agent.

## Configuration that affects latency

The benchmark ran production defaults. These settings trade latency against coverage.

| Setting | Default | Effect on latency |
|---|---|---|
| Enabled detectors | Deterministic + ML classifier (L2) | L1 alone costs about 2 ms per check. |
| `model_device` | `auto` | Picks a GPU when one is present. Long messages then finish well inside the budget. |
| `classifier_cache_size` | 4,096 | Repeated text is scored once. Set it to 0 to turn the cache off; the L2 cache-off figures are measured that way. |
| `judgment_inline` | `when_relied` | An LLM judge runs before the response only when an enforcing rule relies on it. Otherwise it runs after the response and is still recorded. `always` keeps every judge inline. |
| `judgment_llm_timeout_s` | 4.0 | Upper bound on one judge call. |
| `prompt_injection_classifier_secondary_inline` | false | The secondary injection model runs after the response, once the gateway is idle; `true` makes it inline. |
| `enforcement_budget_ms` / `detector_timeout_ms` | 300 / 40 | Time budget for the pooled detectors on one check, and the cap on any one detector. Deterministic detectors always run in full. |

## Compared with published figures

We also ran LLM Guard, Prompt Guard 2, Guardrails AI, NeMo Guardrails and OpenAI moderation ourselves, on the same messages and machine: see [`head_to_head/`](head_to_head/README.md). On short messages AgentFox's default checks took 58.4 ms at the median there, against 51.1 ms for LLM Guard's prompt-injection scanner.

Few vendors publish latency, and almost none publish the conditions behind it. The fair comparisons are in-process measurements like ours. Hosted APIs add a network round trip, and most vendors report an average rather than a tail. The table below lists figures from pages we opened on 2026-10-27; every one of them is self-reported by its vendor or authors.

| Product | Where it runs | Published latency | Conditions |
|---|---|---|---|
| **AgentFox, default (ML classifier)** | Self-hosted, in-process | **49.6 ms p50 / 260 ms p95** | Laptop CPU, real agent traffic, network excluded; p95 is the 300 ms budget on long text |
| **AgentFox, deterministic** | Self-hosted, in-process | **2.1 ms p50 / 6.0 ms p95** | Same |
| [Protect AI LLM Guard](https://protectai.github.io/llm-guard/input_scanners/prompt_injection/), prompt-injection scanner | Self-hosted, in-process | 104 ms mean / 107 ms p95 (ONNX); 213 ms mean / 296 ms p95 (PyTorch) | AWS m5.xlarge CPU, 384-token input |
| [Meta Llama Prompt Guard 2](https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Prompt-Guard-2/86M/MODEL_CARD.md) | Self-hosted model | 86M: 92.4 ms; 22M: 19.3 ms | A100 GPU, 512 tokens |
| Prompt Guard 2 22M, independent ([arXiv 2603.11875](https://arxiv.org/html/2603.11875)) | Self-hosted model | 49 ms p50 / 324 ms p95 | 524 cases, hardware not named |
| [Lakera Guard](https://docs.lakera.ai/docs/evaluation-overview) | Hosted API | p95 50 ms (~1k chars, 1 detector) to 300 ms (~5k chars, 16 detectors) | Network boundary not stated |
| [Alice (ex-ActiveFence)](https://alice.io/blog/low-latency-ai-guardrails) | Hosted API | 68.7 ms mean / 119 ms p95 | Includes network |
| [NVIDIA NeMo Guardrails](https://developer.nvidia.com/blog/measuring-the-effectiveness-and-performance-of-ai-guardrails-in-generative-ai-applications/) | Self-hosted, GPU microservices | About 0.4–0.5 s added per chat turn | End-to-end with a 70B main model |
| Azure Content Safety, AWS Bedrock Guardrails, OpenAI Moderation ([arXiv 2504.00441](https://arxiv.org/html/2504.00441)) | Hosted APIs | 68–70 ms, 197–203 ms and 259–283 ms mean | One workload, authors from a competitor (Enkrypt AI), network boundary not stated |
| [Palo Alto Prisma AIRS](https://docs.paloaltonetworks.com/prisma-airs/ai-runtime-security/airs-vm-firewall/performance-in-prisma-airs) | Network firewall | About 700 ms added | Firewall intercept mode |

Many products publish no latency at all, including:
- **Hosted APIs:** Azure Prompt Shields, AWS Bedrock Guardrails, Google Model Armor and OpenAI Moderation (no official figures).
- **Open models and frameworks:** Llama Guard 3 and 4, and Guardrails AI.
- **Security vendors:** HiddenLayer, Cisco AI Defense, Prompt Security, Pangea, Straiker and Pillar.

Input length and detector count move every number above. Lakera's p95 triples from about 1k to 5k characters. Read each figure with its conditions.

## Data and reproduction

Every call is recorded, and every table above is generated from the files in [`results/`](results/).

| File | Contents |
|---|---|
| `01_repos.csv` | All 119 repositories: URL, commit, source, kind, frameworks, agents, tools, calls recorded |
| `02_by_layer_and_step.csv` | Percentiles by layer and step, engine and local HTTP |
| `03_by_layer_and_scenario.csv` | Per call and per agent turn, by scenario |
| `04_multi_turn_by_turn_number.csv` | By turn number within a session |
| `05_by_repo_kind.csv` | Single-agent, independent-agent and multi-agent repositories |
| `06_by_repo.csv` | Every repository × layer |
| `07_by_content_size.csv` | By message length |
| `08_startup_and_network.csv` | Startup, first call, production round trip |
| `09_recorded_sessions_all_calls.csv.gz` | All 41,540 calls: session, turn, agent, attack, step, length, times, verdict |
| `10_by_framework_default_cache_off.csv` | By framework |
| `concurrency.json` | Concurrency runs, 3 repeats each |
| `headline.json` | The figures the website quotes, bound in `benchmarks/claims.yaml` |

The four private projects are named `private-app-1` to `private-app-4`, and their URLs are withheld. Their timings are included in full.

To reproduce, run these from the repository root with a uv-managed Python 3.12 environment built from the lock file:

```bash
uv export --frozen --no-hashes --no-emit-project --extra pii --extra classifiers --extra otel --extra postgres --extra sql --extra dev > /tmp/req.txt
uv venv --managed-python -p 3.12 /tmp/af312 && uv pip install -p /tmp/af312/bin/python -r /tmp/req.txt
export AGENTFOX_MODEL_DEVICE=cpu PYTHONPATH=src:.
/tmp/af312/bin/python -m benchmarks.latency.fetch_repos var/latency/repos
/tmp/af312/bin/python -m benchmarks.latency.map_repos var/latency/repos var/latency
/tmp/af312/bin/python -m benchmarks.latency.run_latency var/latency/maps var/latency/run --layers "L1 Deterministic,L2 Default (+ML classifier),L2n Default (cache off),L3 Extended (+similarity)"
/tmp/af312/bin/python -m benchmarks.latency.run_latency var/latency/maps var/latency/run_l4 --layers "L4 Full (+LLM judge)" --single 1 --multi 1 --agents 1 --turns 3 --repos mem0,autogen,crewAI-examples,retrieval-agent-template,openai-cua-sample-app,swarm,open-deep-research,langgraph-example,GenAI-Showcase,hello-agents,smolagents,OpenHands,agent-framework,XAgent,data-enrichment,humanlayer,react-agent,langgraph-supervisor-js,Upsonic,langmem,openai-responses-starter-app,Controllable-RAG-Agent,agno,deer-flow,build-with-ag2,agentops,deep-research,samples,RD-Agent,adk-samples,gemini-fullstack-langgraph-quickstart,adk-python,langroid,ChatDev,langgraphjs,agents-towards-production,python-sdk
/tmp/af312/bin/python -m benchmarks.latency.run_concurrency var/latency/maps var/latency/concurrency
MAP_REPORT=map_report.json python -m benchmarks.latency.report var/latency var/latency/results run,run_l4
```

- **`fetch_repos.py`** clones the public repositories at the commits in `01_repos.csv`.
- **`map_repos.py`** maps them, plus the two demo agents in this repository.
- **`run_latency.py`** starts a fresh gateway per layer and replays the three scenarios.
- **`run_concurrency.py`** runs the concurrency test.
- **`report.py`** writes the CSVs and `headline.json`.

**The L4 layer** needs `OPENAI_API_KEY`. Its subset was 37 public repositories plus `private-app-1` to `private-app-3`. The other layers ran with the defaults: 10 single turns, 3 five-turn sessions and 4 handoff turns per repository. Per-layer call counts differ by a few dozen, because tool-less repositories draw their sessions afresh for each layer.

**Measured code:** AgentFox `main` at commit `12520660`.

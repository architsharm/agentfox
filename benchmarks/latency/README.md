# Guard latency on 109 real agent repositories

A guard check with the default detectors adds **57.4 ms at the median and 302 ms at p95**. With only the deterministic checks it adds **2.3 ms**.

These are engine times over 41,520 recorded guard calls, replayed from 109 agent repositories on 2026-10-28. The machine was a laptop CPU running Python 3.12, as in the production image. The times exclude the network and the agent's own model.

| Layer | What runs | p50 per check (ms) | p95 per check (ms) | p50 per agent turn (ms) | Checks past the budget |
|---|---|---|---|---|---|
| L1 Deterministic | Pattern, PII, secrets, schema, unicode and code checks | 2.3 | 6.4 | 8.8 | 0% |
| L2 Default, cache off | L1 + ML prompt-injection classifier | 57.4 | 302 | 179 | 0.2% |
| L2 Default, cache on | Same; repeated text served from the score cache | 3.0 | 264 | 60.9 | 0% |
| L3 Extended | L2 + similarity search against known attacks | 9.9 | 276 | 77.1 | 0% |
| L4 Full | L3 + LLM judges (gpt-4.1-mini) | 76.5 | 1,009 | 1,086 | 0% |

- **Message length drives the tail.** Under 200 characters, a default check takes 54.5 ms p50 / 83.5 ms p95. Between 200 and 600 characters it takes 188 ms p50 / 374 ms p95, because the classifier has more text to read. Text over 200 characters gets a 1,000 ms check budget instead of 300 ms (`long_text_chars`, `long_text_budget_ms`). So these checks finish with the classifier's verdict, where 22% of them used to run out of time on a CPU.
- **Tool calls** cost 2.6–3.1 ms at the median in every layer.
- **Session length** does not matter. Latency is flat across the turns of a session.
- **Repository kind and framework** barely matter. Medians are within a few milliseconds of each other.
- **LLM judges** are mostly off the request path. Input checks stay at 66 ms p50 with the judges on, because by default a judge waits inline only when an enforcing rule relies on it. Replies take about 0.88 s, because the commitment check on outputs runs inline.

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

Tool calls are the cheapest step in every layer. Text the classifier must read (inputs, tool results, replies) carries the cost. Figures are engine p50 / p95 in ms. Each layer has about 2,889 input and output checks and about 1,977 tool checks; L4 has 176 and 111.

| Step | L1 | L2 cache off | L3 | L4 with judges |
|---|---|---|---|---|
| User input | 2.0 / 2.4 | 56.0 / 80.7 | 9.9 / 59.9 | 65.9 / 147 |
| Tool call (arguments) | 2.6 / 3.2 | 3.1 / 4.6 | 2.8 / 3.5 | 2.9 / 4.3 |
| Tool result | 2.3 / 6.3 | 72.3 / 331 | 55.4 / 300 | 105 / 309 |
| Agent reply | 2.3 / 7.2 | 64.0 / 331 | 11.0 / 313 | 878 / 1,146 |
| Handoff to a sub-agent | 2.0 / 2.4 | 56.3 / 81.6 | 53.6 / 60.9 | 52.4 / 57.2 |
| Handback to the root agent | 2.6 / 6.0 | 108 / 373 | 18.1 / 53.3 | 37.6 / 59.3 |
| Final reply | 3.0 / 7.3 | 108 / 392 | 17.8 / 54.1 | 870 / 1,062 |
| All steps | 2.3 / 6.4 | 57.4 / 302 | 9.9 / 276 | 76.5 / 1,009 |

Local HTTP adds about 5 ms to each engine figure. For L1 across all steps the round trip is 7.3 / 11.9 ms.

L3's medians are lower than L2 cache off because L3 runs with the score cache on. Similarity search itself adds about 7 ms over L2 with the cache on.

## Per agent turn

With the default detectors, a full single-agent turn adds 179 ms at the median, and a multi-agent handoff turn adds 564 ms.

A turn's figure is the sum of every guard call it makes: 4 calls for a single turn, 7 for a multi-agent turn. Figures are engine p50 / p95 in ms.

| Scenario | Turns measured | L1 | L2 cache off | L3 | L4 with judges |
|---|---|---|---|---|---|
| Single turn | 1,090 | 8.8 / 17.6 | 179 / 687 | 77.1 / 639 | 1,086 / 1,626 |
| Multi-turn (per turn) | 1,635 | 8.8 / 18.1 | 180 / 710 | 73.2 / 654 | 1,013 / 1,361 |
| Multi-agent handoff | 164 | 18.1 / 33.9 | 564 / 1,592 | 330 / 830 | 2,170 / 2,310 |

The calls in a turn were sent back to back. An agent that runs some checks in parallel with its model pays less.

## What moves latency, and what does not

Message length is the main driver. Session length, repository kind and framework barely matter. Figures are engine p50 / p95 in ms.

**Session length.** Per-check latency is flat from turn 1 to turn 5, with about 1,092 checks per turn. The p95 rises from turn 3 because the attacks start there, and they are longer messages.

| Turn in session | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| L1 | 2.1 / 2.8 | 2.1 / 2.8 | 2.4 / 6.8 | 2.5 / 6.9 | 2.4 / 6.8 |
| L2 cache off | 55.4 / 81.0 | 55.1 / 78.4 | 58.7 / 328 | 58.7 / 322 | 58.9 / 323 |

**Message size.** The classifier reads text in 256-token windows, so its cost grows with length.

| Content length | Checks | L1 | L2 cache off | Past the budget |
|---|---|---|---|---|
| Under 200 characters | 7,987 | 2.1 / 2.9 | 54.5 / 83.5 | 0.3% |
| 200–600 characters | 2,229 | 4.6 / 7.4 | 188 / 374 | 0% |
| 600–1,500 characters | 8 | 7.9 / 9.5 | 375 / 489 | 0% |

**Repository kind.**

| Repository kind | Repos | Checks (L2) | L1 | L2 cache off |
|---|---|---|---|---|
| Single agent | 26 | 1,650 | 2.0 / 3.3 | 57.2 / 162 |
| Independent agents | 42 | 3,500 | 2.3 / 6.2 | 56.8 / 296 |
| Multi-agent with handoffs | 41 | 5,074 | 2.4 / 6.6 | 57.8 / 316 |

**Framework.** This table includes frameworks with at least 4 repositories. Each repository counts once, under the first framework listed for it.

| Framework | Repos | Checks | L2 cache off |
|---|---|---|---|
| LangGraph | 26 | 2,102 | 58.5 / 293 |
| Custom code | 9 | 626 | 55.1 / 287 |
| Agno | 8 | 1,024 | 57.2 / 316 |
| AutoGen | 7 | 840 | 59.1 / 329 |
| CrewAI | 6 | 768 | 63.2 / 381 |
| JavaScript/TypeScript | 6 | 578 | 57.2 / 299 |
| Google ADK | 4 | 484 | 55.3 / 302 |
| OpenAI Agents SDK | 4 | 484 | 57.7 / 307 |

The guard does no framework-specific work per check.

## Concurrency

On CPU, one gateway worker sustains 14.6 default checks per second for a single client. Throughput rises to 49.2 per second at 16 clients, as the classifier batches requests, while each request waits longer. Deterministic checks alone sustain about 140 per second.

Each cell is the median of 3 runs of 200 input checks, drawn from the runnable attack and control messages of 40 repositories. Each check is timed as a local HTTP round trip.

| Layer | Clients | Throughput (checks/s) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| L1 Deterministic | 1 | 96.5 | 6.1 | 9.2 | 11.1 |
| | 4 | 145.5 | 13.6 | 55.2 | 165 |
| | 8 | 137.4 | 16.3 | 208 | 570 |
| | 16 | 121.5 | 34.5 | 574 | 1,082 |
| L2 Default, cache off | 1 | 14.6 | 60.4 | 83.4 | 114 |
| | 4 | 28.1 | 135 | 160 | 170 |
| | 8 | 39.7 | 192 | 249 | 300 |
| | 16 | 49.2 | 285 | 442 | 633 |
| L2 Default, cache on | 1 | 89.2 | 6.9 | 11.1 | 12.7 |
| | 4 | 130.5 | 10.8 | 76.6 | 368 |
| | 8 | 125.9 | 17.7 | 212 | 734 |
| | 16 | 101.0 | 43.1 | 583 | 1,127 |
| L3 Extended (cache on) | 1 | 50.2 | 15.3 | 19.9 | 22.8 |
| | 4 | 67.9 | 54.0 | 70.1 | 76.7 |
| | 8 | 65.7 | 113 | 136 | 147 |
| | 16 | 59.8 | 226 | 410 | 792 |

The cache-on rows repeat messages across runs, so most of their checks are cache hits. Every check also writes its record to the database. This setup (one worker, SQLite, a laptop CPU) is a floor per worker, not a ceiling: production capacity scales with workers, a server database and a GPU.

## Startup and network

A local gateway is healthy in 10.8–16.2 s. Its first check takes 78–133 ms; after that, the figures above apply.

| Layer | Startup to healthy (s) | First check after startup (ms) |
|---|---|---|
| L1 Deterministic | 10.8 | 78 |
| L2 Default | 16.2 | 133 |
| L3 Extended | 11.3 | 123 |
| L4 Full | 11.4 | 127 |

The hosted gateway runs on Vercel in us-east (iad1).
- From Bengaluru, a warm health round trip is 310 ms p50 and 485 ms p95.
- A cold serverless start takes 7.4 s.

Network time is not in the engine figures. For low latency, run the gateway in the agent's region, or self-host it next to the agent.

## Configuration that affects latency

The benchmark ran production defaults. These settings trade latency against coverage.

| Setting | Default | Effect on latency |
|---|---|---|
| Enabled detectors | Deterministic + ML classifier (L2) | L1 alone costs about 2 ms per check. |
| `model_device` | `auto` | Picks a GPU when one is present, which reads long text far faster. |
| `long_text_chars` / `long_text_budget_ms` | 200 / 1,000 | Past 200 characters, the classifier's check may take up to 1,000 ms, so it finishes reading long text instead of returning without a verdict. |
| `classifier_cache_size` | 4,096 | Repeated text is scored once. Set it to 0 to turn the cache off; the L2 cache-off figures are measured that way. |
| `judgment_inline` | `when_relied` | An LLM judge runs before the response only when an enforcing rule relies on it. Otherwise it runs after the response and is still recorded. `always` keeps every judge inline. |
| `judgment_llm_timeout_s` | 4.0 | Upper bound on one judge call. |
| `prompt_injection_classifier_secondary_inline` | false | The secondary injection model runs after the response, once the gateway is idle; `true` makes it inline. |
| `enforcement_budget_ms` / `detector_timeout_ms` | 300 / 40 | Time budget for the pooled detectors on one check of short text, and the cap on any one detector. Deterministic detectors always run in full. |

## Compared with published figures

We also ran LLM Guard, Prompt Guard 2, Guardrails AI, NeMo Guardrails and OpenAI moderation ourselves, on the same messages and machine: see [`head_to_head/`](head_to_head/README.md). On short messages AgentFox's default checks took 63.1 ms at the median there, against 56.1 ms for LLM Guard's prompt-injection scanner, and its deterministic checks alone 7.4 ms.

Few vendors publish latency, and almost none publish the conditions behind it. The fair comparisons are in-process measurements like ours. Hosted APIs add a network round trip, and most vendors report an average rather than a tail. The table below lists figures from pages we opened on 2026-10-27; every one of them is self-reported by its vendor or authors.

| Product | Where it runs | Published latency | Conditions |
|---|---|---|---|
| **AgentFox, default (ML classifier)** | Self-hosted, in-process | **57.4 ms p50 / 302 ms p95** | Laptop CPU, real agent traffic, network excluded |
| **AgentFox, deterministic** | Self-hosted, in-process | **2.3 ms p50 / 6.4 ms p95** | Same |
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
| `09_recorded_sessions_all_calls.csv.gz` | All 41,520 calls: session, turn, agent, attack, step, length, times, verdict |
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

**Measured code:** AgentFox `main` at commit `1445dc4b`.

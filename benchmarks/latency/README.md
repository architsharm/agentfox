# Guard latency on 109 real agent repositories

A guard check with the default detectors adds **37 ms at the median and 181 ms at p95**. With only the deterministic checks it adds **2 ms**.
These are engine times over 40,334 recorded guard calls replayed from 109 open agent repositories, measured on 2026-10-27. They exclude network time and the agent's own model.

| Layer | What runs | p50 per check (ms) | p95 per check (ms) | p50 per agent turn (ms) | Degraded checks |
|---|---|---|---|---|---|
| L1 Deterministic | Pattern, PII, secrets, schema, unicode and code checks | 2.0 | 6.0 | 8 | 0% |
| L2 Default, cache off | L1 + ML prompt-injection classifier | 37.3 | 181 | 141 | 0.2% |
| L2 Default, cache on | Same; repeated text served from the score cache | 3.4 | 170 | 72 | 0.1% |
| L3 Extended | L2 + similarity search against known attacks | 15.2 | 197 | 106 | 0.5% |
| L4 Full | L3 + LLM judge (gpt-4.1-mini) | 79.7 | 1,196 | 1,252 | 2.4% |

- **Tool calls:** checking a tool call costs 3–4 ms in every layer.
- **Session length:** latency is flat across the turns of a session; it does not grow with history.
- **Repo kind:** single-agent, independent-agent and multi-agent repos are within a few ms of each other per check.
- **LLM judge:** input checks stay at 57 ms p50 with the judge on. Replies take about 1.0 s, because the commitment check on outputs runs inline.

The headline uses the cache-off numbers. The attack suite repeats text, so the cache-on numbers would flatter us.

## Methodology

Each repository was mapped with `agentfox init`. Its own agents, tools and handoffs then drove traffic through a fresh local gateway.

**Repositories.** We examined 119 agent repositories. 109 produced an agent map and were tested; the mapper found no agent in the other 10. [`results/01_repos.csv`](results/01_repos.csv) lists every repository with its URL and commit.

| Source | Repos tested |
|---|---|
| Public GitHub repositories | 76 |
| Held-out public repositories (added after the mapper work, never used to tune it) | 26 |
| Local projects: two demo agents in this repository, one test fixture, four private projects (anonymised) | 7 |
| Total | 109 (8,839 agents, 5,634 tools) |

- **Frameworks, by number of repositories:** LangGraph 42, custom code 19, CrewAI 17, AutoGen 16, OpenAI Agents SDK 16, JavaScript/TypeScript 13, Google ADK 12, Agno 9, Vercel AI SDK 9, Pydantic AI 9, and others.
- **Repository kinds:** 26 single-agent, 42 with independent agents, and 41 multi-agent with handoffs.

**Scenarios.** Every call goes through the public guard endpoints, the same way an SDK or the proxy sends it.

1. **Single turn:** user message → tool call → tool result → reply.
2. **Multi-turn:** 5 turns in one session, benign controls first and attacks after, to see whether latency grows with history.
3. **Multi-agent:** user → root agent → handoff → sub-agent tool call → tool result → sub-agent reply → handback → final reply. This runs only for agents the map shows handing off.

**Content.** Messages come from the AgentFox attack suite built for each repository's map. It covers prompt injection, jailbreaks, data leaks and unsafe tool use, plus benign controls. Each message is phrased against that repository's real agents and tools.

**Layers.**
- **L1** runs the deterministic detectors.
- **L2** adds the ML prompt-injection classifier and is measured with the score cache on and off.
- **L3** adds similarity search.
- **L4** adds the LLM judge (OpenAI gpt-4.1-mini). It ran on a 40-repo subset (622 calls), because every call is a paid model request.

**Setup.**
- Machine: Apple M1 Pro, 8 cores, 16 GB. The ML models ran on its built-in GPU (Metal), which the default `model_device = "auto"` picks on a Mac.
- Gateway: one uvicorn worker on SQLite, with production defaults otherwise.
- Each layer starts a new gateway with an empty database and is warmed with 5 calls.

**Metrics.**
- **Engine time** is the gateway's own measured time per check. It excludes the network and the agent's model.
- **Local HTTP round trip** is recorded too.
- A check is **degraded** when a detector timed out or a dependency was unavailable.
- Percentiles use linear interpolation.

## By layer and step

Tool calls are the cheapest step in every layer. Text the classifier must read (inputs, tool results, replies) carries the cost.

Figures are engine p50 / p95 in ms. Each layer has 2,741 input and output checks and 1,977 tool checks; L4 has 176 and 111.

| Step | L1 | L2 cache off | L3 | L4 with judge |
|---|---|---|---|---|
| User input | 1.7 / 2.1 | 32 / 79 | 21 / 83 | 57 / 123 |
| Tool call (arguments) | 2.2 / 2.8 | 3.0 / 4.4 | 3.0 / 4.4 | 3.5 / 12.5 |
| Tool result | 2.2 / 5.8 | 55 / 195 | 58 / 218 | 93 / 261 |
| Agent reply | 2.0 / 6.8 | 42 / 197 | 17 / 222 | 1,021 / 1,410 |
| Handoff to a sub-agent | 1.7 / 2.1 | 50 / 67 | 56 / 79 | 60 / 82 |
| Handback to the root agent | 2.6 / 5.5 | 90 / 202 | 21 / 64 | 41 / 85 |
| Final reply | 3.0 / 7.0 | 91 / 196 | 23 / 62 | 998 / 1,238 |
| All steps | 2.0 / 6.0 | 37 / 181 | 15 / 197 | 80 / 1,196 |

Local HTTP adds about 5–8 ms to each engine figure; for L1 across all steps it is 6.7 / 10.8 ms.

L3's medians are lower than L2 cache off because L3 runs with the score cache on. Similarity search itself adds about 10–20 ms.

## Per agent turn

With the default detectors, a full agent turn adds 141 ms at the median for a single agent and 422 ms for a multi-agent handoff turn.

A turn's figure is the sum of every guard call it makes: 4 calls for a single turn, 7 for a multi-agent turn. Figures are engine p50 / p95 in ms.

| Scenario | Turns measured | L1 | L2 cache off | L3 | L4 with judge |
|---|---|---|---|---|---|
| Single turn | 942 | 8 / 16 | 141 / 424 | 106 / 471 | 1,252 / 1,498 |
| Multi-turn (per turn) | 1,635 | 8 / 17 | 117 / 438 | 66 / 487 | 1,152 / 1,574 |
| Multi-agent handoff | 164 | 17 / 31 | 422 / 887 | 312 / 676 | 2,325 / 2,662 |

The calls in a turn were sent back to back. An agent that runs some checks in parallel with its model pays less.

## What moves latency, and what does not

Message length is the main driver. Session length, repository kind and framework barely matter. Figures are engine p50 / p95 in ms.

**Session length.** Per-check latency is flat from turn 1 to turn 5, with 1,092 checks per turn. The p95 rises from turn 3 because that is where the attacks start, and they are longer messages.

| Turn in session | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| L1 | 1.9 / 2.5 | 1.9 / 2.5 | 2.1 / 6.3 | 2.1 / 6.4 | 2.1 / 6.3 |
| L2 cache off | 36 / 71 | 32 / 57 | 39 / 194 | 36 / 197 | 37 / 190 |

**Message size.** The classifier reads text in 256-token windows, so its cost grows with length.

| Content length | Checks | L1 | L2 cache off |
|---|---|---|---|
| Under 200 characters | 7,741 | 1.9 / 2.5 | 32 / 70 |
| 200–600 characters | 2,169 | 4.8 / 7.0 | 124 / 213 |
| 600–1,500 characters | 18 | 3.6 / 8.5 | 90 / 243 |

**Repository kind.**

| Repository kind | Repos | Checks | L1 | L2 cache off |
|---|---|---|---|---|
| Single agent | 26 | 1,384 | 1.8 / 4.7 | 33 / 95 |
| Independent agents | 42 | 3,470 | 2.0 / 5.7 | 36 / 172 |
| Multi-agent with handoffs | 41 | 5,074 | 2.1 / 6.3 | 40 / 187 |

**Framework.** This table includes frameworks with at least 4 repositories. Each repository counts once, under the first framework listed for it.

| Framework | Repos | Checks | L2 cache off |
|---|---|---|---|
| LangGraph | 26 | 1,954 | 36 / 172 |
| Custom code | 9 | 610 | 36 / 135 |
| Agno | 8 | 1,024 | 46 / 196 |
| AutoGen | 7 | 840 | 44 / 192 |
| CrewAI | 6 | 768 | 42 / 189 |
| JavaScript/TypeScript | 6 | 564 | 40 / 194 |
| Google ADK | 4 | 484 | 35 / 180 |
| OpenAI Agents SDK | 4 | 484 | 43 / 178 |

The guard does no framework-specific work per check. The differences between frameworks follow the message lengths in each repository's traffic.

## Concurrency

One gateway worker sustains about 40–47 input checks per second, with the peak at 4 concurrent clients. Beyond that, requests queue: at 16 clients the default layer's p95 reaches 442 ms with the cache off.

Each cell is the median of 3 runs of 200 input checks, drawn from the attack suites of 40 repositories. Each check is timed as a local HTTP round trip.

| Layer | Clients | Throughput (checks/s) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| L1 Deterministic | 1 | 43.8 | 7.6 | 9.9 | 41 |
| | 4 | 45.3 | 8.9 | 32 | 57 |
| | 8 | 22.5 | 28.5 | 82 | 127 |
| | 16 | 17.7 | 23.3 | 214 | 315 |
| L2 Default, cache on | 1 | 39.6 | 8.1 | 15.6 | 45 |
| | 4 | 42.2 | 8.9 | 35 | 66 |
| | 8 | 17.2 | 25.4 | 79 | 120 |
| | 16 | 19.9 | 25.0 | 265 | 395 |
| L2 Default, cache off | 1 | 31.0 | 8.7 | 41.8 | 71 |
| | 4 | 39.7 | 11.0 | 129 | 170 |
| | 8 | 25.6 | 35.9 | 239 | 366 |
| | 16 | 24.9 | 74.3 | 442 | 550 |
| L3 Extended | 1 | 36.1 | 9.0 | 22.1 | 48 |
| | 4 | 47.2 | 15.6 | 66 | 108 |
| | 8 | 20.2 | 31.8 | 135 | 179 |
| | 16 | 20.1 | 46.7 | 260 | 477 |

Every check writes its record to the database, so this setup (one worker, SQLite, a laptop) caps throughput. Production capacity scales with the number of workers and with a server database. Read these figures as a floor per worker, not a ceiling.

## Startup and network

A local gateway is healthy in 4.5–9.6 s. Its first check takes 57–258 ms; after that, the figures above apply.

| Layer | Startup to healthy (s) | First check after startup (ms) |
|---|---|---|
| L1 Deterministic | 4.5 | 57 |
| L2 Default | 9.0 | 141 |
| L3 Extended | 9.6 | 160 |
| L4 Full | 9.4 | 258 |

The hosted gateway runs on Vercel in us-east (iad1).
- From Bengaluru, a warm health round trip is 310 ms p50 and 485 ms p95.
- A cold serverless start takes 7.4 s.

Network time is not in the engine figures. For low latency, run the gateway in the agent's region, or self-host it next to the agent.

## Configuration that affects latency

The benchmark ran production defaults. These settings trade latency against coverage.

| Setting | Default | Effect on latency |
|---|---|---|
| Enabled detectors | Deterministic + ML classifier (L2) | L1 alone costs about 2 ms per check. Adding similarity search (L3) adds about 10–20 ms. |
| `classifier_cache_size` | 4,096 | Repeated text is scored once. Set it to 0 to turn the cache off; the L2 cache-off figures are measured that way. |
| `judgment_inline` | `when_relied` | An LLM judge runs before the response only when an enforcing rule relies on it. Otherwise it runs after the response and is still recorded. `always` keeps every judge inline. |
| `judgment_llm_timeout_s` | 4.0 | Upper bound on one judge call. |
| `prompt_injection_classifier_secondary_inline` | false | The secondary injection model runs after the response; `true` makes it inline. |
| `enforcement_budget_ms` / `detector_timeout_ms` | 300 / 40 | Time budget for the pooled detectors on one check, and the cap on any one detector. Deterministic detectors always run in full. |

## Compared with published figures

Few vendors publish latency, and almost none publish the conditions behind it. The fair comparisons are in-process measurements like ours. Hosted APIs add a network round trip, and most vendors report an average rather than a tail. The table below lists figures from pages we opened on 2026-10-27; every one of them is self-reported by its vendor or authors.

| Product | Where it runs | Published latency | Conditions |
|---|---|---|---|
| **AgentFox, default (ML classifier)** | Self-hosted, in-process | **37 ms p50 / 181 ms p95** | M1 Pro, models on its built-in GPU, real agent traffic, network excluded |
| **AgentFox, deterministic** | Self-hosted, in-process | **2 ms p50 / 6 ms p95** | Same |
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
| `09_recorded_sessions_all_calls.csv.gz` | All 40,334 calls: session, turn, agent, attack, step, length, times, verdict |
| `10_by_framework_default_cache_off.csv` | By framework |
| `concurrency.json` | Concurrency runs, 3 repeats each |

The four private projects are named `private-app-1` to `private-app-4`, and their URLs are withheld. Their timings are included in full.

To reproduce, run these from the repository root:

```bash
python -m benchmarks.latency.fetch_repos var/latency/repos
python -m benchmarks.latency.map_repos var/latency/repos var/latency
python -m benchmarks.latency.run_latency var/latency/maps var/latency/run --layers "L1 Deterministic,L2 Default (+ML classifier),L2n Default (cache off),L3 Extended (+similarity)"
python -m benchmarks.latency.run_latency var/latency/maps var/latency/run_l4 --layers "L4 Full (+LLM judge)" --single 1 --multi 1 --agents 1 --turns 3 --repos mem0,autogen,crewAI-examples,retrieval-agent-template,openai-cua-sample-app,swarm,open-deep-research,langgraph-example,GenAI-Showcase,hello-agents,smolagents,OpenHands,agent-framework,XAgent,data-enrichment,humanlayer,react-agent,langgraph-supervisor-js,Upsonic,langmem,openai-responses-starter-app,Controllable-RAG-Agent,agno,deer-flow,build-with-ag2,agentops,deep-research,samples,RD-Agent,adk-samples,gemini-fullstack-langgraph-quickstart,adk-python,langroid,ChatDev,langgraphjs,agents-towards-production,python-sdk
python -m benchmarks.latency.run_concurrency var/latency/maps var/latency/concurrency
MAP_REPORT=map_report.json python -m benchmarks.latency.report var/latency var/latency/results run,run_l4
```

- **`fetch_repos.py`** clones the public repositories at the commits in `01_repos.csv`.
- **`map_repos.py`** maps them, plus the two demo agents in this repository.
- **`run_latency.py`** starts a fresh gateway per layer and replays the three scenarios.
- **`run_concurrency.py`** runs the concurrency test.
- **`report.py`** writes the CSVs.

The L4 layer needs `OPENAI_API_KEY`. Its subset was these 37 public repositories plus `private-app-1` to `private-app-3`. The other layers ran with the defaults: 10 single turns, 3 five-turn sessions and 4 handoff turns per repository.

**Measured code:** AgentFox `main` at commit `6a082b77`.

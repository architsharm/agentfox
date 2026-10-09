# Architectural Differentiation

**Date: 2026-10-06. Competitor sources accessed 2026-10-06.** This is the sales-pitch document
for a founder or AE who needs to say "we win here because our architecture has X, which is why we
measure Y on Z." It is written to survive a hostile technical buyer, so every sentence is meant to
be checkable:

- **Our numbers.** Every one comes from a committed results file. Where it is bound in
  [`benchmarks/claims.yaml`](../../benchmarks/claims.yaml), the claim id is given, and
  `scripts/check/claims.py --check` fails if this page drifts from the source.
- **Competitor facts.** Each is labelled by where it came from:
  - **[code]**: a permalink into the vendor's open-source repository at a pinned commit.
  - **[docs]**: the vendor's own API or developer documentation.
  - **[vendor page]**: a vendor product or press page. These are primary sources but not technical documentation, so they are weaker.
  - **[ND]**: not publicly documented. It means we could not find the fact, not that the capability is absent.

Read with [competitor-analysis.md](competitor-analysis.md) (market camps, who wins where) and
[evidence-standards.md](../evaluation/evidence-standards.md) (what each kind of number can and
cannot establish). Where this page and competitor-analysis.md disagree, this page is the newer
read, and §5 says where it narrows an older claim.

---

## 1. Thesis

Most of the field decides on **text**:

- A classifier or policy reads a prompt, a response, or a tool payload flattened to a string, and returns flagged or not flagged.
- Some products wrap that classifier in a gateway, a hook or a platform webhook.

AgentFox decides on the **action**. It sits on the agent's tool call, in-process or as a gateway, and checks three things before the call runs:

- whether this agent was granted this tool, with these argument values;
- what the tool's declared blast radius is;
- **where each argument's value came from**.

None of those inputs is read from the attacker's text, so containment holds when every detector misses. We measure it that way:

- With all detectors switched off: 8/8 attacks contained with zero detector signal (`containment.attacks_contained_with_detectors_off`).
- On AgentDojo: 588/588 attack pairs contained with session-level taint (`agentdojo.session_taint.attack_pairs_contained`).
- The cost is benign utility, and we publish it next to the result: 24/97 benign tasks (24.7% [17.2, 34.2]) run without escalating to a human (`agentdojo.session_taint.benign_tasks_allowed`).

**The single structural reason we win:** a text classifier is defeated when the attacker rewrites the text, and our own adaptive attacker does exactly that. That attacker still cannot change where a value came from or what the tool is declared to do.

---

## 2. Architectural primitives

**How to read the "Who else has it" column.**

- "Has it" means a primary source shows the mechanism.
- "Adjacent" means a related but different mechanism.
- "No [code]" means we read the code and found no such mechanism.
- Unmarked "no" means the API contract we read has no input for it.

Citations are in §4.

| Primitive | What it is, and the design decision | Who else has it | What it moves (claim id or results file) |
|---|---|---|---|
| **Argument provenance and containment at the action** | Every argument carries a provenance mark on a fixed order: `none < user < retrieved < tool_result < subagent < memory` (`detection/taint.py`, `detection/base.py:TAINT_ORDER`). It is inferred by matching argument values against earlier tool outputs, or declared by the caller. A grant carries a ceiling (`max_taint`), and the tool's declared impact tier caps what tainted values may reach. **Decision:** the action check never reads the payload text. | **Adjacent:** <br>- Zenity Boundaries: deterministic, conversation-scoped taint facts that later `forbid` rules read [code]. <br>- Invariant: `->` flow rules over trace order [code]. <br>- Pillar: claims "taint analysis", mechanism [ND]. <br>**No per-argument-value provenance found** in llm-guard, NeMo, Guardrails AI, LlamaFirewall [code], or in the Lakera, Azure, Bedrock, Model Armor, Prompt Security or F5 API contracts [docs]. | 8/8 attacks contained with zero detector signal; 4/4 legitimate calls still allowed (`containment.*`). <br>588/588 attack pairs contained with session-level taint (`agentdojo.session_taint.attack_pairs_contained`). <br>38/38 of those bypasses still contained at the action (`adaptive.bypasses_contained_at_the_action`). |
| **Capability grants with constraints** | Default deny. A grant names one identity, one tool, and argument limits (`eq`, `lte`, `in` … in `policy/model.py:COMPARATORS`), checked in `identity/service.py:check_capability`. **Decision:** a denial is set directly, whatever mode the policy packs are in. | **Has it:** <br>- Zenity Boundaries (rules over `resource.attributes.arguments`) [code]. <br>- Invariant (argument-value rules) [docs]. <br>- NeMo (tool allow-list plus JSON-schema validation) [code]. <br>- Lakera ("Tool Allow/Deny List"; argument scope [ND]). <br>- ServiceNow AI Gateway (tool-level approve or reject) [docs]. | Excessive-agency tier: 5/6 correct (the miss is a benign `tickets.update` held for approval by the cascade rule; the tier counts an escalation as an intervention), where llm-guard "cannot participate" (`benchmarks/agent_security/results/tier_d_results.json`). <br>With grants and impact tiers only and no provenance, the AgentDojo result is 0/588 attack pairs contained (`agentdojo.capability_only`). We publish that grants alone are not enough. |
| **Deterministic action semantics** | Generated SQL is parsed to an AST with sqlglot. We reason over the tree: unbounded DML, tautology `WHERE`, DDL, stacked statements (`detection/actions.py`). Every string argument also goes through `analyse_scope`. **Decision:** "deterministic parsing, never a model". An unparseable statement fails closed. | **Adjacent:** <br>- NeMo ships YARA rules including `sqli` [code]. <br>- LlamaFirewall CodeShield runs regex and Semgrep over generated code [code]. <br>No statement-level SQL blast-radius analysis found elsewhere. | gretelai SQL held-out split: 8/8 natural DML, 12/12 natural DDL, and 357/357 each of the adversarial unbounded and tautology sets, with zero false positives (`benchmarks/action_safety/results/summary.json`). <br>Tool-parameter tier: 8/10, all 5 attacks blocked; the 2 misses are benign `tickets.update` controls held for approval by the cascade rule, which the tier counts as an intervention (`tier_c_results.json`). |
| **Answerability gate before generation** | `_answerability_gate` in `runtime/enforcement/completion.py` refuses a question outside the agent's declared knowledge boundary *before* the provider is called. **Decision:** abstention is a gate, not a score after the fact. | **Post-generation only:** <br>- Bedrock contextual grounding scores the response, output only [docs]. <br>- Automated Reasoning is detect-only, after generation [docs]. <br>No pre-generation gate found. | The deterministic classifier abstains on 57/676 contested questions; with a judgment tier that becomes 572/676 (`judgment.contested_recall_off`, `judgment.contested_recall_on`). The off number is weak; see §5. |
| **Normalised views for detection** | Detectors run over several *views* of the text: zero-width characters stripped, separators rejoined, decoded, hidden HTML. Offsets map back to the original (`detection/normalize.py`). **Decision:** many views, not one aggressive rewrite, because over-blocking gets a guardrail switched off. | **Has it:** <br>- llm-guard (`invisible_text` scanner) [code]. <br>- LlamaFirewall (hidden-ASCII scanner) [code]. <br>Common practice, not a differentiator. | NotInject false positives cut 8.6% → 0.3% by the fixes the adaptive benchmark found (`benchmarks/adaptive/README.md`). <br>19/19 matched pairs across languages (`multilingual.integrity_parity`). |
| **Judgment tiers with egress control** | Optional model tiers (Jev, hosted LLM, local LLM) behind a routing table that forbids them from deciding parse-tree questions (`detection/judgment/capability.py`, `STRUCTURAL_PARSED`). Hosted calls need `allow_egress`, are redacted first, and fail closed if redaction cannot run (`detection/judgment/egress.py`). **Decision:** a model may add recall but may never overrule the parser. | **Model on the deterministic question:** <br>- NeMo sends tool name and arguments to an LLM judge [code]. <br>- LlamaFirewall AlignmentCheck is an LLM judge over the trace [code]. <br>No routing table forbidding a model from overruling a parser found. | 160/165 injection payloads that defeated our pattern detectors caught with a tier on (`judgment.escaped_payloads_caught`). <br>SQL blast-radius accuracy stays at 100.0% with every tier enabled (`judgment.sql_control_unchanged`). |
| **Explicit fail modes** | `Settings.fail_mode` defaults to **open**. A long degradation converts to closed. `NEVER_OPEN` controls cannot be configured open: tenant isolation, entitlement filter, data-access scope, audit chain (`runtime/availability.py`). **Decision:** a disclosure failure is not an outage. | **Mixed across the field.** <br>Fail open: Copilot Studio webhook default [docs], Model Armor on Vertex [docs], Lasso gateway [code], Pillar via LiteLLM [code], Noma hook client [code]. <br>Fail closed: NeMo IORails [code], Invariant Gateway on the MCP path [code]. | No benchmark; this is a design property. Grants, provenance and impact tiers are in-process and deterministic, so a detector timeout does not open them. |
| **Hash-chained audit** | Every decision and operator action is appended to a SHA-256 chain with HMAC checkpoints (`prove/audit/chain.py`). Evidence packages ship a stdlib-only `verify_chain.py`. **Decision:** an auditor verifies without trusting us. | **Has it:** <br>- AWS CloudTrail log-file integrity validation (SHA-256, RSA-signed digests) covers Bedrock guardrail events [docs]. <br>- ServiceNow AI Gateway claims "tamper-evident audit logs", mechanism [ND]. <br>No hash chain or signing found in llm-guard, NeMo, Guardrails AI, LlamaFirewall, Zenity OpenClaw, Lasso or Invariant Gateway [code]. | Verified adversarially, not benchmarked: mutation, deletion, reorder and checkpoint forgery are detected (`docs/evaluation/benchmarking-whitepaper.md` §4.11). |
| **Approvals bound to the exact call** | An approval lets through one retry of the same agent, tool and arguments, before expiry, once (`identity/service.py:redeem_approval`). **Decision:** presenting an approval can never make a call more permitted than a person saw. | **Escalate outcomes:** <br>- Credo Agent Governor ("escalate") [vendor page]. <br>- LlamaFirewall (`HUMAN_IN_THE_LOOP_REQUIRED`) [code]. <br>How an approval is bound to arguments is [ND] for both. <br>The Copilot Studio webhook can only allow or block [docs]. | Tested, not benchmarked. |
| **Harness hooks** | Claude Code hooks call a warm local daemon that runs the same `Enforcer` (`hooks/`). `updatedInput` lets an `alter` verdict rewrite the call. **Decision:** the hook path reports and does not block when the daemon is down (`hooks/client.py`), and says so. | **Has it:** <br>- Noma (decision made server-side; fails open on network error) [code]. <br>- Snyk Agent Guard [code]. <br>- Credo Agent Governor [vendor page]. <br>- Zenity Cursor plugin [code]. <br>Not a differentiator. | No benchmark. |
| **Continuous monitoring and live probing** | Connected GitHub repos, OpenAPI specs and MCP servers are re-checked on a schedule and diffed. Opt-in probes run against deployed agents (`monitoring/`, `evaluation/live_probes.py`). | **Has more:** <br>- Zenity, Noma, Lasso, Pillar and ServiceNow all ship estate discovery or posture management [vendor page / docs]. <br>- Snyk Agent Scan scans MCP supply chains [code]. <br>Theirs is broader. | Adaptive red-team: provenance-laundering mutations 0/30, tool-scope mutations 0/29, structural argument-shape mutations 0/105 after the nested-argument fix (`redteam.*`). <br>That is configuration regression testing, not robustness. |

---

## 3. "We win here because…"

Each line follows one shape: architecture fact → mechanism → measured result → why other architectures cannot get it by design.

1. **Containment survives a detector miss.**
   - **Architecture:** the action check reads where a value came from, never the text.
   - **Mechanism:** an attacker can rewrite a payload until no detector fires, but that does not change its `tool_result` provenance.
   - **Result:** our own adaptive attacker reaches 71% attack success at 50 attempts on the readable attacks we catch (`adaptive.readable_attack_success_at_50`), yet 38/38 of those bypasses still contained at the action (`adaptive.bypasses_contained_at_the_action`).
   - **Head to head on AgentDojo:** on AgentDojo's 588 injection pairs, llm-guard alone let 86/588 (14.6% [12.0, 17.7]) through at its default threshold; AgentFox containment let 0/588 (0.0% [0.0, 0.6]) through (`head_to_head.llm_guard_alone`, `head_to_head.containment_alone`).
     - **The price:** containment completes 24/97 benign tasks (24.7% [17.2, 34.2]), against llm-guard's 42/97 (43.3% [33.9, 53.2]).
     - **No deployable llm-guard threshold closes the gap:** at a benign false-positive rate of 5% or less, its best threshold still lets 389/588 through (`head_to_head.llm_guard_sweep_fpr5`).
     - **Where it ties:** tuned on the test set and in its chunked mode, it does tie containment (§5).
     - Prompt Guard 2 is not yet measured (§7).
   - **Why others can't by design:** a text classifier at the prompt/response boundary has nothing left to decide on once its text check is evaded. That covers Lakera Guard, Azure Prompt Shields, Bedrock Guardrails, Model Armor, llm-guard, Prompt Guard 2, and the Lasso, Prompt Security, F5 and Pillar classify APIs.
2. **We measure with the detectors deleted.**
   - **Architecture:** grants, impact tiers and provenance run without any detector.
   - **Mechanism:** we set `AGENTFOX_ENABLED_DETECTORS=[]` and replay the attack.
   - **Result:** 8/8 attacks contained with zero detector signal, with 4/4 legitimate calls still allowed (`containment.*`).
   - **Why others can't by design:** a product whose only decision is a classifier verdict has no detector-off mode to measure. We found no competitor publishing a detector-disabled containment number.
3. **We see the tool call as structure, not as a string.**
   - **Architecture:** the decision is taken on the tool key and typed arguments, against the agent's grants.
   - **Mechanism:** `order_id="*"` is a wildcard scope, and `amount` above the ceiling breaks a constraint. Neither contains injection-shaped text.
   - **Result:** tool-parameter tier 8/10 and excessive-agency tier 5/6; every attack is blocked, and the three misses are benign `tickets.update` controls held for approval by `cascade.reaches_notification`, because the demo world declares that a ticket update sends email. They were blocked until `email.send` was declared `effect: communication`; both tiers score an escalation as an intervention, so the counts did not change. In both tiers llm-guard "cannot participate" (`benchmarks/agent_security/results/tier_c_results.json`, `tier_d_results.json`).
   - **Why others can't by design:** Bedrock's Converse integration does not evaluate `toolUse.input` [docs]. llm-guard has no tool-call input [code].
4. **We hold up on long multi-step attacks at single-digit-millisecond cost.**
   - **Architecture:** we keep per-session state.
   - **Mechanism:** a trajectory detector reads the slope of a conversation instead of one message.
   - **Result:** 10/13 gradual-escalation conversations detected, with 0/9 control conversations flagged (`crescendo.*`), at 4.1 ms mean and 5.0 ms p95 added per turn (`crescendo.trajectory_latency`).
   - **Why others can't by design:** a stateless per-message scanner cannot see a slope. In the payload-splitting tier, llm-guard flags each fragment alone rather than the assembled attack (`benchmarks/agent_security/README.md`, Tier A).
5. **A model never decides a deterministic question.**
   - **Architecture:** a routing table seats only the parser on parse-tree questions.
   - **Mechanism:** a judgment tier may add recall elsewhere, but it cannot overrule `analyse_sql`.
   - **Result:** 160/165 injection payloads that defeated our pattern detectors are caught with a tier on, while SQL blast-radius accuracy stays at 100.0% with every tier enabled (`judgment.escaped_payloads_caught`, `judgment.sql_control_unchanged`).
   - **Why others can't by design:** when an LLM judge is the tool-call check, its error rate is the control's error rate. That applies to NeMo `tool_safety_check` and LlamaFirewall AlignmentCheck [code].
6. **An auditor can check our log without trusting us, on their own hardware.**
   - **Architecture:** a hash-chained decision log, shipped with a stdlib-only verifier.
   - **Result:** mutation, deletion, reorder and checkpoint forgery are all detected. This was verified adversarially, not benchmarked.
   - **Where others stand by design:** among the open-source tools we read, the logs are plain JSONL, a database or OpenTelemetry with no integrity chain [code]. AWS gets tamper-evidence from CloudTrail, but only inside AWS. Claim self-hosted portability, not uniqueness.
7. **No data leaves by default, including for judgment.**
   - **Architecture:** `allow_egress` is false by default. Hosted tiers redact first and do not send if redaction cannot run.
   - **Result:** this is a design property; no benchmark.
   - **Where others stand by design:** the Lasso gateway plugin [code], the Noma hook client [code] and Invariant Gateway [code] send their decisions to a vendor endpoint. Lakera, Pillar and F5 offer self-hosted modes [docs / vendor page], so do not claim this one as unique against them.

---

## 4. Competitor by competitor

**How the entries are read:**

- **Position**: where the product sits in the stack.
- **Sees**: what the decision can see. "Args" means tool-call arguments.
- **Decides**: model-based or deterministic.
- **Fails**: fail open or fail closed.
- **Evidence**: tamper-evident logging.
- **Delta**: the honest comparison, including where their architecture wins.

Commit-pinned repositories read: llm-guard `168c103`, NeMo-Guardrails `fe6a9c0`, guardrails `06d0ff2`, PurpleLlama `172c107`, invariant `2340fe2`, invariant-gateway `9baeade`, snyk/agent-scan `2d3ca36`, zenitysec/boundaries-as-code-template `d8d842e`, zenitysec/openclaw-security-platform `bc6d2ae`, Noma-Security/noma-marketplace `6e195a5`, lasso-security/mcp-gateway `7e7f1f6`, BerriAI/litellm `10444df` (Pillar and Prompt Security hooks), microsoft/agent-governance-toolkit `c767f83`.

### Lakera Guard (Check Point)

- **Position.** A text-screening API (`POST /v2/guard`, OpenAI-format `messages`), SaaS or self-hosted [docs][lk-api][lk-self].
  - Check Point closed the acquisition on 22 October 2025 [vendor page][lk-cp].
- **Sees.**
  - Screened: user and assistant content, `tool_calls` "as the agent's actions", and `tool` messages "as untrusted content".
  - Not screened: system messages.
  - Whether arguments are evaluated field by field is [ND] [docs][lk-api].
  - There is a "Tool Allow/Deny List"; its argument scope is [ND] [docs][lk-def].
- **Provenance.** [ND].
- **Decides.** "Machine learning and language models with rule-based filters" [docs][lk-def].
- **Fails.** It returns `flagged`, and "your application determines the appropriate action"; timeout behaviour is [ND] [docs][lk-int].
- **Evidence.** A `request_uuid` per call; tamper-evidence is [ND].
- **Delta.**
  - **Lakera wins on:** a managed, multilingual classifier, GPU self-hosting, and central policy.
  - **We win on:** a decision that survives an evaded classifier (§3.1).
  - **Caveat:** their PINT numbers are self-reported on a private dataset, and we do not compare against them (`benchmarks/REPORT.md`).

### Protect AI LLM Guard (Palo Alto Networks)

- **Position.** A Python library with sequential `scan_prompt` and `scan_output` loops, plus an optional FastAPI server [code][lg-eval].
  - Palo Alto Networks completed the acquisition on 22 July 2025 [vendor page][lg-pa].
- **Sees.** Prompt and output text only. There is no `tool_call` or `function_call` handling in `llm_guard/` [code][lg-eval].
- **Provenance.** None [code].
- **Decides.** Both:
  - model-based: the `PromptInjection` scanner uses `protectai/deberta-v3-base-prompt-injection-v2` at a 0.92 threshold [code][lg-pi];
  - deterministic: regex, ban-substring, secrets and invisible-text scanners.
- **Fails.**
  - Library: scanner exceptions propagate to the caller.
  - API server: returns HTTP 408 on timeout (10 s for prompts, 30 s for outputs), so the caller decides [code][lg-app].
- **Evidence.** structlog and OpenTelemetry counters; no chain [code].
- **Delta.** We have run two head-to-heads against a real installed `llm-guard`.
  - On 20 indirect-injection cases it is more precise than us: llm-guard 81.8% precision and 90.0% recall, against AgentFox's 66.7% and 100.0% (`agent_security.tier_b_vs_llm_guard`).
  - On AgentDojo's 588 injection pairs (`benchmarks/head_to_head/`), at its default it let 86/588 through where containment let 0/588 through. It completes more benign tasks, and it ties containment once tuned (§5).
  - On tool parameters and excessive agency it has no input to decide on, so we do not score it as a zero.

### NVIDIA NeMo Guardrails

- **Position.** An SDK, plus an OpenAI-compatible server that can act as a proxy [code][nm-api]. Rails are Colang flows and Python actions.
- **Sees args: yes.**
  - "Tool output rails" run on tool calls *before* execution and "validate tool names, parameters, and context" [code][nm-cfg].
  - `@tool_output_validation` rejects undeclared tools and arguments that fail the JSON schema [code][nm-schema].
  - `tool_safety_check` sends the tool name and arguments to an LLM judge [code][nm-tsc].
- **Provenance.** None. The argument check sees values, not where they came from [code].
- **Decides.** Both: deterministic schema and YARA rules, and LLM-judge rails.
- **Fails.** **Closed** in the IORails engine: "a rail that fails blocks" [code][nm-rail].
- **Evidence.** Logging and OpenTelemetry; no chain [code].
- **Delta.**
  - **NeMo wins on:** a programmable dialogue language, and the largest ecosystem of safety-model integrations.
  - **It is closest to us on:** tool-call inspection.
  - **The difference:** its tool check is schema plus a model, while ours is grants plus provenance plus parsed semantics. No head-to-head has been run.

### Guardrails AI

- **Position.** An SDK `Guard` that wraps the LLM call and validates output, plus an optional REST server [code][ga-guard].
  - Harvey announced the acquisition on 9 September 2026 [vendor page][ga-harvey].
- **Sees.** Prompt and LLM output. It uses tool calling as a structured-output mechanism (`tool_calls[-1].function.arguments` is validated as the output) [code][ga-llm]. There is no agent tool-call policy hook.
- **Provenance.** None. The `provenance_llm` hub validator checks hallucination against sources, not data flow.
- **Decides.** Per validator, either way; Hub validators may run on remote inference [code][ga-val].
- **Fails.** The default `on_fail` is `EXCEPTION`, so the caller decides [code][ga-val].
- **Evidence.** Call history and OpenTelemetry; no chain.
- **Delta.**
  - **Guardrails AI wins on:** output repair (reask and fix loops) and a community validator hub.
  - **Overlap:** it is a different problem from action containment, with little overlap.

### Meta LlamaFirewall / Prompt Guard 2

- **Position.** A library. `LlamaFirewall.scan` maps scanners to message roles: PromptGuard on user and tool messages, CodeShield on assistant and tool messages [code][pl-fw].
- **Sees.** Message content by role. AlignmentCheck reads the whole trace and asks whether the latest action serves the user's goal; arguments are seen as text inside that trace [code][pl-ac].
- **Provenance.** None. It reasons about goal alignment, not value origin [code].
- **Decides.** Both:
  - Prompt Guard 2 is a classifier, blocking at score 0.9 or above [code][pl-pg]; it comes in 86M multilingual and 22M variants with a 512-token context [code][pl-mc];
  - AlignmentCheck is an LLM judge;
  - CodeShield uses regex and Semgrep.
- **Fails.** Mixed:
  - an AlignmentCheck LLM error yields `HUMAN_IN_THE_LOOP_REQUIRED`;
  - a missing trace returns ALLOW with status ERROR [code][pl-ac].
- **Evidence.** Python logging only [code].
- **Delta.**
  - **It wins on:** open-weight multilingual classifiers, and AlignmentCheck can catch a misaligned action that no declared rule anticipated.
  - **We win on:** a decision that does not rest on a model judging the trace.
  - **Not yet run:** we have not run Prompt Guard 2 head to head. The harness is built (`benchmarks/head_to_head/`), but the gated model needs the account owner to accept Meta's licence (§7).

### Microsoft Azure AI Content Safety: Prompt Shields

- **Position.** Two forms:
  - a REST classifier, `text:shieldPrompt` with `{userPrompt, documents[]}` [docs][az-api];
  - platform-native guardrails in Microsoft Foundry, with intervention points at user input, tool call (preview, Foundry Agent Service agents only), tool response and output [docs][az-gr].
- **Sees.** A prompt plus up to 5 documents, 10K characters each [docs][az-reg]. The Foundry tool-call point sees "the action and data the agent proposes to send to a tool".
- **Provenance.** None per argument. Spotlighting (preview, off by default, not for agents) base64-tags documents as lower trust [docs][az-jb].
- **Decides.** "Classification models" [docs][az-gr].
- **Fails.** Errors return an `ErrorResponse`; timeout semantics are [ND].
- **Evidence.** Per-request annotations; tamper-evidence is [ND].
- **Delta.**
  - **Azure wins on:** zero-code enforcement on every Foundry deployment, regional processing, and customer-managed keys.
  - **Language coverage:** Prompt Shields was "tested… with English only" [docs][az-reg].
  - **We win on:** provenance-aware decisions on any framework, not one platform.

### AWS Bedrock Guardrails

- **Position.** A managed classifier and policy service:
  - inside Bedrock inference, or standalone via `ApplyGuardrail` (`source: INPUT|OUTPUT`, `content[].text`) [docs][aws-apply];
  - AWS Organizations policies enforce it org-wide [docs][aws-enf].
- **Sees.** In Converse, it does **not** evaluate tool results, tool definitions or `toolUse.input` [docs][aws-conv].
  - The prompt-attack filter needs input tags on `InvokeModel`, or "prompt attacks… will not be filtered" [docs][aws-pa].
- **Provenance.** [ND].
- **Decides.** Both:
  - deterministic: word and regex filters;
  - model-based: content, prompt-attack, denied-topic and grounding filters;
  - Automated Reasoning: formal logic over rules extracted by models; detect-only, English only, "no prompt injection protection" [docs][aws-ar].
- **Fails.** No configurable fail mode is documented. In async streaming, the model may respond while the assessment continues [docs][aws-conv].
- **Evidence.** CloudTrail data events, tamper-evident through log-file integrity validation [docs][aws-ct].
- **Delta.**
  - **AWS wins on:**
    - org-wide enforcement callers cannot bypass;
    - formal verification of policy claims;
    - signed evidence;
    - a free fit for Bedrock-only shops.
  - **We win on:** the tool call itself, which Converse guardrails do not look at.

### Google Cloud Model Armor

- **Position.** A stateless managed API (`sanitizeUserPrompt`, `sanitizeModelResponse`) [docs][ma-san].
  - It is inline through Agent Gateway, Apigee, Service Extensions, Vertex and Google MCP servers [docs][ma-int].
  - The REST API on its own is detect-only.
- **Sees.** Text and documents. On MCP it sanitises `tools/call` request and response payloads; field-level policies are [ND] [docs][ma-mcp].
- **Provenance.** [ND].
- **Decides.** Mostly classifiers, plus Sensitive Data Protection infoTypes [docs][ma-ov].
- **Fails.** **Open** on Vertex: it "skips the Model Armor sanitization step and continues processing" when unavailable [docs][ma-vx].
- **Evidence.** Cloud Logging; integrity is [ND].
- **Delta.**
  - **Google wins on:** network-layer insertion with no code changes, plus multilingual and document scanning.
  - **We win on:** argument structure and provenance.

### Prompt Security (SentinelOne)

- **Position.** Browser extension, MCP gateway, code-assistant integrations and an API [vendor page][ps-s1].
  - SentinelOne completed the acquisition on 5 September 2025 [docs: SEC 10-Q][ps-sec].
  - The API contract, from the LiteLLM integration: `POST /api/protect` with `{messages, user, system_prompt}`, returning `block` or `modify` [code][ps-lite].
- **Sees.** System, user and assistant messages by default. Tool results are sent only when `check_tool_results` is on (default false) [code][ps-lite]. Tool arguments are [ND].
- **Provenance.** [ND]. **Decides.** [ND].
- **Fails.** File sanitisation fails open after 30 s in that integration [code]; the vendor default is [ND].
- **Evidence.** "Searchable audit log" claimed; integrity is [ND].
- **Delta.**
  - **It wins on:** employee and browser shadow-AI coverage, which an in-process library cannot see.

### Zenity

- **Position.** AISPM and runtime prevention across SaaS and low-code agent platforms (Copilot Studio, Foundry, Salesforce) [docs][zn-docs][zn-blog].
- **Policy ("Boundaries").** Cedar-style `forbid` and `taint` rules, managed as code [code][zn-readme].
- **Sees args: yes.** `resource.attributes.arguments`, outbound domains derived from arguments, and the agent's configuration [code][zn-fixture].
- **Provenance: conversation-level taint.**
  - A rule can mark the conversation, e.g. `CUSTOMER_DATA_ACCESSED` when a retrieval matches a pattern [code][zn-taint].
  - A later `forbid` on `execute_tool` reads that mark [code][zn-egress].
  - System taints such as `SYSTEM.MALICIOUS` come from a prompt-injection signal [code][zn-untrusted].
  - No per-value link was found; the fixture's `toolOrigins` is empty.
- **Decides.** Deterministic rules; the detector inputs behind them are [ND].
- **Fails.**
  - Commercial product: [ND].
  - Zenity's open-source OpenClaw shim allows on timeout or an unreachable server [code][zn-shim].
- **Evidence.** Commercial: [ND]. OpenClaw writes append-only JSONL with no hash [code].
- **Delta.** **The closest architecture to ours** (see §5).
  - **Zenity wins on:** Copilot Studio and low-code coverage (a deliberate non-goal for us), estate discovery, and policy-as-code CI.
  - **The real difference:**
    - our taint is set by where a value came from, not by a pattern or detector match;
    - we can run per argument;
    - we carry ceilings on the grant;
    - and we publish a detector-off result.

### Noma Security

- **Position.** Discovery and AISPM, plus runtime enforcement through "AI gateways, MCP gateways, agent hooks, agent SDKs" [vendor page][nm-acp].
  - Its open-source hook client forwards the whole hook event to Noma's server, which makes the decision [code][noma-hook].
- **Sees args.** "Tool calls and arguments" [vendor page][nm-dr].
- **Provenance.** [ND] per value; it describes session-level context.
- **Decides.** [ND].
- **Fails.** **Open** in the hook client on a network failure or a 10 s timeout ("degrade quietly") [code][noma-tx].
- **Evidence.** Not claimed on Noma's own pages. A third-party registry claims "tamper-evident receipts", unverified.
- **Delta.**
  - **Noma wins on:** one policy across many enforcement points (gateways, EDR/MDM, hooks), and estate discovery.
  - **Us:** the same hook surface, but our decision runs locally.

### Lasso Security

- **Position.** Browser extension, AI gateway, and an open-source MCP gateway [vendor page][ls-site][code][ls-mgr].
- **Sees args.** The `lasso` plugin flattens every string argument into one message and classifies it remotely [code][ls-plugin].
- **Provenance.** None [code].
- **Decides.** A remote classifier, plus regex secret redaction [code].
- **Fails.** **Open**: the code says "fail open" on errors, and a missing API key passes through [code][ls-plugin].
- **Evidence.** Request and response logs, no chain [code].
- **Delta.**
  - **Lasso wins on:** browser shadow-AI coverage, and reputation scanning of MCP servers before load.
  - **Us:** we decide on the structure Lasso flattens away.

### Invariant Labs Guardrails (Snyk)

- **Position.** A rule engine (`raise "..." if:`), an LLM and MCP proxy gateway that posts traces to a hosted check API, and Agent Scan for supply chains [code][iv-readme][iv-gw][sn-scan].
  - Snyk announced the acquisition on 24 June 2025 [vendor page][iv-snyk].
- **Sees args: yes.** Rules match argument values by exact value, regex or type [docs][iv-ref].
- **Provenance: trace ordering, not value taint.**
  - `->` maps to `has_flow`, which is true if one event precedes another in the trace [code][iv-df][iv-eval].
  - A link between a specific argument value and its source must be written into the rule.
- **Decides.** Deterministic rules, plus built-ins that are models: a deberta prompt-injection classifier at 0.9, Presidio, and LLM checks [code][iv-pi].
- **Fails.** **Effectively closed** on the MCP path: check errors become blocking errors [code][iv-mcp].
- **Evidence.** Traces go to Invariant Explorer; no chain [code].
- **Delta.**
  - **Invariant wins on:** an expressive trace language, and an architecture strong enough to express our containment rules by hand.
  - **The difference:** our provenance is inferred and attached to each argument automatically, with tiers and ceilings; theirs is authored per rule.

### CalypsoAI (F5 AI Guardrails)

- **Position.** A SaaS scan API (`POST /scans`, `input` is a string), plus an NGINX Gateway Fabric integration [docs][f5-scan][f5-ngf].
  - F5 closed the acquisition on 26 September 2025 [docs: SEC 10-Q][f5-sec].
- **Sees.** A string, or OpenAI request bodies. Tool-argument policies are [ND].
- **Provenance.** [ND].
- **Decides.** GenAI, regex or keyword custom scanners [docs][f5-custom].
- **Fails.** The NGINX integration returns 403 on block and fails closed on invalid TLS policy [docs][f5-ngf].
- **Evidence.** Configuration audit log; integrity is [ND] [docs][f5-audit].
- **Delta.**
  - **F5 wins on:** integrated red teaming, delivery through network infrastructure, and customer-written GenAI scanners.

### Pillar Security

- **Position.** A SaaS API (`POST /api/v1/protect`, sending messages and tool definitions) [code][pi-lite], plus discovery, red teaming and self-hosted deployment [vendor page][pi-plat].
  - Pillar's own docs require an access code.
- **Sees.** Messages and tool *definitions*; argument inspection is [ND].
- **Provenance.** It claims "taint analysis" to "trace PII and secrets from source to destination"; the mechanism is [ND] [vendor page][pi-plat].
- **Decides.** [ND].
- **Fails.** **Open** by default in the LiteLLM integration (`fallback_on_error: allow`) [code][pi-lite].
- **Evidence.** Audit logs claimed; integrity is [ND].
- **Delta.**
  - **Pillar wins on:** attack-path red teaming and discovery.
  - **Watch:** its taint claim is the one to verify if it comes up in a deal.

### ServiceNow AI Control Tower (governance platform)

- **Position.** A governance system of record with Service Graph discovery connectors [docs][sn-rel].
  - Its AI Gateway is the runtime layer for MCP: tool-level approve or reject, and pattern-based blocking of sensitive data [docs][sn-faq].
- **Sees.** MCP server and tool access, and call content. Field-level argument parsing is [ND].
- **Provenance.** [ND].
- **Decides.** Deterministic patterns, plus LLM-as-judge evaluations after the fact [docs][sn-rel].
- **Fails.** Closed for a paused server ("requests are blocked"); behaviour on a gateway outage is [ND] [docs][sn-faq].
- **Evidence.** Claims "tamper-evident audit logs"; the mechanism is [ND] [docs][sn-faq].
- **Delta.**
  - **ServiceNow wins on:**
    - discovery breadth;
    - a CMDB-linked registry;
    - workflows;
    - a kill switch through IdP revocation.
  - **Us:** deeper per-call semantics, which we have measured. Theirs is unmeasured publicly.

### Microsoft agent-governance-toolkit (open source, MIT): platform-absorption risk

This is not a point product. It is the risk that the platform owner gives the category away. The toolkit is free, MIT-licensed, Microsoft-maintained, and wired into Entra. A buyer already on Azure can get "agent governance" without a purchase order. Read at commit `c767f83`; every claim below cites a file there, and anything we could not confirm in the code was left out.

- **Position.**
  - In-process middleware or a sidecar per agent. The management plane is a separate Azure service: their FAQ calls the toolkit the enforcement engine and the Foundry Control Plane "the management dashboard" (`docs/FAQ.md:39-45`).
  - Identity bridges to Entra Agent ID and managed identities (`agentmesh/identity/entra_agent_id.py`, `docs/FAQ.md:199-201`).
- **Breadth, where it wins outright.**
  - SDKs in five languages (`agent-governance-{python,typescript,dotnet,golang,rust}/`).
  - Plugins or hooks for five coding agents: Claude Code, Codex CLI, Copilot CLI, OpenCode and Antigravity (`agent-governance-{claude-code,codex-cli,copilot-cli,opencode,antigravity-cli}/`). We ship one, for Claude Code (`plugins/claude-code/`).
  - 18 framework adapters in one package (`agent_os/integrations/*_adapter.py`), plus more under `agentmesh-integrations/`.
  - Ed25519-signed agent identities (`agentmesh/identity/agent_id.py:13, 172`).
  - A sandbox package (`agent-governance-python/agent-sandbox/`). We have no sandbox.
- **Decides.** Rules, parsed out of condition strings with regular expressions. Two engines are cited in their own NIST mapping:
  - **AgentMesh `PolicyRule`** (`agentmesh/governance/policy.py:184-396`) matches each condition against anchored regexes for `==`, `!=`, `in`, `contains`, `startswith`, `endswith` and comparison with a *numeric literal*.
    - It splits compound conditions on the bare strings `" or "` and `" and "` (`:216-223`).
    - A field-to-field comparison such as `amount > limit.max` matches none of the patterns. It falls to "unrecognized syntax": a deny rule then matches, so it fails closed with a logged warning, and an allow rule does not match (`:386-396`). That is safe, but the comparison is unsupported.
  - **The TypeScript MCP-server `PolicyEngine`** (`agent-os/extensions/mcp-server/src/services/policy-engine.ts`, their "TypeScript MCP policy engine") is weaker. `evaluateRule` (`:406-445`), commented "Simplified rule evaluation", understands only `action.type ==`, `action.type in [...]` and `true`. Every other condition returns `false` with no log, including:
    - the shipped field-to-field rule `daily_cost > budget.daily` (`:93`);
    - `estimated_cost > 10.00` (`:101`).

    So those deny and approval rules never fire. A compound rule such as `action.type == "delete" && action.record_count > 100` (`:128`) fires on every delete, because only its first half is read.
  - The trust-policy `matches` operator returns `False` for any pattern containing `{`, so `\d{16}` never matches, and the same holds for any pattern over 200 characters (`agentmesh/governance/trust_policy.py:96-97`).
- **Provenance.** We found no per-argument taint or provenance ceiling in their SDK source; a search for "taint" finds none. Their data-provenance model is a documentation schema (`docs/compliance/data-provenance-model.md`).
- **Evidence.**
  - Their `verify` command's default mode (`agt verify` without `--evidence`, `agent_compliance/cli/agt.py:268-273`) reports OWASP ASI coverage, a letter grade and a badge. It counts a control as present when a Python module imports and a named class exists (`agent_compliance/verify.py:497-513, 728-775`). Importing `PromptInjectionDetector` scores ASI-01 whether or not anything calls it.
  - A separate `--evidence` mode does check a runtime evidence file (`verify.py:515`).
- **Measured.**
  - Their own prompt-injection detector reports 7/110 attacks caught (6.4% recall) and 16/170 benign rows flagged (9.4%) on their smoke corpus (`benchmarks/prompt-injection/README.md:72-75`). On the same 280 rows our `injection.heuristic` caught 34/110 attack rows and flagged 32/170 benign rows (`benchmarks/toolkit_corpus/`). That is more recall at twice their false-positive rate, and neither detector catches prompt-leakage or markdown-image exfiltration.
  - Their red-team benchmark marks a scenario contained exactly when it is labelled unsafe (`tests/redteam/benchmark/benchmark.py:332-334`). That is a contract test, not a measurement. We instantiated their 24 scenarios on our enforcement path: 12/12 of the unsafe scenarios contained with every detector off, at the cost of one hard-benign false block with detectors on.
- **Delta.**
  - **They win on:**
    - price (free);
    - distribution (Azure, Entra, Foundry);
    - SDK and framework breadth;
    - signed identities;
    - a sandbox;
    - a large published compliance-mapping set.

    Some of that mapping set has errors; see [compliance-crosswalk-review.md](compliance-crosswalk-review.md).
  - **We win on:**
    - per-argument provenance with taint ceilings on the grant, which their rule engines have no field for;
    - containment measured with detectors off, on AgentDojo and on their own scenarios;
    - one deployable gateway with an approval queue bound to exact arguments and our own dashboard, where theirs splits enforcement from a hosted Azure management plane;
    - a runtime answerability gate, grounding against registered sources, and per-requester entitlement. Their nearest equivalent is an offline eval that counts a sentence as grounded if any word longer than four letters appears in the context (`agent_sre/evals/__init__.py:194-203`).
  - **Not a differentiator against them:**
    - Zero egress. Both run self-hosted and in-process.
    - Compliance mappings. Theirs and ours are both self-assessed drafts.
  - **The risk to plan for:** a buyer who reads "Microsoft, free, OWASP 10/10" and never asks how a rule is evaluated. The answer is the evaluator behaviour above and a measured containment number, not a feature list.

---

## 5. Where our architecture loses or is unproven

- **Utility is the price of containment.** With session-level taint, only 24/97 benign tasks (24.7% [17.2, 34.2]) run without escalating to a human (`agentdojo.session_taint.benign_tasks_allowed`).
  - Per-argument taint: 37/97 benign tasks, 527/588 attack pairs contained (`agentdojo.argument_taint`).
  - Inferred provenance cannot tell a legitimate copy from an attack.
- **Grants alone do nothing against injection.** None (grants and impact tiers only): 97/97 benign, 0/588 attack pairs contained (`agentdojo.capability_only`). The win is provenance, and provenance depends on declarations an operator can get wrong.
- **Detection is weak by default.**
  - The shipped lexical heuristic's held-out injection recall is 26.7% at 100% precision (`injection.heuristic_held_out`).
  - The opt-in ensemble reaches 85.6% recall on SPML (`generalization.classifier_spml_recall`), but it times out on long prompts (`benchmarks/REPORT.md`, round 7).
- **The heuristic over-fires on text that quotes an attack.** On the third-party smoke corpus in `benchmarks/toolkit_corpus/`, it flags benign security notes, fixtures and changelogs that quote "ignore all previous instructions" at twice the rate of that project's own detector. It also misses prompt-leakage, markdown-image exfiltration and every leetspeak and rot13 spelling (see §4, Microsoft agent-governance-toolkit).
- **The answerability gate is real, but its default recall is low.** It abstains on 57/676 contested questions; with a judgment tier that becomes 572/676 (`judgment.contested_recall_*`), at 6.8% over-refusal (`benchmarks/judgment/results/judgment_results.json`).
- **Judgment costs latency.** The hosted tier adds 341.3 ms median and 1209.8 ms p95 per injection check (`judgment.injection_latency`), against 0.22 ms per example for the heuristic (`injection.heuristic_held_out`).
- **The hook path fails open.** The default `fail_mode` is also open (`runtime/availability.py`). Only the four `NEVER_OPEN` controls are guaranteed closed.
- **Not built:**
  - no sandbox (that is E2B/Modal/Daytona's job);
  - no network capture, browser extension or desktop coverage;
  - no Copilot Studio or low-code coverage;
  - no live IdP;
  - text only (`docs/architecture/high-level-design.md` §11).
- **Head-to-heads.**
  - Two have been run, both against `llm-guard`:
    - on 20 indirect-injection cases, where it was more precise;
    - on AgentDojo (`benchmarks/head_to_head/`), where it loses on attacks and wins elsewhere, as the next three bullets say.
  - Every other comparison on this page, including Prompt Guard 2, is architectural, read from docs and code, not measured.
- **llm-guard wins on benign utility.**
  - At its defaults, on AgentDojo, llm-guard completes 42/97 benign tasks to containment's 24/97.
  - At a benign false-positive rate of 5% or less it completes 82/97, while letting 389/588 attacks through.
- **llm-guard ties containment once tuned.** In its non-default chunked mode, with a threshold tuned on the test set, it reaches 0/588 (0.0% [0.0, 0.6]) attacks at 24/97 benign tasks, the same point as containment (`head_to_head.llm_guard_chunks_matched_utility`). That setting flags 38.3% of benign tool outputs. The containment win is "no tuning and no model", not "a better point on the curve".
- **Our detectors miss AgentDojo's injection text, and llm-guard does not.**
  - With the shipped detectors on, an injection rule fired on 0 of the 752 injected tool outputs (`head_to_head.agentfox_detectors_on_outputs`).
  - llm-guard flags 195 of the 298 distinct injected outputs at its default, and 291 of 298 chunked (`head_to_head.llm_guard_injected_recall`).
  - Every AgentFox containment on that benchmark came from provenance.
- **Stacking costs utility.** llm-guard + AgentFox containment completes only 11/97 benign tasks (`head_to_head.llm_guard_plus_containment`). Containment alone already contains every pair, so the classifier adds false positives and nothing else.
- **Compliance mappings are DRAFT**, not reviewed by counsel.
- **Corrections to [competitor-analysis.md](competitor-analysis.md) §4.**
  - **Argument-provenance taint is not unclaimed.** Zenity Boundaries has deterministic, conversation-scoped taint rules over tool calls. Our shipped default is also session-level. Say "per-value provenance with grant ceilings, measured with detectors off", not "nobody tracks taint".
  - **The audit chain is not unique.** AWS CloudTrail is tamper-evident, and ServiceNow claims it. Our claim is a self-hosted chain with an offline, stdlib-only verifier.

---

## 6. Objection handling

- **"Lakera blocks prompt injection too."**
  - Yes, and as a dedicated classifier it is a different product from our default lexical heuristic. We make no comparative detection claim and decline to quote PINT.
  - The question is what happens after a classifier misses. Our adaptive attacker gets 71% attack success at 50 attempts against our own detectors, yet 38/38 of those bypasses still contained at the action.
  - A screening API returns `flagged`, and "your application determines the appropriate action" [docs][lk-int]. We are that application-side decision. The two are complementary.
- **"Bedrock Guardrails is free with my cloud."**
  - For text it is a good default. Keep it.
  - But in Converse it does not evaluate tool-call arguments, tool results or tool definitions [docs][aws-conv], and that is where an agent does damage.
  - We decide on the tool call, across Bedrock, Azure, Vertex and OpenAI alike.
- **"Why not just a classifier?"**
  - *The Attacker Moves Second* reports over 90% attack success against twelve defences once the attacker adapts.
  - Our grants-and-provenance layer contained 8/8 attacks with zero detector signal. A classifier has no detector-off mode to measure.
  - Add our classifier, or anyone's, as a cost on the attacker.
- **"NeMo or Invariant can express this already."**
  - Partly true. NeMo checks tool arguments with a schema and an LLM judge; Invariant writes value and ordering rules.
  - What neither does by default is infer, for every argument, which tool output its value came from, and cap that against a declared impact tier.
- **"Zenity already does taint."**
  - At conversation level, yes, and inside Copilot Studio they are ahead.
  - Ask how a taint is set (a pattern or detector match, or the value's origin) and whether they publish a detector-off number.
- **"Your benign utility is terrible."**
  - At session-level taint, yes: 24/97. The mitigation path is published:
    - per-argument taint;
    - read-only exemption;
    - approvals bound to the exact call, so a held call runs once a person approves it.
- **"Fail-open is unsafe."**
  - It is the default only for detectors and hooks.
  - Tenant isolation, entitlement filtering, data-access scope and the audit chain refuse to be configured open.
  - Grants and provenance have no remote dependency to fail.

---

## 7. Proof gaps to close

These are the runs that would turn an architectural claim on this page into a measured one, in priority order.

1. **AgentDojo with competitor detectors in the loop.** Run Prompt Guard 2, llm-guard and, under a trial key, Lakera Guard and Azure Prompt Shields as the only defence on the same 588 pairs, then stack them with containment.
   - This turns "a classifier has nothing left after a miss" into a number.
   - **Partially measured** (`benchmarks/head_to_head/`).
     - **llm-guard:** done, with a threshold sweep and a latency comparison: 71.9 ms p50 per tool result, against 6.9 ms for containment (`head_to_head.latency`).
     - **Prompt Guard 2:** wired, but blocked on Meta's licence gate on Hugging Face. The account owner must accept it; the arm is then one command.
     - **Lakera and Azure:** not attempted; they need trial keys.
     - **The adaptive version of this** is still gap 5.
2. **NeMo tool rails against the tool-parameter and excessive-agency tiers.** NeMo is the competitor whose architecture can see the same inputs. We should score it rather than describe it.
3. **Invariant rules that encode our containment policy, on AgentDojo.** This tests whether hand-written flow rules match inferred provenance on utility and containment.
4. **Bedrock `ApplyGuardrail` on tool arguments passed explicitly as text.** This measures the integrator workaround, not just the documented Converse gap.
5. **The adaptive attacker against Prompt Guard 2 and llm-guard**, with the same protocol and budget as `benchmarks/adaptive/`, so "71% against us" has comparators.
6. **Latency under the same harness.** Our per-call cost against llm-guard and Prompt Guard 2 on one machine. `benchmarks/agent_security/README.md` says this was never done.
   - Done for llm-guard on AgentDojo tool outputs; see gap 1. Prompt Guard 2 is still to do.
7. **Re-run the pending benchmarks** (adaptive, redteam provenance) and update the bound claims. Until then, this page quotes the committed results.

[lk-api]: https://docs.lakera.ai/docs/api/guard
[lk-self]: https://docs.lakera.ai/docs/selfhosting
[lk-def]: https://docs.lakera.ai/docs/defenses
[lk-int]: https://docs.lakera.ai/docs/integration
[lk-cp]: https://www.checkpoint.com/press-releases/check-point-software-reports-2025-third-quarter-financial-results/
[lg-eval]: https://github.com/protectai/llm-guard/blob/168c1034ffdb33837e7ae6fd6a16b80567c1be03/llm_guard/evaluate.py#L23-L127
[lg-pi]: https://github.com/protectai/llm-guard/blob/168c1034ffdb33837e7ae6fd6a16b80567c1be03/llm_guard/input_scanners/prompt_injection.py#L39-L52
[lg-app]: https://github.com/protectai/llm-guard/blob/168c1034ffdb33837e7ae6fd6a16b80567c1be03/llm_guard_api/app/app.py#L257-L261
[lg-pa]: https://www.paloaltonetworks.com/company/press/2025/palo-alto-networks-completes-acquisition-of-protect-ai
[nm-api]: https://github.com/NVIDIA/NeMo-Guardrails/blob/fe6a9c01184695a6b84c02fd2efe6dd3a607575c/nemoguardrails/server/api.py#L649-L663
[nm-cfg]: https://github.com/NVIDIA/NeMo-Guardrails/blob/fe6a9c01184695a6b84c02fd2efe6dd3a607575c/nemoguardrails/rails/llm/config.py#L437-L476
[nm-schema]: https://github.com/NVIDIA/NeMo-Guardrails/blob/fe6a9c01184695a6b84c02fd2efe6dd3a607575c/nemoguardrails/guardrails/tool_schema.py#L209-L241
[nm-tsc]: https://github.com/NVIDIA/NeMo-Guardrails/blob/fe6a9c01184695a6b84c02fd2efe6dd3a607575c/nemoguardrails/library/tool_safety_check/actions.py#L29-L60
[nm-rail]: https://github.com/NVIDIA/NeMo-Guardrails/blob/fe6a9c01184695a6b84c02fd2efe6dd3a607575c/nemoguardrails/guardrails/rail_guard.py#L16-L25
[ga-guard]: https://github.com/guardrails-ai/guardrails/blob/06d0ff2c5f9bcb493d976b76f885e37e41ce845d/guardrails/guard.py#L1070-L1098
[ga-llm]: https://github.com/guardrails-ai/guardrails/blob/06d0ff2c5f9bcb493d976b76f885e37e41ce845d/guardrails/llm_providers.py#L233
[ga-val]: https://github.com/guardrails-ai/guardrails/blob/06d0ff2c5f9bcb493d976b76f885e37e41ce845d/guardrails/validator_base.py#L111-L140
[ga-harvey]: https://www.harvey.ai/blog/guardrails-ai-joins-harvey
[pl-fw]: https://github.com/meta-llama/PurpleLlama/blob/172c1074069eb88ec834124272c1b1c4f8893445/LlamaFirewall/src/llamafirewall/llamafirewall.py#L87-L167
[pl-ac]: https://github.com/meta-llama/PurpleLlama/blob/172c1074069eb88ec834124272c1b1c4f8893445/LlamaFirewall/src/llamafirewall/scanners/experimental/alignmentcheck_scanner.py#L62-L134
[pl-pg]: https://github.com/meta-llama/PurpleLlama/blob/172c1074069eb88ec834124272c1b1c4f8893445/LlamaFirewall/src/llamafirewall/scanners/prompt_guard_scanner.py#L22-L45
[pl-mc]: https://github.com/meta-llama/PurpleLlama/blob/172c1074069eb88ec834124272c1b1c4f8893445/Llama-Prompt-Guard-2/22M/MODEL_CARD.md#L16-L25
[az-api]: https://learn.microsoft.com/en-us/rest/api/contentsafety/text-operations/shield-prompt
[az-gr]: https://learn.microsoft.com/en-us/azure/foundry/guardrails/guardrails-overview
[az-reg]: https://learn.microsoft.com/en-us/azure/ai-services/content-safety/region-availability
[az-jb]: https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection
[aws-apply]: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html
[aws-enf]: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-enforcements.html
[aws-conv]: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html
[aws-pa]: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html
[aws-ar]: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html
[aws-ct]: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html
[ma-san]: https://docs.cloud.google.com/model-armor/sanitize-prompts-responses
[ma-int]: https://docs.cloud.google.com/model-armor/integrations
[ma-mcp]: https://docs.cloud.google.com/model-armor/model-armor-mcp-google-cloud-integration
[ma-ov]: https://docs.cloud.google.com/security-command-center/docs/model-armor-overview
[ma-vx]: https://docs.cloud.google.com/model-armor/model-armor-vertex-integration
[ps-s1]: https://www.sentinelone.com/platform/prompt-security-agentic-ai-security/
[ps-sec]: https://www.sec.gov/Archives/edgar/data/1583708/000158370825000159/s-20251031.htm
[ps-lite]: https://github.com/BerriAI/litellm/blob/10444df3a0173a99ab4e4858ce6777f31530e6c5/litellm/proxy/guardrails/guardrail_hooks/prompt_security/prompt_security.py#L276-L316
[zn-docs]: https://docs.zenity.io/
[zn-blog]: https://zenity.io/blog/zenity-brings-inline-prevention-to-microsoft-foundry-and-copilot-studio
[zn-readme]: https://github.com/zenitysec/boundaries-as-code-template/blob/d8d842e74499adec691bae6c11e7f26e3438e6bf/README.md#L50-L65
[zn-fixture]: https://github.com/zenitysec/boundaries-as-code-template/blob/d8d842e74499adec691bae6c11e7f26e3438e6bf/tests/fixtures/outlook-send.json#L42-L104
[zn-taint]: https://github.com/zenitysec/boundaries-as-code-template/blob/d8d842e74499adec691bae6c11e7f26e3438e6bf/taints/CUSTOM.CUSTOMER_DATA_ACCESSED.yaml#L1-L13
[zn-egress]: https://github.com/zenitysec/boundaries-as-code-template/blob/d8d842e74499adec691bae6c11e7f26e3438e6bf/boundaries/customer-data-egress.yaml#L13-L21
[zn-untrusted]: https://github.com/zenitysec/boundaries-as-code-template/blob/d8d842e74499adec691bae6c11e7f26e3438e6bf/boundaries/untrusted-input-guardrails.yaml#L13-L35
[zn-shim]: https://github.com/zenitysec/openclaw-security-platform/blob/bc6d2aeb89330c458e5c60e217153fa4c98168ad/shim/src/index.ts#L25-L48
[nm-acp]: https://noma.security/solutions/agent-control-plane
[nm-dr]: https://noma.security/products/ai-dr
[noma-hook]: https://github.com/Noma-Security/noma-marketplace/blob/6e195a56659fac4795247d3a10b5934117e4f6fa/guardrails/scripts/hook.py#L88-L106
[noma-tx]: https://github.com/Noma-Security/noma-marketplace/blob/6e195a56659fac4795247d3a10b5934117e4f6fa/guardrails/scripts/common/transport.py#L27-L73
[ls-site]: https://www.lasso.security/
[ls-mgr]: https://github.com/lasso-security/mcp-gateway/blob/7e7f1f6e5314819b3d0928128bb88eaea874b600/mcp_gateway/plugins/manager.py#L225-L281
[ls-plugin]: https://github.com/lasso-security/mcp-gateway/blob/7e7f1f6e5314819b3d0928128bb88eaea874b600/mcp_gateway/plugins/guardrails/lasso.py#L196-L284
[iv-readme]: https://github.com/invariantlabs-ai/invariant/blob/2340fe2d9cd619f73d5b67fa05bf8a08c7cad515/README.md
[iv-gw]: https://github.com/invariantlabs-ai/invariant-gateway/blob/9baeade022cc55de2412ba3dcae98069bd6f794a/gateway/integrations/guardrails.py#L129-L165
[iv-mcp]: https://github.com/invariantlabs-ai/invariant-gateway/blob/9baeade022cc55de2412ba3dcae98069bd6f794a/gateway/mcp/mcp_transport_base.py#L245-L286
[iv-ref]: https://invariantlabs-ai.github.io/docs/mcp-scan/guardrails-reference/
[iv-df]: https://github.com/invariantlabs-ai/invariant/blob/2340fe2d9cd619f73d5b67fa05bf8a08c7cad515/invariant/analyzer/runtime/input.py#L66-L119
[iv-eval]: https://github.com/invariantlabs-ai/invariant/blob/2340fe2d9cd619f73d5b67fa05bf8a08c7cad515/invariant/analyzer/runtime/evaluation.py#L556-L567
[iv-pi]: https://github.com/invariantlabs-ai/invariant/blob/2340fe2d9cd619f73d5b67fa05bf8a08c7cad515/invariant/analyzer/runtime/utils/prompt_injections.py#L7-L57
[iv-snyk]: https://snyk.io/news/snyk-acquires-invariant-labs-to-accelerate-agentic-ai-security-innovation/
[sn-scan]: https://github.com/snyk/agent-scan/blob/2d3ca361e33452dcfb8e74f7b7db6db0ee08d59e/src/agent_scan/cli.py#L479
[f5-scan]: https://docs.aisecurity.f5.com/operations/post_scans.html
[f5-ngf]: https://docs.nginx.com/nginx-gateway-fabric/how-to/f5-ai-guardrails/
[f5-custom]: https://docs.aisecurity.f5.com/api-docs/creating-custom-scanner.html
[f5-audit]: https://docs.aisecurity.f5.com/api-docs/getting-audit-logs.html
[f5-sec]: https://www.sec.gov/Archives/edgar/data/0001048695/000104869526000051/ffiv-20260331.htm
[pi-lite]: https://github.com/BerriAI/litellm/blob/10444df3a0173a99ab4e4858ce6777f31530e6c5/litellm/proxy/guardrails/guardrail_hooks/pillar/pillar.py#L189-L194
[pi-plat]: https://www.pillar.security/platform
[sn-rel]: https://www.servicenow.com/community/ai-control-tower-articles/what-s-new-in-ai-control-tower-for-august-amp-september-2026/ta-p/3597749
[sn-faq]: https://www.servicenow.com/community/ai-control-tower-articles/ai-gateway-faq/ta-p/3587429

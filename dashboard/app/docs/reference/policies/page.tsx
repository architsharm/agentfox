import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, DemoAgentNames, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Policy language",
  description:
    "The policy YAML schema, every condition and effect, the four shipped packs rule by rule, the hierarchy, and how to write, check, load and roll out your own.",
  path: "/docs/reference/policies",
});

type PackRule = { id: string; effect: string; severity: string; what: string };

function PackTable({ rules }: { rules: PackRule[] }) {
  return (
    <div className="docs-table" tabIndex={0}><table>
      <thead>
        <tr>
          <th>Rule</th>
          <th>Effect</th>
          <th>Severity</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        {rules.map((r) => (
          <tr key={r.id}>
            <td><code>{r.id}</code></td>
            <td>{r.effect}</td>
            <td>{r.severity}</td>
            <td>{r.what}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}

const BASELINE: PackRule[] = [
  { id: "injection.direct", effect: "block", severity: "high", what: "Injection or jailbreak in the user's input, score 0.7 or more." },
  { id: "injection.indirect", effect: "block", severity: "critical", what: "Injection in retrieved content or a tool result, at the lower bar of 0.6: an instruction has no business being in data." },
  { id: "injection.system_prompt_leak", effect: "block", severity: "medium", what: "An attempt to extract the system prompt, on any surface." },
  { id: "injection.memory_and_agent_message", effect: "block", severity: "critical", what: "Injection in a memory write or a message from another agent." },
  { id: "injection.adopted_in_reasoning", effect: "block", severity: "critical", what: "Instruction-like text in the model's own reasoning, at 0.4: evidence the model took the payload up." },
  { id: "secrets.block", effect: "block", severity: "critical", what: "A credential anywhere, in either direction, at 0.9." },
  { id: "pii.outbound_redact", effect: "redact (mask)", severity: "medium", what: "Personal data in a response is masked before it is delivered." },
  { id: "pii.inbound_tokenize", effect: "tokenize", severity: "medium", what: "Personal data in a prompt is replaced with tokens before it reaches the model." },
  { id: "pii.high_sensitivity", effect: "block", severity: "critical", what: "A US Social Security number, anywhere." },
  { id: "pii.memory_and_agent_message", effect: "redact (mask)", severity: "medium", what: "Personal data in a memory write or an inter-agent message is masked." },
  { id: "safety.harm", effect: "block", severity: "high", what: "Unsafe content (harm, self-harm, illicit, harassment, extremism)." },
  { id: "schema.violation", effect: "block", severity: "medium", what: "A response that does not match the output schema it was declared with." },
  { id: "pipeline.degraded_high_risk", effect: "escalate", severity: "medium", what: "A high-risk or prohibited-tier agent served while detectors were degraded." },
];

const CONTAINMENT: PackRule[] = [
  { id: "taint.irreversible_tool", effect: "escalate", severity: "critical", what: "An irreversible tool whose arguments came from anything other than the user." },
  { id: "taint.high_impact_tool", effect: "escalate", severity: "high", what: "The same for a high-impact tool." },
  { id: "taint.write_from_tool_result", effect: "escalate", severity: "medium", what: "A write whose arguments were copied out of a tool result, a sub-agent or memory." },
  { id: "capability.denied", effect: "block", severity: "high", what: "No grant for this tool: default deny. The reason names the command that fixes it." },
  { id: "capability.constraint_violated", effect: "block", severity: "high", what: "A grant exists, but an argument is outside a limit it declares." },
  { id: "capability.approval_required", effect: "escalate", severity: "medium", what: "The grant says a person signs off, or an argument's provenance is worse than the grant allows." },
  { id: "intent.undeclared_irreversible", effect: "escalate", severity: "medium", what: "An irreversible tool call with no declared task." },
  { id: "budget.exceeded", effect: "block", severity: "medium", what: "The agent ran out of calls, tokens, spend or recursion depth." },
  { id: "loop.runaway", effect: "block", severity: "medium", what: "The agent is repeating the same tool call without progress." },
  { id: "completion.unverified_claim", effect: "escalate", severity: "high", what: "The agent says it is finished without reporting that the work was verified." },
  { id: "completion.irreversible_unconfirmed", effect: "block", severity: "critical", what: "A run with a destructive or admin action ends without confirmation that it succeeded." },
  { id: "tool.not_declared", effect: "escalate", severity: "high", what: "A tool the registry has never seen: invented by the model, or real and undeclared." },
  { id: "action.remote_code_execution", effect: "block", severity: "critical", what: "A download piped straight into a shell or interpreter." },
  { id: "secrets.credential_file", effect: "block", severity: "high", what: "A command touching .env, an SSH key, cloud credentials, a kubeconfig or a service-account file." },
  { id: "action.supply_chain_publish", effect: "escalate", severity: "high", what: "Publishing a package or image." },
  { id: "action.infrastructure_mutation", effect: "escalate", severity: "high", what: "terraform, kubectl, helm or a cloud CLI changing live infrastructure." },
  { id: "action.history_rewrite", effect: "escalate", severity: "medium", what: "A hard reset, force clean or dropped stash." },
  { id: "control_plane.tamper", effect: "block", severity: "critical", what: "A command that would switch AgentFox's own enforcement off. The pack refuses to load without it." },
  { id: "cascade.reaches_destructive", effect: "block", severity: "critical", what: "A harmless-looking call that reaches a destructive tool through its declared triggers." },
  { id: "cascade.reaches_notification", effect: "escalate", severity: "high", what: "A call whose declared triggers reach only a message that cannot be recalled (a tool declared effect: communication), and nothing more destructive." },
  { id: "cascade.cycle", effect: "block", severity: "critical", what: "The declared trigger graph loops." },
  { id: "cascade.blast_radius", effect: "escalate", severity: "high", what: "The declared trigger graph is unusually deep or wide." },
  { id: "access.unscoped_table", effect: "block", severity: "critical", what: "A query on a table with per-customer rows and no predicate binding it to the caller." },
  { id: "access.undeclared_table", effect: "escalate", severity: "high", what: "A query on a table with no scope declaration." },
  { id: "injection.in_tool_arguments", effect: "block", severity: "critical", what: "Injection inside tool arguments (see the note under the table)." },
  { id: "secrets.in_tool_arguments", effect: "block", severity: "critical", what: "A credential inside tool arguments." },
];

const EU: PackRule[] = [
  { id: "eu.art14.human_oversight", effect: "escalate", severity: "high", what: "Any irreversible tool call by a high-risk agent goes to a person." },
  { id: "eu.art14.no_covert_action", effect: "block", severity: "critical", what: "Content telling a high-risk agent to act without informing the user." },
  { id: "eu.art15.no_degraded_enforcement", effect: "block", severity: "high", what: "A high-risk agent served while detectors were degraded." },
  { id: "eu.art15.injection_resistance", effect: "block", severity: "critical", what: "Injection against a high-risk agent, at 0.5." },
  { id: "eu.art10.special_category_data", effect: "block", severity: "critical", what: "Personal data in a high-risk agent's prompt." },
  { id: "eu.art50.impersonation", effect: "escalate", severity: "medium", what: "Review of an answer that claims to be a person (\"I'm a real person\", \"I am not a bot\"): the disclosure.claims_human risk. Lexical, so it escalates rather than blocks." },
  { id: "eu.art5.prohibited_tier", effect: "block", severity: "critical", what: "An agent classified prohibited is refused on every call." },
];

const CODING: PackRule[] = [
  { id: "code.injection_in_fetched_content", effect: "block", severity: "critical", what: "Injection in a tool result or fetched content, at 0.5 rather than 0.6." },
  { id: "code.secret_in_fetched_content", effect: "block", severity: "high", what: "A credential coming back from a tool, at 0.7: once it is in context it can leak later." },
  { id: "code.injection_adopted", effect: "escalate", severity: "critical", what: "A directive in the model's reasoning, at 0.3." },
  { id: "code.injection_in_operator_turn", effect: "escalate", severity: "medium", what: "Injection in the operator's own turn, usually a pasted log or issue." },
  { id: "code.pii_out_of_a_developer_machine", effect: "escalate", severity: "high", what: "Personal data in a tool call's arguments from a coding session." },
];

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Policy language</h1>
      <p className="docs-lede">
        Policies are YAML files of rules: a condition, an effect, a reason. This page lists
        every field and condition, the shipped packs rule by rule, grants and their limits,
        business rules, imported policies, and how to roll out a change.
      </p>

      <h2 id="document">The document</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Field</th><th>Values</th><th>Default</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>key</code></td><td>text</td><td>required</td><td>Unique id. A project pack with the key of a shipped pack replaces it.</td></tr>
          <tr><td><code>name</code>, <code>description</code></td><td>text</td><td><code>&quot;&quot;</code></td><td>For people.</td></tr>
          <tr><td><code>version</code></td><td>integer</td><td><code>1</code></td><td>The first stored version number. Saving a changed body stores a new immutable version; decisions record the version in force.</td></tr>
          <tr><td><code>mode</code></td><td><code>observe</code> | <code>enforce</code></td><td><code>observe</code></td><td>The mode the pack is bound in when first loaded. Afterwards the binding decides (<code>agentfox policy enforce</code> / <code>observe</code>).</td></tr>
          <tr><td><code>default_effect</code></td><td>an effect</td><td><code>allow</code></td><td>The verdict when no rule fires.</td></tr>
          <tr><td><code>fail_mode</code></td><td><code>open</code> | <code>closed</code></td><td><code>open</code></td><td>What a detector timeout or error does to this pack&apos;s checks: see <a href="#fail-mode">fail_mode</a>.</td></tr>
          <tr><td><code>scope</code></td><td><code>{"{agents: [globs], environments: [names]}"}</code></td><td><code>{"{}"}</code></td><td>Which agents and environments the pack applies to at runtime. Empty means all.</td></tr>
          <tr><td><code>rules</code></td><td>list</td><td><code>[]</code></td><td>The rules.</td></tr>
        </tbody>
      </table></div>

      <h2 id="rule">A rule</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Field</th><th>Default</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>id</code></td><td>required</td><td>Unique within the pack, dotted by family: <code>billing.large_export</code>. Decisions, findings and the explanation name it.</td></tr>
          <tr><td><code>description</code></td><td><code>&quot;&quot;</code></td><td>For authors.</td></tr>
          <tr><td><code>when</code></td><td>matches everything</td><td>A condition. Every field present must match; absent fields are ignored.</td></tr>
          <tr><td><code>effect</code></td><td><code>block</code></td><td>See <a href="#effects">effects</a>.</td></tr>
          <tr><td><code>reason</code></td><td>generated</td><td>Shown to the caller and written to the audit log. Write it for a person. When empty, one is generated from what matched.</td></tr>
          <tr><td><code>severity</code></td><td><code>medium</code></td><td><code>critical</code>, <code>high</code>, <code>medium</code> or <code>low</code>. Becomes the finding&apos;s severity.</td></tr>
          <tr><td><code>controls</code></td><td><code>[]</code></td><td>Control ids this rule is evidence for, in the compliance catalog.</td></tr>
          <tr><td><code>enabled</code></td><td><code>true</code></td><td>A disabled rule never fires (and lint says so).</td></tr>
          <tr><td><code>redaction</code></td><td><code>mask</code></td><td>The style used when the effect is <code>redact</code>, <code>mask</code> or <code>tokenize</code>.</td></tr>
          <tr><td><code>overridable</code></td><td><code>false</code></td><td>Whether a narrower level of the hierarchy may weaken this rule.</td></tr>
        </tbody>
      </table></div>

      <h2 id="effects">Effects</h2>
      <p>When several rules fire, across all bound packs, the strongest effect wins:</p>
      <Code lang="text" copy={false}>{`allow < tokenize < mask < redact < abstain < escalate < block`}</Code>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Effect</th><th>What happens when enforced</th></tr>
        </thead>
        <tbody>
          <tr><td><code>allow</code></td><td>Nothing. A rule that allows cannot cancel a stronger rule elsewhere.</td></tr>
          <tr><td><code>tokenize</code>, <code>mask</code>, <code>redact</code></td><td>The matched spans are replaced and the call goes on with the rewritten content.</td></tr>
          <tr><td><code>abstain</code></td><td>The answer is withheld without treating the user as an attacker.</td></tr>
          <tr><td><code>escalate</code></td><td>An approval is created and the call waits for a person (<code>ApprovalRequired</code>, HTTP 202).</td></tr>
          <tr><td><code>block</code></td><td>Refused (<code>PolicyViolation</code>, <code>agentfox.Blocked</code>, HTTP 403).</td></tr>
        </tbody>
      </table></div>
      <p>
        In <strong>observe</strong> a pack still evaluates and records what it would
        have done: the decision&apos;s <code>verdict</code> is <code>allow</code> and its{" "}
        <code>effective_verdict</code> is the strongest effect that fired. That
        difference is what <code>agentfox findings</code> reports as &quot;would have
        been blocked&quot;.
      </p>

      <h2 id="decision-order">How a tool call is decided</h2>
      <ol>
        <li>Which agent is calling, and is it stopped (quarantine or kill switch)?</li>
        <li>Does it hold a <a href="#grants">grant</a> for the tool, and do the arguments fit its limits? No grant: refused.</li>
        <li>What is the tool&apos;s impact, and the <a href="#provenance">provenance</a> of its arguments? Untrusted values in an irreversible call escalate.</li>
        <li>Composition (a value from one tool passed into a higher-impact one), declared intent, loops and budget.</li>
        <li>What the detectors found in the arguments, under each detection rule&apos;s pack mode.</li>
      </ol>
      <p>
        The strongest effect wins and is written to the audit chain. Steps 2 and 3 read no
        text, so they hold when a detector misses. Content is checked on nine{" "}
        <Link href="/docs/reference/detectors#surfaces">surfaces</Link>.
      </p>

      <h3 id="provenance">Provenance</h3>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Level</th><th>The value came from</th></tr>
        </thead>
        <tbody>
          <tr><td><code>none</code></td><td>No external origin.</td></tr>
          <tr><td><code>user</code></td><td>The user&apos;s message.</td></tr>
          <tr><td><code>retrieved</code></td><td>A retrieved document.</td></tr>
          <tr><td><code>tool_result</code></td><td>Another tool&apos;s output, such as a fetched page.</td></tr>
          <tr><td><code>subagent</code></td><td>Another agent.</td></tr>
          <tr><td><code>memory</code></td><td>The agent&apos;s long-term memory.</td></tr>
        </tbody>
      </table></div>
      <p>
        Ordered from most to least trusted; everything after <code>user</code> is untrusted.{" "}
        <code>auto()</code> reads it from the conversation (a value copied out of a{" "}
        <code>role=&quot;tool&quot;</code> message is a tool result); over HTTP the caller
        declares it (<code>provenance</code>, <code>X-AgentFox-Trust</code>), and what is
        declared is believed.
      </p>

      <h2 id="conditions">Conditions (<code>when</code>)</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Key</th><th>Type</th><th>Matches when</th></tr>
        </thead>
        <tbody>
          <tr><td><code>surface</code></td><td>list</td><td>The content is on one of these surfaces: <code>input</code>, <code>output</code>, <code>tool_args</code>, <code>tool_result</code>, <code>retrieved</code>, <code>memory_write</code>, <code>agent_message</code>, <code>completion</code>, <code>reasoning</code>. See <Link href="/docs/reference/detectors#surfaces">surfaces</Link>.</td></tr>
          <tr><td><code>environment</code></td><td>list</td><td>The call&apos;s environment is listed.</td></tr>
          <tr><td><code>agent</code></td><td>glob</td><td>The agent slug matches, e.g. <code>support-*</code>.</td></tr>
          <tr><td><code>risk_tier</code></td><td>list</td><td>The agent&apos;s risk tier is listed: <code>minimal</code>, <code>limited</code>, <code>high</code>, <code>prohibited</code>.</td></tr>
          <tr><td><code>tool</code></td><td>glob</td><td>The tool key matches, e.g. <code>billing.*</code> or <code>mcp:helpdesk/*</code>.</td></tr>
          <tr><td><code>tool_impact</code></td><td>list</td><td>The tool&apos;s declared impact is listed: <code>read</code>, <code>write</code>, <code>high_impact</code>, <code>irreversible</code>.</td></tr>
          <tr><td><code>tool_known</code></td><td>bool</td><td><code>false</code> matches a tool the registry has never seen.</td></tr>
          <tr><td><code>detection</code></td><td>object</td><td>At least <code>min_count</code> (default 1) detections scored at or above <code>min_score</code> (default 0.5) whose entity equals <code>entity</code> (e.g. <code>PII.CREDIT_CARD</code>) or starts with <code>entity_prefix</code> (e.g. <code>INJECTION</code>). Entity types are listed in <Link href="/docs/reference/detectors#entities">Detectors</Link>.</td></tr>
          <tr><td><code>argument</code></td><td>object</td><td>The tool argument at <code>path</code> (dotted, with <code>[0]</code> for list items) compared with <code>value</code> by <code>op</code>: <code>eq</code>, <code>ne</code>, <code>gt</code>, <code>gte</code>, <code>lt</code>, <code>lte</code>, <code>in</code>, <code>not_in</code>, <code>contains</code> (case-insensitive substring), <code>matches</code> (regular-expression search). A missing argument never matches.</td></tr>
          <tr><td><code>taint_exceeds</code></td><td>level</td><td>The worst provenance of the call&apos;s content or arguments is above this level, in the order <code>none &lt; user &lt; retrieved &lt; tool_result &lt; subagent &lt; memory</code>.</td></tr>
          <tr><td><code>capability</code></td><td>state</td><td>The grant check came out <code>denied</code> (no grant), <code>constraint_violated</code> (a grant, but an argument outside its limit), <code>requires_approval</code> or <code>granted</code>.</td></tr>
          <tr><td><code>action_operation</code></td><td>list</td><td>What an SQL, shell or HTTP argument does: <code>read</code>, <code>write</code>, <code>destructive</code>, <code>admin</code>, <code>unknown</code>.</td></tr>
          <tr><td><code>blast_radius_at_least</code></td><td>level</td><td>The estimated blast radius is at least this, in the order <code>none &lt; bounded &lt; unknown &lt; unbounded &lt; catastrophic</code>.</td></tr>
          <tr><td><code>action_reversible</code></td><td>bool</td><td>The analysed action is (or is not) reversible.</td></tr>
          <tr><td><code>action_risk</code></td><td>glob</td><td>Any risk code found in the call matches, e.g. <code>sql.*</code>, <code>shell.destructive</code>, <code>remote-code-execution</code>, <code>unscoped-table</code>, <code>control_flow.*</code>, <code>crescendo.trajectory_drift</code>. Codes appear in a decision&apos;s explanation.</td></tr>
          <tr><td><code>budget_exceeded</code></td><td>bool</td><td>The agent&apos;s call, token, spend or depth budget is exhausted.</td></tr>
          <tr><td><code>loop_detected</code></td><td>bool</td><td>The loop governor saw a repeating call with no progress.</td></tr>
          <tr><td><code>intent_declared</code></td><td>bool</td><td>The caller did (or did not) declare a task intent.</td></tr>
          <tr><td><code>detector_degraded</code></td><td>bool</td><td>A detector timed out, errored or was skipped for budget on this call.</td></tr>
          <tr><td><code>completion_requires</code></td><td>list</td><td>On the <code>completion</code> surface: any named fact was not reported as true by the caller. Scope the rule with <code>surface: [completion]</code>.</td></tr>
          <tr><td><code>expr</code></td><td>text</td><td>An escape hatch: a Python expression over <code>agent</code>, <code>surface</code>, <code>tool</code>, <code>impact</code>, <code>risk_tier</code>, <code>environment</code>, <code>n_detections</code>, <code>max_score</code>, <code>prior_tool_count</code>, <code>taint</code>, with no builtins. Lint cannot reason about it and it does not compile to Rego meaningfully; avoid it.</td></tr>
        </tbody>
      </table></div>

      <h3 id="built-in">Refusals that are not policy rules</h3>
      <p>
        Some refusals happen whatever mode your packs are in, because they are facts
        about the call rather than opinions: a capability check with no grant (default
        deny once the agent holds any grant, and always in the SDK and gateway), a
        critical action risk such as <code>shell.destructive</code> or{" "}
        <code>sql.unbounded_mutation</code>, an SQL argument that cannot be analysed
        because the <code>[sql]</code> extra is missing (<code>analysis.unavailable</code>,
        which fails closed), composed privilege escalation, and MCP schema drift. With{" "}
        <code>tool-containment</code> demoted to observe, both of these still block:
      </p>
      <Output>{`db.query PolicyViolation [('analysis.unavailable', 'enforce')]
shell.run PolicyViolation [('shell.destructive', 'enforce')]`}</Output>
      <p>
        With <code>sqlglot</code> installed (<code>pip install &quot;agentfox[sql]&quot;</code>)
        the same <code>DELETE FROM tickets</code> is analysed and refused as{" "}
        <code>sql.unbounded_mutation</code> instead.
      </p>

      <h2 id="packs">The shipped packs</h2>
      <p>
        <code>agentfox init</code> loads <code>agent-integrity</code>, <code>baseline</code>,{" "}
        <code>eu-ai-act-high-risk</code> and <code>tool-containment</code>, every one watching
        (<code>observe</code>) until you turn it to blocking with{" "}
        <code>agentfox policy enforce &lt;key&gt;</code>; a pack someone switched to blocking
        stays blocking when <code>init</code> or <code>up</code> runs again. In{" "}
        <code>policy packs</code> the mode is the one the file declares; in{" "}
        <code>policy list</code> it is the one in force. <code>coding-agent</code> is loaded only for
        agents with coding-agent hooks installed (<code>agentfox admin hooks install</code>,
        see <Link href="/docs/connect/coding-agents">Coding agents</Link>).
      </p>
      <Code>{`agentfox policy packs
agentfox policy list`}</Code>
      <Output>{`pack                 origin   mode     rules  file
agent-integrity      shipped  observe  3      …/agentfox/packs/agent-integrity/policies/agent-integrity.yaml
baseline             shipped  observe  13     …/agentfox/packs/baseline/policies/baseline.yaml
coding-agent         shipped  observe  10     …/agentfox/packs/coding-agent/policies/coding-agent.yaml
eu-ai-act-high-risk  shipped  observe  7      …/agentfox/packs/eu-ai-act/policies/eu-ai-act-high-risk.yaml
tool-containment     shipped  enforce  26     …/agentfox/packs/tool-containment/policies/tool-containment.yaml

policy               version  mode     rules
agent-integrity      v1       observe  3
baseline             v1       observe  13
eu-ai-act-high-risk  v1       observe  7
tool-containment     v1       observe  26`}</Output>

      <h3 id="capability-packs">Capability packs</h3>
      <p>
        Each shipped policy file lives in a capability pack: a directory with a{" "}
        <code>pack.yaml</code> (id, version, maturity, owners, compliance mappings,
        vocabulary) and the policies, controls, business-ladder templates, red-team probes,
        golden cases and fixtures one use case needs. Besides these four, AgentFox ships{" "}
        <code>eu-ai-act</code> (which carries <code>eu-ai-act-high-risk</code> and the risk
        classes), <code>compliance/catalog</code> (the control catalog),{" "}
        <code>payments/refunds</code> and <code>customer-support</code>. Your own go in{" "}
        <code>.agentfox/packs/</code>; only <code>stable</code> packs load unless{" "}
        <code>pack_maturity</code> says otherwise.
      </p>
      <Code>{`agentfox policy packs list
agentfox policy packs show payments/refunds
agentfox policy packs test
agentfox policy packs new payments/chargebacks
agentfox policy packs validate .agentfox/packs/payments/chargebacks`}</Code>

      <h3 id="pack-baseline">baseline: content guardrails (observe)</h3>
      <p>Detection-driven rules on every surface. Ships in observe: read what it would have done, then promote it.</p>
      <PackTable rules={BASELINE} />

      <h3 id="pack-tool-containment">tool-containment: what an agent may do</h3>
      <p>
        Rules about the action and where its arguments came from, which hold when a
        detector misses. The file declares <code>enforce</code>, but <code>agentfox init</code>{" "}
        binds it watching like every pack; <code>agentfox policy enforce tool-containment</code>{" "}
        starts it blocking. The pack cannot be loaded with <code>control_plane.tamper</code>{" "}
        removed or disabled.
      </p>
      <p id="built-in-containment">
        Its mode also decides two checks the enforcer makes itself, listed under Tool containment
        on the Policies page: <code>capability.default_deny</code> (a tool the agent was not
        granted; <code>agentfox.auto()</code> applies it once the agent holds any grant) and <code>composition.escalation</code> (a value a
        lower-impact tool returned, used by a tool that changes more). While the pack watches, or
        where it is not applied, both are recorded as would-block and the call goes through. A
        limit or &quot;Ask first&quot; a person set on a grant applies at once, whatever the mode.
      </p>
      <PackTable rules={CONTAINMENT} />
      <Callout kind="note" title="injection.in_tool_arguments">
        <p>
          The heuristic injection detector (<code>injection.heuristic</code>) runs on the{" "}
          <code>tool_args</code> surface, reading the call&apos;s arguments as JSON, so an
          instruction smuggled into an argument fires this rule. It is a lexical check:
          taint and grants still contain the call when the wording gets past it.
        </p>
      </Callout>

      <h3 id="pack-eu">eu-ai-act-high-risk (observe)</h3>
      <p>
        Measures for agents classified <code>high</code> (and a hard stop for{" "}
        <code>prohibited</code>). They only fire for agents whose risk tier says so.
        The article mappings are drafts, not legal advice.
      </p>
      <PackTable rules={EU} />

      <h3 id="pack-coding">coding-agent (observe)</h3>
      <p>Lower thresholds for an agent that reads diffs and runs shell commands on a developer&apos;s machine.</p>
      <PackTable rules={CODING} />

      <h2 id="custom">Write and load your own</h2>
      <p>
        Put a YAML file in <code>.agentfox/policies/</code> at the root of your
        repository. <code>agentfox init</code> (safe to run again) loads it alongside
        the shipped packs, and it travels with the code through review like anything
        else. A file whose <code>key</code> equals a shipped pack&apos;s replaces that
        pack. It is loaded watching, whatever its <code>mode:</code> says; promote it with{" "}
        <code>agentfox policy enforce &lt;key&gt;</code>. <code>agentfox init --server</code>{" "}
        (an account) does not load these files: a setup key only maps the agent, so it lists
        them and prints the command that loads each one with your account key.
      </p>
      <Code lang="yaml" title=".agentfox/policies/support-desk.yaml">{`key: support-desk
name: Support desk rules
description: Rules for the agents that answer customer tickets.
version: 1
mode: enforce
fail_mode: open
scope:
  agents: ["support-*"]

rules:
  - id: email.outside_domain
    description: Email to an address outside example.com needs a person.
    when:
      tool: email.send
      argument: {path: to, op: matches, value: "@(?!example\\\\.com$)"}
    effect: escalate
    severity: high
    reason: "Email to a recipient outside example.com; a person must approve it."

  - id: billing.large_export
    description: Exports over 10,000 rows are refused.
    when:
      tool: "billing.*"
      argument: {path: rows, op: gt, value: 10000}
    effect: block
    severity: high
    reason: "Billing exports are capped at 10,000 rows."

  - id: crm.write_from_untrusted
    description: A CRM write whose arguments came from a web page or a tool result.
    when:
      tool: "crm.*"
      tool_impact: [write, high_impact, irreversible]
      taint_exceeds: user
    effect: escalate
    severity: high
    reason: "CRM write carries data the user did not type."

  - id: output.card_number
    description: A card number never goes back to a customer.
    when:
      surface: [output]
      detection: {entity: PII.CREDIT_CARD, min_score: 0.9}
    effect: block
    severity: critical
    reason: "Card number in a reply to a customer."`}</Code>

      <h3 id="validate">Check it, load it</h3>
      <Code>{`agentfox policy validate .agentfox/policies/support-desk.yaml
agentfox init
agentfox policy lint`}</Code>
      <Output>{`valid — support-desk v1, 4 rules, mode=enforce
  controls: []
  compiles to 73 lines of Rego
…
  ✓ 5 policy packs loaded
      agent-integrity          observe  recorded, nothing blocked
      baseline                 observe  recorded, nothing blocked
      eu-ai-act-high-risk      observe  recorded, nothing blocked
      support-desk             observe  recorded, nothing blocked
      tool-containment         observe  recorded, nothing blocked
…
no policy issues`}</Output>
      <p>
        <code>policy validate FILE</code> checks one file offline: the schema, the
        effects and operators, that it compiles, and the full lint. <code>policy lint
        FILE…</code> lints files before they are loaded; with no file it lints every
        bound pack and every hierarchy layer together, so run it after{" "}
        <code>init</code> too. Lint catches a rule whose conditions can never be true, a
        condition naming a value no request carries (<code>surface: [input,
        toolargs]</code> still fires on input, but <code>toolargs</code> is a typo),
        duplicate ids, over-broad globs, rules with no conditions, and illegal
        loosening. Both exit 1 on critical or high findings, so either can gate a pull
        request:
      </p>
      <Code lang="yaml" title=".agentfox/policies/typos.yaml">{`key: typos
name: A pack with mistakes
mode: observe
rules:
  - id: pii.reply
    when:
      surface: [outputs]
      detection: {entity_prefix: PII}
    effect: redact
  - id: tools.everything
    when:
      tool: "*"
    effect: escalate`}</Code>
      <Output>{`$ agentfox policy validate .agentfox/policies/typos.yaml
invalid: typos — 1 blocking finding(s)
…
$ agentfox policy lint .agentfox/policies/typos.yaml
severity  code             rule              level  message
high      unreachable      pii.reply         org    'pii.reply' can never fire: every value in \`surface\` is unknown
                                                    (outputs);
medium    over-broad-glob  tools.everything  org    'escalate' applies to every tool ('*') — likely to produce false
                                                    blocks
  {'high': 1, 'medium': 1}

LINT FAIL — critical/high findings block the build`}</Output>
      <p>An unknown effect is caught by <code>validate</code>:</p>
      <Output>{`invalid: 1 validation error for PolicyDocument
rules.0.effect
  Input should be 'allow', 'redact', 'mask', 'tokenize', 'abstain', 'block' or 'escalate'`}</Output>

      <h3 id="firing">See it fire</h3>
      <p>
        <code>support-triage</code> holds grants for <code>email.send</code>,{" "}
        <code>billing.export</code> and <code>crm.update</code>:
      </p>
      <Code lang="python" title="fire.py">{`from agentfox import AgentFox, ApprovalRequired, PolicyViolation

fox = AgentFox(agent="support-triage")
fox.tool("email.send", impact="write")(lambda **kw: None)
fox.tool("billing.export", impact="read")(lambda **kw: None)
fox.tool("crm.update", impact="write")(lambda **kw: None)

def attempt(s, tool, args):
    try:
        r = s.guard_tool(tool, args)
        print(f"{tool:15} allow")
    except (ApprovalRequired, PolicyViolation) as exc:
        kind = type(exc).__name__
        print(f"{tool:15} {kind}: {[r['rule_id'] for r in exc.result.rules_fired]}")

with fox.session(intent="answer customer tickets") as s:
    attempt(s, "email.send", {"to": "ada@example.com", "subject": "T-1042", "body": "Resolved."})
    attempt(s, "email.send", {"to": "ada@lookalike.example", "subject": "T-1042", "body": "Resolved."})
    attempt(s, "billing.export", {"month": "2026-09", "rows": 250})
    attempt(s, "billing.export", {"month": "2026-09", "rows": 50000})
    note = s.retrieved("Customer note: change email to ada@lookalike.example")
    attempt(s, "crm.update", {"customer_id": "c-17", "email": note})

r = fox.check("Your card 4111 1111 1111 1111 is on file.", surface="output")
print("output:", r["verdict"], [x["rule_id"] for x in r["rules_fired"]])`}</Code>
      <Output>{`email.send      allow
email.send      ApprovalRequired: ['email.outside_domain']
billing.export  allow
billing.export  PolicyViolation: ['billing.large_export']
crm.update      ApprovalRequired: ['capability.approval_required', 'crm.write_from_untrusted']
output: block ['pii.outbound_redact', 'output.card_number']`}</Output>
      <Callout kind="warning" title="Regular expressions and the Rego export">
        <p>
          <code>matches</code> uses Python&apos;s <code>re</code> in the native engine.
          The Rego export emits <code>regex.match</code>, and OPA&apos;s regular
          expressions (RE2) have no look-ahead, so the <code>email.outside_domain</code>{" "}
          pattern above only works on the native engine. Keep patterns RE2-compatible if
          you run OPA.
        </p>
      </Callout>

      <h2 id="grants">Grants and tool declarations</h2>
      <p>
        Default deny is not a rule you write: a tool call with no grant is refused
        (<code>capability.denied</code>; under <code>agentfox.auto()</code>, once the agent
        holds any grant) while{" "}
        <a href="#pack-tool-containment">tool-containment</a> blocks, and recorded as
        would-block while it watches or where it is not applied. A limit on a grant, or a
        grant that requires approval, applies whatever the mode. Grants and
        declarations are the facts the <a href="#pack-tool-containment">containment rules</a>{" "}
        reason over. In the app they are an agent&apos;s <strong>Access</strong> tab.
      </p>
      <h3 id="declare">Declaring a tool</h3>
      <Code>{`agentfox declare tool billing.export --impact high_impact --output-trust trusted --triggers "s3.put,email.send"`}</Code>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Option</th><th>Values</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>--impact</code></td><td><code>read</code> | <code>write</code> | <code>high_impact</code> | <code>irreversible</code></td><td>Required. Matched by <code>tool_impact</code> and by the <code>taint.*</code> rules.</td></tr>
          <tr><td><code>--output-trust</code></td><td><code>untrusted</code> (default) | <code>trusted</code></td><td>Whether values from this tool&apos;s output count as tool results. Declare <code>trusted</code> only for a system of record you control; it also tells <code>composition.escalation</code> the flow is intended.</td></tr>
          <tr><td><code>--triggers</code></td><td>comma-separated tool keys</td><td>What the call sets off downstream, read by the <code>cascade.*</code> rules.</td></tr>
        </tbody>
      </table></div>
      <p>
        A tool first seen in traffic is registered with an <em>inferred</em> impact: names
        with <code>send</code>, <code>delete</code>, <code>transfer</code> or{" "}
        <code>deploy</code> read as irreversible; <code>create</code>, <code>update</code>{" "}
        or <code>write</code> as write; anything else as read. A declaration always wins
        over a guess. The SDK&apos;s <code>@fox.tool(&quot;key&quot;, impact=&quot;…&quot;)</code>{" "}
        declares too.
      </p>

      <DemoAgentNames />

      <h3 id="grant-options">permit grant</h3>
      <Code>{`agentfox permit grant support-triage 'billing.*' --limit 'format:in=csv,json' --limit 'rows:lte=5000' --max-taint retrieved --requires-approval --expires-in-days 7 --yes`}</Code>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Option</th><th>Default</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>TOOL</code></td><td>required</td><td>A key or a glob (<code>tickets.*</code>, <code>mcp:github/*</code>, <code>*</code>). When several grants match, the most specific wins.</td></tr>
          <tr><td><code>--limit</code></td><td>none</td><td>Repeatable argument limit; see the operators below.</td></tr>
          <tr><td><code>--max-taint</code></td><td><code>memory</code> for a tool that only reads, <code>user</code> for any other (as the dashboard&apos;s Add)</td><td>The worst provenance an argument may carry and still run without approval: <code>none</code>, <code>user</code>, <code>retrieved</code>, <code>tool_result</code>, <code>subagent</code>, <code>memory</code>. Above it the call escalates. Within it, the <code>taint.*</code> rules defer to the grant; <code>composition.escalation</code> does not.</td></tr>
          <tr><td><code>--requires-approval</code></td><td>off</td><td>Every matching call goes to a person first.</td></tr>
          <tr><td><code>--expires-in-days</code></td><td>no expiry</td><td>The grant stops matching after N days.</td></tr>
          <tr><td><code>--action</code></td><td>every action</td><td>Limit the grant to named actions on the tool. Repeatable.</td></tr>
          <tr><td><code>--granted-by</code></td><td>you</td><td>Who is accountable, recorded in the audit chain.</td></tr>
        </tbody>
      </table></div>
      <p>
        The agent must already exist (it appears the first time it sends traffic). Every
        grant and revocation (<code>agentfox permit revoke CAP_ID</code>) is on the audit
        chain. <code>agentfox policy proposals from-traffic</code> drafts grants from
        recorded calls; limits are learned only from calls no detector or provenance rule
        flagged, and a tool declaration needs a second approver.
      </p>

      <h3 id="limit-operators">Limit operators</h3>
      <p>
        <code>path=value</code> means equal; <code>path:op=value</code> uses an operator.
        Values are read as JSON where possible (<code>1000</code> is a number,{" "}
        <code>&quot;1000&quot;</code> a string). A dotted path reaches nested arguments
        (<code>recipient.country:eq=GB</code>). A missing argument compares as null, so it
        fails an equality, list or numeric limit. An unknown operator is refused before
        anything is written.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Operator</th><th>Example</th><th>Holds when the argument is</th></tr>
        </thead>
        <tbody>
          <tr><td>(none) or <code>eq</code></td><td><code>region=eu</code></td><td>exactly that value</td></tr>
          <tr><td><code>ne</code></td><td><code>status:ne=closed</code></td><td>anything but that value</td></tr>
          <tr><td><code>lt</code>, <code>lte</code></td><td><code>rows:lte=5000</code></td><td>below / at most, numerically</td></tr>
          <tr><td><code>gt</code>, <code>gte</code></td><td><code>priority:gte=2</code></td><td>above / at least, numerically</td></tr>
          <tr><td><code>in</code></td><td><code>format:in=csv,json</code></td><td>one of a comma-separated list</td></tr>
          <tr><td><code>not_in</code></td><td><code>queue:not_in=legal,security</code></td><td>none of the list</td></tr>
          <tr><td><code>contains</code></td><td><code>subject:contains=ticket</code></td><td>text containing it, case-insensitively</td></tr>
          <tr><td><code>matches</code></td><td><code>to:matches=@example\.com$</code></td><td>text matching a regular expression (search)</td></tr>
        </tbody>
      </table></div>

      <h3 id="taint-scope">Taint scope</h3>
      <p>
        <code>taint_scope</code> (<Link href="/docs/reference/config#set-taint_scope">Configuration</Link>)
        decides what provenance the rules see for a tool call. The recorded decision
        always keeps the session value and notes which scope was applied.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Value</th><th>What policy sees</th><th>Trade-off</th></tr>
        </thead>
        <tbody>
          <tr><td><code>session</code> (default)</td><td>The worst provenance anywhere in the run so far, plus the call&apos;s own arguments.</td><td>Contains injections that steer an argument without copying text. Escalates more honest calls.</td></tr>
          <tr><td><code>argument</code></td><td>Only what this call&apos;s arguments were copied from.</td><td>Lets honest calls through after the agent read the web. Misses an injection whose text never lands in an argument.</td></tr>
        </tbody>
      </table></div>

      <h2 id="business-rules">Business rules (threshold ladders)</h2>
      <p>
        A ladder bands one numeric tool argument into outcomes. It runs on the{" "}
        <code>tool_args</code> surface, after grants: a call with no grant is refused
        before the ladder matters. Its fired rule id is <code>business.&lt;key&gt;</code>.
      </p>
      <Code lang="yaml" title="credit-ladder.yaml">{`key: billing-credit-ladder
tool: billing.credit
field: arguments.amount
unit: USD
owner: finance
mode: observe
bands:
  - upto: 50
    outcome: allow
  - upto: 500
    outcome: verify
    verify:
      check: billing.credit_history
      expect: {credits_last_90d: {op: lt, value: 3}}
      on_fail: escalate
  - upto: 5000
    outcome: escalate
    approver_role: finance-lead
  - outcome: block
    reason: credits above $5,000 go through the finance system`}</Code>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Field</th><th>Default</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>key</code></td><td>required</td><td>Unique id. Applying the same key again replaces the ladder and bumps its version.</td></tr>
          <tr><td><code>name</code>, <code>description</code>, <code>owner</code></td><td><code>&quot;&quot;</code></td><td>For people. <code>owner</code> names who to ask when two ladders disagree.</td></tr>
          <tr><td><code>tool</code></td><td>every tool</td><td>Limit the ladder to one tool (a glob). Without it, every tool call carrying the field.</td></tr>
          <tr><td><code>agent</code></td><td>every agent</td><td>Scope to one registered agent (also <code>--agent</code> on apply).</td></tr>
          <tr><td><code>field</code></td><td>required</td><td>Dotted path into the request. Tool arguments are under <code>arguments</code>.</td></tr>
          <tr><td><code>unit</code></td><td><code>count</code></td><td><code>USD</code>, <code>EUR</code>, <code>GBP</code>, <code>JPY</code>, <code>USD_CENTS</code>, <code>EUR_CENTS</code>, <code>GBP_CENTS</code>, <code>count</code>, <code>days</code>.</td></tr>
          <tr><td><code>mode</code></td><td><code>observe</code></td><td>The ladder&apos;s own mode, whatever mode the packs are in. <code>--mode</code> on apply overrides it.</td></tr>
          <tr><td><code>bands</code></td><td>required</td><td>Ordered by <code>upto</code>, ascending. Each covers values above the previous <code>upto</code>, up to and including its own. The last band omits <code>upto</code>.</td></tr>
        </tbody>
      </table></div>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Band field</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>upto</code></td><td>Inclusive upper bound. Omitted on the last band.</td></tr>
          <tr><td><code>outcome</code></td><td><code>allow</code> (default), <code>verify</code>, <code>escalate</code>, <code>block</code>, <code>redact</code>.</td></tr>
          <tr><td><code>reason</code>, <code>label</code></td><td>Shown in the decision.</td></tr>
          <tr><td><code>approver_role</code></td><td>Who may approve an <code>escalate</code>.</td></tr>
          <tr><td><code>verify</code></td><td>Required for a <code>verify</code> band: <code>check</code> (the check key), <code>arguments</code>, <code>expect</code> (what passing looks like; absent means truthy), <code>on_pass</code> (default <code>allow</code>), <code>on_fail</code> and <code>on_error</code> (default <code>escalate</code>), <code>timeout_ms</code> (5000). AgentFox does not run the check: your code does, with <code>agentfox.capabilities.business.run_verification</code>.</td></tr>
        </tbody>
      </table></div>
      <ul>
        <li>When several ladders match, the strictest outcome wins. A ladder never loosens a security verdict.</li>
        <li>A missing field, a negative value, text that is not a number, or a value in another currency escalates. It never passes.</li>
        <li>
          <code>agentfox policy rules check</code> reports where two ladders on the same field
          disagree (and ladders in different units as critical), exiting 1, so it works as a CI
          step. <code>policy lint</code> does not look at ladders.
        </li>
      </ul>
      <TaskTable
        rows={[
          { task: "Save or replace a ladder", run: "agentfox policy rules apply credit-ladder.yaml", href: "/docs/reference/cli#cmd-policy-rules-apply" },
          { task: "Read back the resolved bands", run: "agentfox policy rules show billing-credit-ladder", href: "/docs/reference/cli#cmd-policy-rules-show" },
          { task: "Try values at each boundary", run: "agentfox policy rules test billing-credit-ladder 50,50.01,5000.01", href: "/docs/reference/cli#cmd-policy-rules-test" },
          { task: "Find disagreements between ladders", run: "agentfox policy rules check", href: "/docs/reference/cli#cmd-policy-rules-check" },
          { task: "Every kind of guardrail, and one in detail", run: "agentfox policy rules explain threshold_ladder", href: "/docs/reference/cli#cmd-policy-rules-explain" },
          { task: "Turn a written policy into ladders (observe)", run: "agentfox policy compile billing-policy.md --apply", href: "/docs/reference/cli#cmd-policy-compile" },
        ]}
      />
      <p>
        <code>policy compile</code> is deterministic (no model). It lists every assumption
        it made and the sentences it cannot express; <code>--apply</code> saves only the
        threshold ladders, in observe.
      </p>

      <h2 id="import">Imported policies</h2>
      <p>
        <code>agentfox policy import FILE</code> prints a plan of what a policy written for
        another engine becomes; <code>--apply</code> saves it in observe. It reads rule
        files (<code>apiVersion: governance.toolkit/v1</code>) and policy manifests
        (<code>agent_control_specification_version</code>, with their Rego from beside the
        manifest or <code>--bundle</code>; Rego is read, never executed). Over HTTP:{" "}
        <code>POST /api/import/agent-governance/plan</code>, then{" "}
        <code>/api/import/agent-governance</code> (<code>skip</code> leaves items out).
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Source</th><th>Becomes</th></tr>
        </thead>
        <tbody>
          <tr><td><code>deny</code></td><td><code>block</code></td></tr>
          <tr><td><code>require_approval</code></td><td><code>escalate</code></td></tr>
          <tr><td><code>warn</code>, <code>log</code></td><td>recorded when they fire</td></tr>
          <tr><td><code>default_action: deny</code></td><td>a <code>default-deny</code> block rule, with allow rules on the tool or agent name carved out of it</td></tr>
          <tr><td><code>default_action: allow</code></td><td>unmatched calls pass; the plan says so first</td></tr>
          <tr><td>priorities</td><td>dropped: the strongest effect wins, so an allow never overrides a block</td></tr>
          <tr><td><code>==</code>, <code>!=</code>, <code>in [...]</code>, <code>contains</code>, <code>startswith</code>, <code>endswith</code>, numeric comparisons, <code>and</code>, <code>or</code></td><td>conditions; an <code>or</code> or <code>in</code> list on the tool becomes one rule per branch</td></tr>
          <tr><td>regex or substring on message text</td><td>a custom pattern rule that detects, plus a policy rule acting on it</td></tr>
          <tr><td>Rego <code>input</code>, <code>output</code>, <code>pre_tool_call</code>, <code>post_tool_call</code></td><td>the input, output, tool-argument and tool-result surfaces</td></tr>
        </tbody>
      </table></div>
      <p>
        Not translated, and absent from the import: comparisons of two fields (unless both
        are tool, agent, surface or environment), negations, rate limits, conditions on
        context or budget, more than one argument comparison in a condition, Cedar
        policies, annotations, and conditional verdict rules in Rego.
      </p>

      <h2 id="effective">The effective policy</h2>
      <p>
        <code>agentfox policy effective</code> resolves what is in force for a subject
        and says which layer each rule came from:
      </p>
      <Code>{`agentfox policy effective --agent support-triage`}</Code>
      <Output>{`effective policy in development — default allow
  layers:
    org:*(extend)  baseline  observe
    org:*(extend)  eu-ai-act-high-risk  observe
    org:*(extend)  support-desk  enforce
    org:*(extend)  tool-containment  enforce

rule                                 effect    mode     from   overrides
access.undeclared_table              escalate  enforce  org:*  —
access.unscoped_table                block     enforce  org:*  —
…
billing.large_export                 block     enforce  org:*  —
…`}</Output>
      <p>
        Each layer is listed with its own mode, and each rule with the mode it is
        applied under: <code>enforce</code> rules block, <code>observe</code> rules are
        recorded as the effective verdict only.
      </p>

      <h2 id="hierarchy">Hierarchy: org, team, agent, user</h2>
      <p>
        A policy saved through the API can be placed at a level (<code>org</code>,{" "}
        <code>team</code>, <code>agent</code>, <code>user</code>), with a{" "}
        <code>scope_id</code> (which team, agent or user; <code>*</code> for all) and a
        compose mode:
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th><code>compose</code></th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>extend</code> (default)</td><td>Add rules; the broader levels&apos; rules still apply.</td></tr>
          <tr><td><code>restrict</code></td><td>Tighten only. A rule with the same id and a weaker effect is rejected.</td></tr>
          <tr><td><code>override</code></td><td>May weaken a rule, but only one the broader level marked <code>overridable: true</code>.</td></tr>
        </tbody>
      </table></div>
      <p>
        Packs loaded by <code>agentfox init</code> are bound at <code>org:*</code> with{" "}
        <code>extend</code>. To place one elsewhere, post it to{" "}
        <Link href="/docs/reference/api#POST--api-policies"><code>POST /api/policies</code></Link>{" "}
        with <code>level</code>, <code>scope_id</code> and <code>compose</code>. Here a
        finance team tightens PII redaction to a block, and an agent layer tries to
        switch off <code>injection.direct</code>:
      </p>
      <Code lang="python">{`import httpx
B = "http://127.0.0.1:18732"
for f, level, scope, compose in [("finance-team.yaml", "team", "finance", "restrict"),
                                  ("loosen.yaml", "agent", "payments-ops", "override")]:
    r = httpx.post(f"{B}/api/policies", json={"body": open(f).read(), "level": level,
                   "scope_id": scope, "compose": compose, "notes": "docs example"})
    print(r.status_code, r.json())`}</Code>
      <Output>{`201 {'key': 'finance-team', 'version': 1, 'version_id': 'pvr_01m469r2pmpz4qds25'}
201 {'key': 'payments-ops-exceptions', 'version': 1, 'version_id': 'pvr_01m469r2q1s0kh1bq6'}`}</Output>
      <Code>{`agentfox policy effective --agent payments-ops --team finance
agentfox policy lint`}</Code>
      <Output>{`effective policy in development — default allow
  layers:
    org:*(extend)  baseline  observe
    …
    team:finance(restrict)  finance-team  observe
    agent:payments-ops(override)  payments-ops-exceptions  observe
…
injection.direct                     block     observe  org:*         —
pii.outbound_redact                  block     observe  team:finance  org:*
…
rejected layer rules
  injection.direct at agent:payments-ops — cannot loosen 'block' (from org) to 'allow' — the upstream rule is not marked
overridabl

severity  code               rule              level  message
critical  illegal-loosening  injection.direct  agent  weakens 'block' from org:* to 'allow' without an 'overridable:
                                                      true' grant
  {'critical': 1}

LINT FAIL — critical/high findings block the build`}</Output>
      <h3 id="hierarchy-runtime">What the runtime enforces</h3>
      <p>
        The enforcer resolves the hierarchy the same way <code>policy effective</code>{" "}
        does, for each request:
      </p>
      <ul>
        <li>
          A layer applies only to the subject its level and <code>scope_id</code> name.
          An agent&apos;s team is its <code>owner_team</code> (set with{" "}
          <code>PATCH /api/agents/{"{slug}"}</code> or when registering it); an agent with
          no team gets only <code>team</code> layers scoped to <code>*</code>. In the
          example above, <code>team:finance</code> does not apply to{" "}
          <code>support-triage</code>.
        </li>
        <li>
          A rule rejected as an illegal loosening is not enforced; the broader rule
          stands. A granted <code>override</code> replaces the broader rule, so an{" "}
          <code>allow</code> there really loosens it.
        </li>
        <li>
          A rule that a narrower layer tightened stays in force beside the tighter one,
          each under its own pack&apos;s mode. A team that trials a stricter rule in
          observe does not switch off the org&apos;s enforced rule.
        </li>
        <li>
          <code>user</code> layers scoped to a specific user apply only where the caller
          identifies the user, which the runtime does not do today; a{" "}
          <code>user</code> layer scoped to <code>*</code> applies to everyone.
        </li>
      </ul>

      <h2 id="fail-mode">fail_mode and the enforcement budget</h2>
      <p>
        What happens when a detector times out or errors is decided by two settings,
        and the stricter wins: the deployment-wide <code>fail_mode</code> (
        <code>AGENTFOX_FAIL_MODE</code>, or <code>fail_mode</code> in{" "}
        <code>agentfox.toml</code>) and each pack&apos;s own <code>fail_mode</code>. With{" "}
        <code>open</code> (the default) the call proceeds and the gap is recorded. A
        degraded call is blocked as <code>pipeline.fail_closed</code> when the
        deployment says <code>closed</code> and the decision is enforcing, or when a pack
        that is bound in enforce says <code>closed</code> and has an enabled detection
        rule on the surface being checked (its coverage depended on the detectors that
        did not finish). <code>tool-containment</code> and{" "}
        <code>eu-ai-act-high-risk</code> ship with <code>closed</code>. Details and an
        example are in <Link href="/docs/reference/detectors#budget">Detectors: budget and failure</Link>.
      </p>
      <p>
        An LLM judge that does not answer (unreachable, an error, a timeout) is a degraded
        check like any other. The judgment posture&apos;s &quot;On a judge outage: deny the
        request&quot; (off by default) adds one more block, as{" "}
        <code>pipeline.judge_outage</code>: only when the decision is enforcing and an
        enforcing pack has a rule on that surface the judge&apos;s findings could fire. It
        never loosens a <code>closed</code> fail mode. A payload the egress gate refused to
        send (<code>pii_egress</code> set to <code>block</code>) is not an outage.
      </p>

      <h2 id="rollout">Roll out a change</h2>
      <h3 id="simulate">Simulate against recorded traffic</h3>
      <p>
        <code>agentfox policy simulate --file</code> replays recorded decisions against a
        candidate and exits 1 if anything would newly block. Here the export cap is
        lowered from 10,000 rows to 100:
      </p>
      <Code>{`agentfox policy simulate --file candidate.yaml`}</Code>
      <Output>{`support-desk simulated against 6 decisions
  unchanged        5
  newly blocked    1
  newly escalated  0
  newly allowed    0
    would block support-triage tool_args billing.export — Billing exports are capped at 100 rows.

This change would block production traffic. Review before promoting to enforce.`}</Output>
      <p>
        Options: <code>--agent</code>, <code>--since-days</code> (default 30),{" "}
        <code>--limit</code> (default 1000).
      </p>

      <h3 id="versions">Versions and the simulate gate</h3>
      <p>
        Saving a policy (<code>POST /api/policies</code>, or <strong>Save new version</strong>{" "}
        in the editor) stores an immutable new version and never changes what is in force,
        whatever <code>mode:</code> the YAML says. A policy saved for the first time goes live
        in observe. <code>POST /api/policies/&#123;key&#125;/mode</code> with{" "}
        <code>mode: enforce</code> answers 409 unless a simulation of exactly that
        version&apos;s rules was recorded; demoting to observe never needs one.
      </p>

      <h3 id="enforce">Promote and demote</h3>
      <Code>{`agentfox policy enforce baseline
agentfox policy observe baseline`}</Code>
      <Output>{`baseline → enforce
baseline → observe`}</Output>
      <p>
        Both are audited. <code>agentfox.auto()</code> in its default mode follows the
        change with no code change; <code>policy enforce</code> names any{" "}
        <code>agentfox.auto(..., mode=&quot;observe&quot;)</code> line in the project, which
        never blocks, and the edit that fixes it. The key can also be a library applied per agent
        (<code>basic</code>, <code>baseline</code>, <code>tool-containment</code> from the
        dashboard&apos;s Libraries): every agent&apos;s copy is switched. A shipped pack the
        workspace never loaded is loaded in that mode.
      </p>

      <h3 id="canary">Canary</h3>
      <p>
        A new version can take a percentage of traffic before it takes all of it.
        Canaries are run over the API (there is no CLI command):{" "}
        <Link href="/docs/reference/api#POST--api-policies-key-canary-start"><code>POST /api/policies/{"{key}"}/canary/start</code></Link>{" "}
        with optional <code>steps</code> (default <code>[10, 25, 50, 100]</code>),{" "}
        <code>max_block_rate_delta</code> (0.15), <code>max_block_rate_drop</code>,{" "}
        <code>min_dwell_seconds</code> and <code>min_sample</code> (20);{" "}
        <code>/canary/advance</code> checks health and advances, holds, or rolls back
        when the candidate blocks more, or less, than stable by more than the threshold;{" "}
        <code>/canary/rollback</code> stops it.
      </p>
      <Output>{`201 {
 "id": "cny_01m469sp29fkvhqj65",
 "status": "rolling",
 "percent": 10,
 "step_index": 0,
 "steps": [
  10,
  50,
  100
 ],
 "stable_version": 1,
 "candidate_version": 2,
 "max_block_rate_delta": 0.15,
 "max_block_rate_drop": 0.15,
 "min_dwell_seconds": 3600,
 …
 "gate": {
  "action": "hold",
  "reason": "waiting for 20 decisions in each cohort (stable 0, candidate 0)"
 }
}`}</Output>

      <h3 id="rego">Rego export and the OPA engine</h3>
      <p>
        Every pack compiles to a Rego module:{" "}
        <Link href="/docs/reference/api#GET--api-policies-key-rego"><code>GET /api/policies/{"{key}"}/rego</code></Link>,
        and <code>policy validate</code> reports the line count. The native engine is
        the default. Setting <code>policy_engine = &quot;opa&quot;</code> with{" "}
        <code>opa_url</code> evaluates through an OPA sidecar instead, and falls back to
        the native engine if the sidecar is unreachable. The OPA path was not exercised
        for this page.
      </p>
      <Output>{`# Generated by AgentFox from policy 'support-desk' v1.
# Do not edit — regenerate from the declarative source.
package agentfox.platform.policy.support_desk

import rego.v1

default verdict := "allow"

# Exports over 10,000 rows are refused.
fired contains out if {
    glob.match("billing.*", [], input.tool)
    input.arguments.rows > 10000
    out := {
        "rule_id": "billing.large_export",
        "effect": "block",
…`}</Output>

      <h2 id="proposals">Change proposals</h2>
      <p>
        AgentFox proposes changes to its own configuration instead of making them: grants and
        tool declarations from traffic (<code>proposals from-traffic</code>), rule cut-offs
        from false-positive labels (<code>proposals from-labels</code>). A loosening is never
        applied by automation.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Status</th><th>Meaning</th></tr>
        </thead>
        <tbody>
          <tr><td><code>proposed</code></td><td>Filed, not yet checked.</td></tr>
          <tr><td><code>proven</code></td><td>Replayed against recorded calls; awaiting approval (or a second approver).</td></tr>
          <tr><td><code>approved</code></td><td>Ready to apply. Only an approved change can be applied.</td></tr>
          <tr><td><code>canary</code></td><td>Applied to part of the traffic; <code>apply</code> settles it when the canary ends.</td></tr>
          <tr><td><code>applied</code>, <code>verified</code></td><td>In force; <code>verify</code> records whether it did what it promised.</td></tr>
          <tr><td><code>rejected</code>, <code>rolled_back</code>, <code>superseded</code></td><td>Not in force.</td></tr>
        </tbody>
      </table></div>
      <p>
        A tool declaration applies to the whole organisation, so it needs two different
        approvers: the same person approving twice is refused. Apply, rollback and verify
        need the <code>policy_production</code> permission (owner, admin, security). The CLI
        takes <code>--actor</code> on every decision.
      </p>

      <h2 id="escalation">Hand-off conditions</h2>
      <p>
        <code>agentfox declare escalation</code> sets when a conversation must go to a person
        (omit <code>--agent</code> for the default). Conditions you do not name keep these
        defaults:
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Condition</th><th>Default</th></tr>
        </thead>
        <tbody>
          <tr><td><code>explicit_request</code></td><td>on: asking for a person always qualifies</td></tr>
          <tr><td><code>sentiment_below</code></td><td>-0.6</td></tr>
          <tr><td><code>confidence_below</code></td><td>0.35</td></tr>
          <tr><td><code>repeated_failure</code></td><td>2</td></tr>
          <tr><td><code>repeated_abstention</code></td><td>2</td></tr>
          <tr><td><code>turn_depth</code></td><td>8</td></tr>
          <tr><td><code>regulated_topics</code></td><td>legal, medical, financial_advice, complaint, discrimination</td></tr>
          <tr><td><code>urgent_flags</code></td><td>self_harm, urgency, legal_threat, regulatory, discrimination (self_harm cannot be switched off)</td></tr>
        </tbody>
      </table></div>
      <p>
        In <code>observe</code> (the default) the hourly <code>escalation.scan</code> job
        raises a <code>missed_escalation</code> finding for each conversation that qualified.
        In <code>enforce</code> the conversation is handed off on the turn that first
        qualifies. <code>--sla-minutes</code> is how long a hand-off may wait before{" "}
        <code>handoff_sla_breach</code>.
      </p>

      <h2 id="boundaries">Knowledge boundaries</h2>
      <p>
        <code>agentfox declare boundary AGENT --systems … --coverage-months N --answerable … --out-of-scope …</code>{" "}
        says what an agent may answer from. The question is checked before the model is
        called; the answer is withheld with an <code>abstain</code> verdict. Question types
        are <code>fact</code>, <code>aggregate</code>, <code>prediction</code>,{" "}
        <code>opinion</code>, <code>procedure</code> (<code>--answerable</code> defaults to
        fact, aggregate, procedure). Boundaries start in observe;{" "}
        <code>agentfox test boundary</code> shows the refusal without changing anything.
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr><th>Abstention kind</th><th>When</th></tr>
        </thead>
        <tbody>
          <tr><td><code>unknowable</code></td><td>A projection or opinion rather than a recorded fact.</td></tr>
          <tr><td><code>out_of_coverage</code></td><td>About a period outside the data&apos;s coverage.</td></tr>
          <tr><td><code>out_of_domain</code></td><td>A topic declared out of scope.</td></tr>
          <tr><td><code>unsupported_question_type</code></td><td>A question type the agent is not set up to answer.</td></tr>
          <tr><td><code>out_of_scope_entity</code></td><td>Only when the caller sends <code>known_entities</code>: the question names an identifier-shaped token not among them.</td></tr>
        </tbody>
      </table></div>

      <h2 id="tasks">Commands</h2>
      <TaskTable
        rows={[
          { task: "See which packs exist and where they came from", run: "agentfox policy packs", href: "/docs/reference/cli#cmd-policy-packs" },
          { task: "See each bound pack's mode", run: "agentfox policy list", href: "/docs/reference/cli#cmd-policy-list" },
          { task: "Check one file", run: "agentfox policy validate FILE", href: "/docs/reference/cli#cmd-policy-validate" },
          { task: "Lint everything bound (CI gate)", run: "agentfox policy lint", href: "/docs/reference/cli#cmd-policy-lint" },
          { task: "What is in force for an agent", run: "agentfox policy effective --agent support-triage", href: "/docs/reference/cli#cmd-policy-effective" },
          { task: "Replay traffic against a candidate", run: "agentfox policy simulate --file candidate.yaml", href: "/docs/reference/cli#cmd-policy-simulate" },
          { task: "Start or stop enforcing", run: "agentfox policy enforce baseline", href: "/docs/reference/cli#cmd-policy-enforce" },
          { task: "Draft grants from recorded calls", run: "agentfox policy proposals from-traffic", href: "/docs/reference/cli#cmd-policy-proposals-from-traffic" },
        ]}
      />

      <h2 id="troubleshooting">Troubleshooting</h2>
      <dl>
        <dt>My pack is not in <code>policy list</code></dt>
        <dd>
          Files in <code>.agentfox/policies/</code> are loaded by{" "}
          <code>agentfox init</code>, run from the repository root. <code>policy packs</code>{" "}
          shows what is on disk; <code>policy list</code> shows what is bound.
        </dd>
        <dt>A rule never fires</dt>
        <dd>
          Run <code>agentfox policy lint</code> for unreachable conditions. Check the
          pack&apos;s <code>scope</code>, the surface (each detector runs only on some
          surfaces), and that <code>min_score</code> is not above what the detector
          produces: the decision&apos;s explanation shows each match&apos;s score.
        </dd>
        <dt>It fires but nothing is blocked</dt>
        <dd>The pack is in observe. Look at <code>effective_verdict</code>, then <code>agentfox policy enforce KEY</code>.</dd>
        <dt><code>tool-containment</code> will not load</dt>
        <dd>A replacement pack removed or disabled <code>control_plane.tamper</code>. That is refused by design.</dd>
      </dl>

      <h2 id="limits">Limits</h2>
      <ul>
        <li>Rules see what the detectors and the registry give them. A wrong impact declaration or a missed detection is not fixed by a better rule.</li>
        <li>The runtime does not know the end user, so <code>user</code> layers scoped to one user never apply at runtime (above).</li>
        <li>The <code>completion</code> surface needs the caller to report facts; over HTTP there is no field for them, so <code>completion_requires</code> rules always see them as unmet there.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/reference/detectors", label: "Detectors and findings", why: "the entities your detection conditions match" },
          { href: "/docs/protect/custom-rules", label: "Custom rules", why: "the same rules from the app" },
          { href: "/docs/protect/tuning", label: "Fix false positives", why: "feedback, suppressions and canaries in practice" },
        ]}
      />
    </article>
  );
}

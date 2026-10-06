import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Approvals and the kill switch",
  description:
    "Hold a tool call for a person, poll and decide approvals, catch conversations that never reached a human, and stop an agent during an incident.",
  path: "/docs/guides/approvals",
});

export default function ApprovalsGuide() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>Approvals and the kill switch</h1>
      <p className="docs-lede">
        AgentFox can hold a single call until a person approves it, tell you which
        conversations should have reached a person and did not, and stop an agent outright
        while you find out what it did.
      </p>

      <h2>When to use this</h2>
      <ul>
        <li>
          <strong>Approvals</strong>: a tool is fine to call sometimes but not unattended,
          such as <code>billing.export</code> or <code>email.send</code> to a customer, or an
          argument came from somewhere you do not trust.
        </li>
        <li>
          <strong>Escalation policy</strong>: a support agent talks to people, and some of
          those conversations (an explicit request for a human, repeated failure, anger, a
          legal threat) should go to a person.
        </li>
        <li>
          <strong>Quarantine and kill</strong>: an agent is doing something you did not
          expect and you need it to stop now, reversibly, with a record of who did it.
        </li>
      </ul>

      <h2>Where an approval comes from</h2>
      <p>
        A decision with the verdict <code>escalate</code> files an approval request and
        returns its id. In practice that happens three ways:
      </p>
      <table>
        <thead>
          <tr>
            <th>Cause</th>
            <th>Rule in <code>rules_fired</code></th>
            <th>How you set it up</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>The grant says a person approves every call.</td>
            <td><code>capability.approval_required</code></td>
            <td>
              <code>agentfox permit grant &lt;agent&gt; &lt;tool&gt; --requires-approval</code>
            </td>
          </tr>
          <tr>
            <td>
              An argument came from somewhere worse than the grant&apos;s{" "}
              <code>--max-taint</code> (a retrieved document, another tool&apos;s output).
            </td>
            <td><code>capability.approval_required</code>, with a reason naming the argument and where it came from</td>
            <td>
              Any grant. The default <code>--max-taint</code> is <code>user</code>; see{" "}
              <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>.
            </td>
          </tr>
          <tr>
            <td>A policy rule with <code>effect: escalate</code> matched, in enforce mode.</td>
            <td>the rule&apos;s own id</td>
            <td>
              Shipped packs (several rules in <code>tool-containment</code>) or your own; see{" "}
              <Link href="/docs/reference/policies">Policy language</Link>.
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        In observe mode an escalating rule is recorded as what would have happened and no
        approval is needed for the call to go through.
      </p>

      <h2>Worked example: a held export</h2>
      <p>
        This uses the gateway from <Link href="/docs/guides/gateway">Any language: the
        gateway</Link> and the operators that{" "}
        <Link href="/docs/reference/cli#cmd-admin-seed">
          <code>agentfox admin seed</code>
        </Link>{" "}
        creates (deciding an approval needs the owner, admin or security role;{" "}
        <code>marcus@example.com</code> is security).
      </p>
      <Steps>
        <Step title="Require a person for the tool">
          <Code>{`agentfox declare tool billing.export --impact high_impact --description "Export invoices for an account"
agentfox permit grant support-triage billing.export --requires-approval --yes`}</Code>
          <Output>{`billing.export declared — impact high_impact, output untrusted
…
Grant billing.export to support-triage  agent:support-triage
  actions        *
  argument limits —
  max provenance user  arguments the user typed, nothing retrieved
  human approval required for every call
  expires        never

granted cap_01m469qwr2pjeckkc3  agent:support-triage`}</Output>
        </Step>

        <Step title="Ask before running it">
          <Code>{`agentfox serve &
curl -s http://localhost:8080/v1/guard/tool_call \\
  -H 'Content-Type: application/json' \\
  -d '{"agent":"support-triage","tool":"billing.export",
       "arguments":{"account":"acme","period":"2026-09"},
       "provenance":{"account":"user","period":"user"},
       "intent":"export September invoices for acme"}'`}</Code>
          <Output>{`{
  "verdict": "escalate",
  "applied_verdict": "escalate",
  "effective_verdict": "escalate",
  "mode": "enforce",
  "approval_id": "apr_01m46jnb2j2zszsbsm",
  "reason": "The granting capability requires human approval for this action.",
  "trace_id": "trc_01m46jnb1tvwstznav",
  "decision_id": "dec_01m46jnb2fj3mscvm0",
  "rules_fired": [{"rule_id": "capability.approval_required", "effect": "escalate", …}],
  …
}`}</Output>
          <p>
            Through the proxy (<code>/v1/chat/completions</code>, <code>/v1/messages</code>) an
            escalation is an HTTP 428 with{" "}
            <code>{`{"error":{"type":"agentfox_approval_required","approval_id","poll",…}}`}</code>{" "}
            and the model is not called. The OpenAI and Anthropic SDKs raise it as{" "}
            <code>APIStatusError</code>.
          </p>
        </Step>

        <Step title="Look at the queue">
          <Code>{`export AGENTFOX_API_TOKEN=nom_api_…   # agentfox admin auth issue marcus@example.com
curl -s "http://localhost:8080/api/approvals?status=pending" \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN"`}</Code>
          <Output>{`{
    "approvals": [
        {
            "id": "apr_01m46jnb2j2zszsbsm",
            "agent_id": "agt_01m469q1nfsd4b4c3h",
            "tool": "billing.export",
            "arguments": {"account": "acme", "period": "2026-09"},
            "reason": "The granting capability requires human approval for this action.",
            "status": "pending",
            "requested_at": "2026-10-05T17:44:22.866282+00:00",
            "expires_at": "2026-10-05T18:14:22.865869+00:00",
            "trace_id": "trc_01m46jnb1tvwstznav",
            "decision_id": "dec_01m46jnb2fj3mscvm0",
            "timeout_action": "deny"
        }
    ]
}`}</Output>
          <p>
            <code>status</code> filters by <code>pending</code>, <code>approved</code>,{" "}
            <code>denied</code>, <code>expired</code> or <code>used</code>. An approval held over
            a <em>message</em> rather than a tool call has <code>tool: "message:input"</code>{" "}
            (or <code>message:output</code>, <code>message:agent_message</code>) and the message
            in <code>arguments.content</code>, with personal data masked. From the CLI:
          </p>
          <Code>{`agentfox permit approvals list
agentfox permit approvals show apr_01m46jnb2j2zszsbsm`}</Code>
          <InTheApp path="/app/approvals">Approvals: pending requests, with Approve and Deny</InTheApp>
        </Step>

        <Step title="Decide it">
          <Code>{`curl -s -X POST http://localhost:8080/api/approvals/apr_01m46jnb2j2zszsbsm/approve \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN" -H 'Content-Type: application/json' \\
  -d '{"rationale":"Finance asked for the September export (ticket 4411)."}'
curl -s http://localhost:8080/api/approvals/apr_01m46jnb2j2zszsbsm \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN"`}</Code>
          <Output>{`{"id":"apr_01m46jnb2j2zszsbsm","status":"approved","resolver":"marcus@example.com"}
{"id":"apr_01m46jnb2j2zszsbsm","status":"approved","reason":"The granting capability requires human approval for this action.","tool":"billing.export","arguments":{"account":"acme","period":"2026-09"},"rationale":"Finance asked for the September export (ticket 4411).","agent_id":"agt_01m469q1nfsd4b4c3h","expires_at":"2026-10-05T18:16:02.114023+00:00","trace_id":"trc_01m46jnb1tvwstznav"}`}</Output>
          <p>
            <code>…/deny</code> takes the same body. Both are written to the audit chain
            with the person who decided. A user without the role is refused:
          </p>
          <Output>{`{"detail":"role 'developer' may not modify 'approvals'. Permitted: ['admin', 'owner', 'security']."}`}</Output>
          <p>Or from the CLI, against the same database:</p>
          <Code>{`agentfox permit approvals approve apr_01m46jnb2j2zszsbsm -r "Finance asked for the September export (ticket 4411)." --as marcus@example.com`}</Code>
        </Step>

        <Step title="Run it">
          <p>
            Approving does not run anything. The agent sends the same call again with the
            approval id, and that call runs:
          </p>
          <Code>{`curl -s http://localhost:8080/v1/guard/tool_call \
  -H 'Content-Type: application/json' \
  -d '{"agent":"support-triage","tool":"billing.export",
       "arguments":{"account":"acme","period":"2026-09"},
       "provenance":{"account":"user","period":"user"},
       "intent":"export September invoices for acme",
       "approval_id":"apr_01m46jnb2j2zszsbsm"}'`}</Code>
          <Output>{`{"verdict": "allow", "rules_fired": [{"rule_id": "capability.approval_required", …}, {"rule_id": "approval.redeemed", "effect": "allow", …}], …}`}</Output>
          <p>
            An approval lets exactly one call through: the same agent, the same tool and the
            same arguments the person saw, within 30 minutes of the approval. Sending it again,
            or with different arguments, escalates as before and files a new approval; the
            reason says why the approval presented was not used. It never turns a block into
            an allow. Through the proxy, send the same request with the header{" "}
            <code>X-Nometria-Approval: apr_…</code>.
          </p>
        </Step>
      </Steps>

      <p>
        Nobody answering is a denial. An approval expires 30 minutes after it was filed and
        its <code>timeout_action</code> is <code>deny</code>, so polling it after that
        returns <code>expired</code>. Once approved, it can be redeemed for 30 minutes; once
        redeemed it reads <code>used</code>.
      </p>

      <h2>In Python: ApprovalRequired</h2>
      <p>
        The SDK (<code>agentfox.sdk.AgentFox</code>) raises <code>ApprovalRequired</code> on
        an escalate verdict and <code>PolicyViolation</code> on a block. The exception
        carries <code>approval_id</code> and <code>trace_id</code>.{" "}
        <code>fox.wait_for_approval(id, timeout)</code> waits for the decision and returns{" "}
        <code>approved</code>, <code>denied</code>, <code>expired</code>, or{" "}
        <code>pending</code> if the timeout ran out; <code>guard_tool(…, approval_id=id)</code>{" "}
        is the retry that runs. This one talks to the gateway (<code>base_url</code>) with the
        agent&apos;s own key; without <code>base_url</code> the same code checks in-process
        against the local database.
      </p>
      <Code lang="python" title="export.py">{`import os

from agentfox.sdk import AgentFox, ApprovalRequired, PolicyViolation

fox = AgentFox(
    agent="support-triage",
    base_url="http://localhost:8080",
    api_key=os.environ["AGENTFOX_AGENT_KEY"],  # nom_agt_…, the agent's own key
)


def export_invoices(account: str, period: str) -> None:
    arguments = {"account": account, "period": period}
    with fox.session(intent=f"export {period} invoices for {account}") as s:
        try:
            s.guard_tool("billing.export", arguments)
        except ApprovalRequired as held:
            print(f"held for a person: {held.approval_id}")
            status = fox.wait_for_approval(held.approval_id, timeout=1800)
            print(f"decision: {status}")
            if status != "approved":
                return
            # The retry: the same call, presenting the approval. Runs once.
            s.guard_tool("billing.export", arguments, approval_id=held.approval_id)
        except PolicyViolation as refused:
            print(f"refused: {refused}")
            return
    print(f"exporting {period} for {account}")  # run the real export here


export_invoices("acme", "2026-09")`}</Code>
      <p>Run it, and approve from another terminal while it waits:</p>
      <Output>{`held for a person: apr_01m469wyjmfgyk34yr
decision: approved
exporting 2026-09 for acme`}</Output>
      <p>Denied instead:</p>
      <Output>{`held for a person: apr_01m469xcaf6c5vkj7s
decision: denied`}</Output>
      <Callout kind="note" title="Polling with the agent's key">
        An agent&apos;s own <code>nom_agt_</code> key may read{" "}
        <code>GET /api/approvals/&#123;id&#125;</code> for its own agent&apos;s approvals (another
        agent&apos;s read as 404). Listing and deciding stay with operators.
      </Callout>
      <p>
        With <code>agentfox.auto()</code> the model&apos;s tool call is withheld and{" "}
        <code>agentfox.Blocked</code> is raised, with the approval id on{" "}
        <code>exc.result.approval_id</code>:
      </p>
      <Output>{`agentfox: tool call billing.export needs human approval (approval apr_01m469ya25jgwswme8) by capability.approval_required: The granting capability requires human approval for this action. No argument came from untrusted content.`}</Output>
      <p>
        The response that asked for the call is not handed back, so after an approval your
        code makes the call itself, through <code>guard_tool(…, approval_id=…)</code> as above.
      </p>

      <h2>Conversations that should reach a person</h2>
      <p>
        Approvals hold one call. Escalation policy is about whole conversations: when a user
        asks for a human, gets angry, keeps failing, or raises a legal or medical topic, the
        conversation should be handed off. AgentFox checks this after the fact, over the
        turns it recorded, and reports the conversations that qualified and never got one.
      </p>
      <Steps>
        <Step title="Declare the policy">
          <Code>{`agentfox declare escalation --agent support-triage --turn-depth 6 --repeated-failure 2 --sla-minutes 30 --owner support`}</Code>
          <Output>{`✓ escalation policy for support-triage
  owner support · SLA 30 min · observe mode
  conditions: confidence_below, explicit_request, regulated_topics,
repeated_abstention, repeated_failure, sentiment_below, turn_depth`}</Output>
          <p>
            Omit <code>--agent</code> to set the default for every agent. Conditions you do
            not name keep their defaults: an explicit request always qualifies, sentiment at
            or below -0.6, regulated topics (legal, medical, financial advice, complaint,
            discrimination), confidence below 0.35, two abstentions, eight turns.{" "}
            <code>--sla-minutes</code> is how long a hand-off may wait before it is breached.
          </p>
        </Step>

        <Step title="Record conversations">
          <p>
            Turns are recorded by <code>agentfox.auto()</code>, and by the gateway proxy for
            any request with an <code>X-Nometria-Session</code> header. Three turns of one
            conversation and one of another:
          </p>
          <Code>{`for msg in "My invoice for September is wrong." \\
           "It is still wrong, the total doubled." \\
           "This is ridiculous. I want to speak to a manager."; do
  curl -s -o /dev/null http://localhost:8080/v1/chat/completions \\
    -H 'Content-Type: application/json' -H 'X-Nometria-Agent: support-triage' \\
    -H 'X-Nometria-Session: conv-1001' \\
    -d "{\\"model\\":\\"gpt-4o-mini\\",\\"messages\\":[{\\"role\\":\\"user\\",\\"content\\":\\"$msg\\"}]}"
done`}</Code>
        </Step>

        <Step title="Find the ones that were missed">
          <Code>{`agentfox report escalations --hours 24`}</Code>
          <Output>{`5 conversation(s) · 2 qualified for escalation · 1 missed (50.0%, target < 5%)
  conv-1001 3 turns · qualified at turn 2 · explicit_request, sentiment

  Read-only. Re-run with --apply to raise findings and retroactive hand-offs so
the people still waiting are actually queued.`}</Output>
          <p>
            Turns are counted from 0, so &quot;turn 2&quot; is the third message. The
            report is read-only. <code>--apply</code> raises a{" "}
            <code>missed_escalation</code> finding and puts a hand-off in the queue for each
            missed conversation:
          </p>
          <Code>{`agentfox report escalations --hours 24 --apply
agentfox report escalations`}</Code>
          <Output>{`5 conversation(s) · 2 qualified for escalation · 1 missed (50.0%, target < 5%)
  conv-1001 3 turns · qualified at turn 2 · explicit_request, sentiment
5 conversation(s) · 2 qualified for escalation · 0 missed (0.0%, target < 5%)`}</Output>
        </Step>

        <Step title="Work the hand-off queue">
          <Code>{`curl -s "http://localhost:8080/api/escalation/handoffs?agent=support-triage&status=pending" \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN"`}</Code>
          <Output>{`{
    "handoffs": [
        {
            "id": "hnd_01m469yz15b43n8fc7",
            "session_id": "conv-1001",
            "agent_slug": "support-triage",
            "status": "pending",
            "reason": "the user asked for a human; sentiment -0.90 at or below -0.6",
            "summary": "[0] My invoice for September is wrong. → [1] It is still wrong, the total doubled. → [2] This is ridiculous. I want to speak to a manager.",
            "triggers": [
                {"condition": "explicit_request", "detail": "the user asked for a human", "turn_index": 2, "severity": "high"},
                {"condition": "sentiment", "detail": "sentiment -0.90 at or below -0.6", "turn_index": 2, "severity": "high"}
            ],
            "owner_role": "support",
            "due_at": "2026-10-05T15:42:21.029445",
            "completeness": {"score": 1.0, "missing": [], "complete": true, …},
            "detected_retroactively": true,
            …
        }
    ]
}`}</Output>
          <p>Whoever picks it up acknowledges it:</p>
          <Code>{`curl -s -X POST http://localhost:8080/api/escalation/handoffs/hnd_01m469yz15b43n8fc7/acknowledge \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN"`}</Code>
          <p>
            A pending hand-off past its <code>due_at</code> is marked breached and raises a{" "}
            <code>handoff_sla_breach</code> finding when{" "}
            <code>POST /api/escalation/scan</code> runs. Nothing runs that scan on a
            schedule and <code>report escalations --apply</code> does not check SLAs, so call
            it from your own cron if you rely on the SLA.
          </p>
          <InTheApp path="/app/approvals?tab=escalation">Approvals → Escalation: missed escalations and the hand-off queue</InTheApp>
        </Step>
      </Steps>

      <h3>Telling AgentFox your agent did hand off</h3>
      <p>
        If your agent hands a conversation to a person itself, record that turn with{" "}
        <code>escalated: true</code>, or it will be reported as missed:
      </p>
      <Code>{`curl -s -X POST http://localhost:8080/api/escalation/turns \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN" -H 'Content-Type: application/json' \\
  -d '{"session_id":"conv-1003","agent":"support-triage",
       "user_text":"Can I talk to a real person about my invoice?",
       "agent_text":"Connecting you to the billing team now.","escalated":true}'
agentfox report escalations`}</Code>
      <Output>{`{"id":"trn_01m469zc5ytngmyd5p","turn_index":0,"signals":{"sentiment":0.0,"flags":[],"explicit_request":true,"topics":[],"abstained":false,"claims_resolution":false,"failed":false}}
6 conversation(s) · 3 qualified for escalation · 0 missed (0.0%, target < 5%)`}</Output>
      <Callout kind="note">
        Detection is lexical (phrases like &quot;speak to a manager&quot;,
        &quot;ridiculous&quot;, &quot;lawyer&quot;), not a model, and it runs after the
        conversation rather than during it. Nothing here stops the agent mid-conversation.
        The <code>--mode</code> option of <code>declare escalation</code> is stored but does
        not change behaviour today.
      </Callout>

      <h2>Quarantine, kill and resume</h2>
      <p>
        Two stop states. <code>quarantined</code> means &quot;stop while we
        investigate&quot;; <code>killed</code> means &quot;stop now&quot;. They refuse the same
        calls and differ in what they declare, which an incident review will ask about. Both
        are reversible with <code>resume</code>, and every change is on the audit chain.
      </p>
      <Code>{`agentfox agents quarantine support-triage --reason "INC-212: exporting invoices for accounts nobody asked about"
agentfox agents list --stopped`}</Code>
      <Output>{`support-triage active → quarantined  INC-212: exporting invoices for accounts
nobody asked about
agent           state        reason                     by   when
support-triage  quarantined  INC-212: exporting         cli  2026-10-05T15:12:55
                             invoices for accounts
                             nobody asked about`}</Output>
      <p>The next model call through the proxy is refused before it reaches the model:</p>
      <Output>{`HTTP/1.1 403 Forbidden
x-nometria-verdict: block
x-nometria-mode: enforce
{"type": "agentfox_policy_violation", "message": "Agent is quarantined: INC-212: exporting invoices for accounts nobody asked about (by cli)", "verdict": "block", "trace_id": "trc_01m46a06mnmr02yhr7"} ['agent.quarantined']`}</Output>

      <h3>What a stopped agent can and cannot still do</h3>
      <p>
        The state is read at the start of each call. A call that already passed the check
        finishes; the next one is refused. Not every surface reads it:
      </p>
      <table>
        <thead>
          <tr>
            <th>Surface</th>
            <th>While quarantined or killed</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Proxy (<code>/v1/chat/completions</code>, <code>/v1/messages</code>), <code>agentfox.auto()</code> model calls</td>
            <td>Refused, rule <code>agent.quarantined</code> or <code>agent.killed</code></td>
          </tr>
          <tr>
            <td><code>/v1/guard/tool_call</code>, <code>/v1/mcp/call</code>, SDK <code>guard_tool</code></td>
            <td>Refused</td>
          </tr>
          <tr>
            <td><code>/v1/guard/input</code>, <code>/v1/guard/output</code>, <code>/v1/guard/memory_write</code></td>
            <td>
              <strong>Not refused.</strong> They return their usual verdict (
              <code>allow</code> for ordinary content).
            </td>
          </tr>
          <tr>
            <td>Approvals already pending for the agent</td>
            <td>
              <strong>Still decidable.</strong> Approving one while the agent is quarantined
              succeeds, and code following the pattern above then runs the tool.
            </td>
          </tr>
        </tbody>
      </table>
      <Callout kind="warning" title="If you only call /v1/guard/input and /output, the kill switch does not stop you">
        An integration that gates on those two endpoints alone keeps getting{" "}
        <code>allow</code> for a stopped agent. Gate tool calls through{" "}
        <code>/v1/guard/tool_call</code>, and during an incident deny the agent&apos;s pending
        approvals (runbook step 2).
      </Callout>

      <p>Escalate to a kill, then bring the agent back when the cause is dealt with:</p>
      <Code>{`agentfox agents kill support-triage --reason "INC-212: confirmed, stop everything"
agentfox findings --severity critical
agentfox agents resume support-triage --reason "INC-212: grant narrowed to finance-approved accounts"
agentfox findings --severity critical`}</Code>
      <Output>{`support-triage quarantined → killed  INC-212: confirmed, stop everything
 id         severity  type           what
 …hpct9jbp  critical  agent_stopped  Agent 'support-triage' killed by cli

  1 open finding(s).
…
support-triage killed → active  INC-212: grant narrowed to finance-approved
accounts
No open findings at severity 'critical'.`}</Output>
      <p>
        Stopping raises an <code>agent_stopped</code> finding (high for quarantine, critical
        for kill); resuming resolves it under the name of whoever resumed.{" "}
        <code>agentfox agents list --stopped</code> keeps listing an agent that has been
        resumed, with state <code>active</code> and the resume reason.
      </p>
      <p>Over HTTP the same three actions are on the control plane:</p>
      <Code>{`curl -s -X POST http://localhost:8080/api/agents/payments-ops/quarantine \\
  -H "Authorization: Bearer $AGENTFOX_API_TOKEN" -H 'Content-Type: application/json' \\
  -d '{"reason":"INC-213: unexpected email.send volume"}'`}</Code>
      <Output>{`{"agent":"payments-ops","state":"quarantined","previous_state":"active","reason":"INC-213: unexpected email.send volume","actor":"marcus@example.com","changed_at":"2026-10-05T15:14:28.169251+00:00"}`}</Output>
      <p>
        Quarantine needs the owner, admin, security or developer role; kill and resume need
        owner, admin or security. <code>GET /api/agent-controls</code> lists every agent not
        in its default state. The CLI acts on the database directly and records the actor as{" "}
        <code>cli</code>.
      </p>
      <InTheApp path="/app/agents">Agents → an agent → Kill switch</InTheApp>

      <h2>Incident runbook</h2>
      <p>Every command below was run against the example deployment above.</p>
      <Steps>
        <Step title="1. Stop the agent">
          <Code>{`agentfox agents quarantine payments-ops --reason "INC-213: unexpected email.send volume"`}</Code>
          <p>Use <code>kill</code> instead if you already know it is doing harm.</p>
        </Step>
        <Step title="2. Deny what it is waiting on">
          <p>
            Pending approvals survive a quarantine. Deny the agent&apos;s pending approvals
            (<code>agentfox permit approvals list --agent payments-ops</code>, then{" "}
            <code>deny ID</code>), or over HTTP:
          </p>
          <Code>{`API=http://localhost:8080
AUTH="Authorization: Bearer $AGENTFOX_API_TOKEN"
AGENT_ID=$(curl -s "$API/api/agents/payments-ops" -H "$AUTH" | jq -r .id)
for id in $(curl -s "$API/api/approvals?status=pending" -H "$AUTH" \\
             | jq -r --arg a "$AGENT_ID" '.approvals[] | select(.agent_id == $a) | .id'); do
  curl -s -X POST "$API/api/approvals/$id/deny" -H "$AUTH" \\
       -H 'Content-Type: application/json' -d '{"rationale":"INC-213: agent quarantined"}'
  echo
done`}</Code>
          <Output>{`{"id":"apr_01m46a3vyhar5cmbqk","status":"denied","resolver":"marcus@example.com"}
{"id":"apr_01m46a3vxyaj3yz8zz","status":"denied","resolver":"marcus@example.com"}`}</Output>
        </Step>
        <Step title="3. See what it can reach">
          <Code>{`agentfox agents lineage support-triage
agentfox permit list support-triage`}</Code>
          <Output>{`support-triage — blast radius 4
  support-triage --calls_tool--> billing.export (observed 8×)
  support-triage --uses_model--> gpt-4o-mini (observed 11×)
  …
  support-triage --connects_mcp--> tickets (observed 1×)

  id           may call                  as long as
  …pjeckkc3    billing.export            provenance up to user; a human
                                         approves
  …g3jqv96m    crm.lookup                provenance up to user
  …htby2gwa    kb.search                 provenance up to retrieved
  …5pdrxe82    tickets.*                 provenance up to user

  4 grant(s). Anything not listed is refused by default.`}</Output>
        </Step>
        <Step title="4. See what it did">
          <Code>{`curl -s "$API/api/traces?agent=support-triage&since_days=1&limit=3" -H "$AUTH"
agentfox findings --severity high`}</Code>
          <Output>{`{"traces": [{"id": "trc_01m46a3dz3eaesavnp", "verdict": "block", "status": "blocked", "started_at": "2026-10-05T15:14:47.395890+00:00", …},
            {"id": "trc_01m46a154ytg4v63tt", "verdict": "allow", "status": "ok", …}, …]}`}</Output>
          <p>
            Open a trace with <code>GET /api/traces/&#123;id&#125;</code> (see{" "}
            <Link href="/docs/guides/gateway">the gateway guide</Link>) or in the web app.
          </p>
        </Step>
        <Step title="5. Take away what it should not have">
          <Code>{`agentfox permit list support-triage --json
agentfox permit revoke cap_01m469qwr2pjeckkc3 --yes`}</Code>
          <Output>{`Revoke billing.export from support-triage  cap_01m469qwr2pjeckkc3
  argument limits —

revoked billing.export from support-triage
  The grant is gone from the live set; the audit chain keeps what it was.`}</Output>
          <p>
            The next <code>billing.export</code> call is refused with{" "}
            <code>capability.denied</code>. Re-grant narrower, for example with{" "}
            <code>--limit</code> or <code>--max-taint</code>.
          </p>
        </Step>
        <Step title="6. Resume, and check the record">
          <Code>{`agentfox agents resume support-triage --reason "INC-212: grant narrowed to finance-approved accounts"
agentfox report verify`}</Code>
          <Output>{`support-triage killed → active  INC-212: grant narrowed to finance-approved
accounts
chain: 52 entries, head seq 52, 0 checkpoints
CHAIN INTACT — 52 entries verified (seq 1..52)`}</Output>
          <p>
            The stop, the decisions on approvals and the resume are chain entries (
            <code>agent.quarantined</code>, <code>agent.killed</code>,{" "}
            <code>approval.denied</code>, <code>agent.resumed</code>), readable with{" "}
            <code>GET /api/audit/entries?action=agent.killed</code> and included in{" "}
            <Link href="/docs/guides/audit-evidence">evidence packages</Link>.
          </p>
        </Step>
      </Steps>

      <h2>Troubleshooting</h2>
      <table>
        <thead>
          <tr>
            <th>Symptom</th>
            <th>Cause and fix</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>The call escalated with &quot;arguments [&apos;…&apos;] carry provenance above the capability&apos;s max_taint&quot;, but the grant has no <code>--requires-approval</code>.</td>
            <td>
              An argument came from somewhere above the grant&apos;s <code>max_taint</code>{" "}
              (a document, a tool result). The reason names the argument and where it came
              from; pass a trusted value, or raise the grant&apos;s <code>--max-taint</code>.
            </td>
          </tr>
          <tr>
            <td>A retry with the approval id files a new approval.</td>
            <td>
              The reason ends with why the approval was not used: it was already used, is not
              yet approved, expired, or the arguments differ from the ones approved. Each
              approval lets one identical call through.
            </td>
          </tr>
          <tr>
            <td>A pending approval turned into <code>expired</code>.</td>
            <td>Nobody decided within 30 minutes. Expiry denies.</td>
          </tr>
          <tr>
            <td><code>role &apos;developer&apos; may not modify &apos;approvals&apos;</code></td>
            <td>Deciding needs owner, admin or security. Issue the token for such a user.</td>
          </tr>
          <tr>
            <td><code>report escalations</code> says 0 conversations.</td>
            <td>
              No turns were recorded. Send <code>X-Nometria-Session</code> through the proxy,
              use <code>agentfox.auto()</code>, or post turns to{" "}
              <code>/api/escalation/turns</code>.
            </td>
          </tr>
          <tr>
            <td>A quarantined agent still gets <code>allow</code>.</td>
            <td>You are calling <code>/v1/guard/input</code>, <code>/output</code> or <code>/memory_write</code>, which do not read the kill switch.</td>
          </tr>
        </tbody>
      </table>

      <h2>Limits</h2>
      <ul>
        <li>There is no CLI command to list or decide approvals; use the API or the web app.</li>
        <li>An approval does not authorise a retry, and it does not re-check the agent&apos;s state when it is decided.</li>
        <li>Approvals expire after 30 minutes; the window is not configurable per grant.</li>
        <li>Missed-escalation detection is after the fact and lexical; it finds conversations, it does not intervene in them.</li>
        <li>The kill switch is not read by <code>/v1/guard/input</code>, <code>/output</code> or <code>/memory_write</code>.</li>
      </ul>

      <TaskTable
        rows={[
          { task: "Require a person for a tool", run: "agentfox permit grant support-triage billing.export --requires-approval", href: "/docs/reference/cli#cmd-permit-grant" },
          { task: "Declare when to hand off", run: "agentfox declare escalation --agent support-triage --sla-minutes 30", href: "/docs/reference/cli#cmd-declare-escalation" },
          { task: "Find missed hand-offs", run: "agentfox report escalations --hours 24", href: "/docs/reference/cli#cmd-report-escalations" },
          { task: "Queue the missed ones", run: "agentfox report escalations --apply", href: "/docs/reference/cli#cmd-report-escalations" },
          { task: "Stop an agent", run: "agentfox agents quarantine support-triage --reason INC-212", href: "/docs/reference/cli#cmd-agents-quarantine" },
          { task: "Stop it harder", run: "agentfox agents kill support-triage --reason INC-212", href: "/docs/reference/cli#cmd-agents-kill" },
          { task: "Bring it back", run: "agentfox agents resume support-triage --reason INC-212", href: "/docs/reference/cli#cmd-agents-resume" },
        ]}
      />

      <NextSteps
        items={[
          { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", why: "grants, max-taint and the declarations approvals hang off" },
          { href: "/docs/guides/gateway", label: "Any language: the gateway", why: "the 428 response and the guard endpoints" },
          { href: "/docs/app/approvals", label: "Approvals in the web app", why: "the queue a person works from" },
          { href: "/docs/guides/audit-evidence", label: "Prove it to an auditor", why: "where the decisions and stops end up" },
        ]}
      />
    </article>
  );
}

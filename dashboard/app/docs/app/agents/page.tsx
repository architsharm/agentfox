import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Agents",
  description:
    "The agent register and the agent page: owners, risk classification, knowledge boundary, kill switch, effective policy and lineage.",
  path: "/docs/app/agents",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Agents</h1>
      <p className="docs-lede">
        The register of every agent in the workspace, and one page per agent for deciding
        whether it is safe to leave running as it is.
      </p>
      <InTheApp path="/app/agents">Agents</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>To approve or reject agents a scan proposed.</li>
        <li>To find agents sending traffic that nobody registered, or that nobody owns.</li>
        <li>To stop an agent now, and to see what policy actually applies to it.</li>
      </ul>

      <h2>The agents list</h2>
      <p>
        <code>/app/agents</code>, built from <code>GET /api/agents</code> and{" "}
        <code>GET /api/discovery/shadow</code>. Top to bottom:
      </p>
      <ul>
        <li>
          <strong>A strip of counts</strong>: agents, registered, unregistered, without an
          owner, tools, lineage edges.
        </li>
        <li>
          <strong>Pending review</strong>: draft agents proposed by a repository or hosted-API
          scan, with <strong>Approve</strong> and <strong>Reject</strong>. A draft is inert:
          approving makes it active (<code>POST /api/agents/&#123;id&#125;/approve</code>),
          rejecting discards it. Both are written to the audit chain.
        </li>
        <li>
          <strong>Unregistered agents</strong>: slugs seen in traffic that were never
          registered, with environment, call count, models, framework and first seen. These
          are shadow agents; each also appears in the attention queue as high severity.
        </li>
        <li>
          <strong>All agents</strong>: name and slug, purpose, owner (or an{" "}
          <strong>unowned — assign</strong> link), environment, risk tier, framework, and last
          seen (&quot;—&quot; means no traffic yet, not a fault). Tags mark{" "}
          <code>unregistered</code>, <code>draft</code> and <code>sample data</code>.
        </li>
        <li>
          Agents whose slug looks like a test, spec, script, example, demo or fixture are
          folded into a collapsed &quot;look like tests, scripts or examples&quot; list, so a
          scan of a repository&apos;s test directory does not bury production agents.
        </li>
        <li>
          <strong>What an agent is allowed to do</strong>: a reminder that what an agent was{" "}
          <em>seen</em> calling and what it is <em>permitted</em> to call are separate.
          Capability grants are default deny and have no screen; make them with{" "}
          <Link href="/docs/reference/cli#cmd-permit-grant">agentfox permit grant</Link> (the
          explainer in the app shows the older command name).
        </li>
      </ul>

      <h3>Registering an agent by hand</h3>
      <p>
        <strong>+ Register an agent manually</strong> is for an agent that does not live in a
        repository you can connect. Fields: <strong>Slug</strong> (unique, lowercase),{" "}
        <strong>Name</strong>, <strong>Purpose</strong>, <strong>Owner email</strong>,{" "}
        <strong>Risk tier</strong> (minimal, limited, high, prohibited; default limited).
        It posts to <code>POST /api/agents</code> and the agent is registered at once. An
        agent that calls the gateway before anyone registers it shows up as unregistered
        instead; registering the same slug claims it.
      </p>
      <p>The CLI reads the same register:</p>
      <Code>{`agentfox agents list`}</Code>
      <Output>{`agent            env         risk     registered  owner          framework
127-0-0-1        production  limited  SHADOW      unowned        hosted_api
hr-screening     production  limited  yes         unowned        crewai
marketing-copy…  production  limited  SHADOW      unowned        —
payments-ops     production  high     yes         marcus@examp…  claude-agent-s…
research-bot     production  limited  yes         dana@example…  —
support-triage   production  limited  yes         priya@exampl…  langgraph
  6 agents · 1 shadow · 3 unowned · 11 lineage edges`}</Output>
      <p>
        <code>research-bot</code> was registered from the web app a moment earlier.{" "}
        <code>127-0-0-1</code> is a draft from a hosted-API scan; the CLI and the attention
        queue both count a draft as unregistered until it is approved.
      </p>

      <h2>The agent page</h2>
      <InTheApp path="/app/agents/support-triage">Agents → an agent</InTheApp>
      <p>
        <code>/app/agents/&lt;slug&gt;</code>. Above the tabs, always visible: the name, a{" "}
        <code>sample data</code> tag for seeded agents, a red banner if the agent is
        quarantined or killed (with who did it, when and why), and a strip of counts: traces,
        decisions, blocked, escalated, hand-offs and blast radius. Each count links to the
        filtered list behind it. The page is built from{" "}
        <code>GET /api/agents/&#123;slug&#125;/posture</code>, <code>/lineage</code>,{" "}
        <code>/api/traces?agent=</code>, <code>/api/risk/classify/&#123;slug&#125;</code>,{" "}
        <code>/api/answerability/boundaries</code>, <code>/api/agent-controls</code> and{" "}
        <code>/api/policies/effective?agent=</code>.
      </p>

      <h3>Activity tab</h3>
      <ul>
        <li><strong>Open findings</strong> for this agent: severity, type, title, each linking to the finding.</li>
        <li>
          <strong>Recent traces</strong>: the last 15, with verdict, model, intent and time. If
          there are none but the agent has hand-offs, it says so: hand-offs are logged apart
          from traced calls.
        </li>
        <li>
          <strong>Reliability objectives</strong>: any SLOs declared for this agent on{" "}
          <Link href="/docs/app/evals#slos">Evaluation</Link>, with attainment and error budget.
        </li>
      </ul>

      <h3>What it may do tab</h3>
      <p>
        <strong>Effective policy</strong> is the policy actually in force for this agent,
        composed from every level that reaches it, with where each rule came from. The header
        line gives the mode, the default effect and the layers applied. Each row is a rule:
        what it checks, its effect, its source (for example <code>org:*</code>), and the
        layer&apos;s compose setting (in the column headed &quot;mode&quot;: <code>extend</code>,{" "}
        <code>restrict</code> or <code>override</code>). A <code>custom</code> tag marks a rule
        from a narrower level than the org default, and <code>loosened</code> marks a rule a
        narrower level relaxed. Rules rejected during composition are listed underneath.
      </p>
      <p>
        <strong>+ Customize for this agent</strong> opens a new policy called{" "}
        <code>&lt;slug&gt;-overrides</code>, pre-scoped to the agent level. See{" "}
        <Link href="/docs/app/policies#editor">the policy editor</Link>.
      </p>
      <Code>{`agentfox policy effective --agent payments-ops`}</Code>
      <Output>{`effective policy in development — default allow
  layers:
    org:*(extend)  baseline  observe
    org:*(extend)  eu-ai-act-high-risk  observe
    org:*(extend)  tool-containment  enforce

rule                                 effect    mode     from   overrides
access.undeclared_table              escalate  enforce  org:*  —
access.unscoped_table                block     enforce  org:*  —
…`}</Output>

      <h3 id="boundary">Knowledge boundary</h3>
      <p>
        On the same tab. A knowledge boundary is what the agent may answer from; without one,
        nothing stops it inventing an answer to a question it has no data for. Fields:
      </p>
      <ul>
        <li><strong>Systems of record it may answer from</strong> (comma-separated)</li>
        <li><strong>Coverage</strong> (months of history) and <strong>Freshness</strong> (hours)</li>
        <li><strong>Entity types it knows about</strong> (comma-separated)</li>
        <li><strong>Topics it must refuse even if it has data</strong> (comma-separated)</li>
        <li><strong>Question types it may answer</strong>: fact, aggregate, prediction, opinion, procedure</li>
      </ul>
      <p>
        <strong>Declare boundary</strong> (or <strong>Update boundary</strong>) sends{" "}
        <code>PUT /api/answerability/boundary</code>. The form has no mode field: a boundary
        saved from the web app is in <code>observe</code>, so refusals are recorded, not
        applied. Enforce it from the CLI once the dry runs look right.
      </p>
      <Code>{`agentfox declare boundary research-bot --systems wiki,ticket-history --coverage-months 12 --answerable fact,procedure --out-of-scope "legal advice,medical diagnosis"
agentfox test boundary research-bot "Can you give me legal advice about this contract?"`}</Code>
      <Output>{`✓ boundary declared for research-bot
  answerable: fact, procedure
  coverage:   last 12 months
  observe mode — refusals are recorded, not applied. Re-run with --mode enforce when the dry runs
look right.
╭─ would abstain — out_of_domain ───────────────────────────────────────────────╮
│ That topic is outside what this agent is set up to cover (legal advice).      │
╰───────────────────────────────────────────────────────────────────────────────╯
  recorded only (observe mode)`}</Output>

      <h3>Registration tab</h3>
      <ul>
        <li>
          <strong>Purpose</strong>, editable inline (tagged <code>not set</code> when empty).
          Saves with <code>PATCH /api/agents/&#123;slug&#125;</code>.
        </li>
        <li>
          <strong>Agent map</strong>: everything this agent reached in observed traffic within
          two hops, drawn as a circle, with the blast radius on it. An edge that was observed
          but never declared is drawn as such; that gap is registry drift.
        </li>
        <li>
          <strong>Registration</strong>: owner (with an email and optional team field and{" "}
          <strong>Assign owner</strong> / <strong>Update</strong>), team, environment, risk
          tier, framework, registered, declared models, declared tools, data classes, last
          seen.
        </li>
        <li>
          <strong>Observed lineage</strong>: the same edges as a table (from, relation, to,
          times seen), with each tool&apos;s impact tier (read, write, high_impact,
          irreversible) and, for MCP tools, the server&apos;s trust level. Declared models and
          tools are what someone typed in; observed lineage is what happened. A mismatch is
          worth reading.
        </li>
        <li>
          <strong>Proposed risk classification</strong>: an EU AI Act class proposed from the
          purpose text and observed behaviour, with the signals behind it (for example
          &quot;can invoke high-impact or irreversible tools&quot;). It is advisory and says it
          requires human confirmation. When it differs from the recorded tier,{" "}
          <strong>Accept — set risk tier to …</strong> writes it; leaving it is rejecting it.
          The formal record (class, residual risk, signer) is on{" "}
          <Link href="/docs/app/compliance#risk">Compliance → Risk register</Link>.
        </li>
        <li>
          <strong>Kill switch</strong>, below.
        </li>
      </ul>

      <h3 id="kill-switch">Kill switch, quarantine and resume</h3>
      <p>
        The current state is shown as a tag: <code>active</code>, <code>quarantined</code> or{" "}
        <code>killed</code>. Any state other than active refuses every governed call from the
        agent immediately, and each change goes to the audit chain.
      </p>
      <ul>
        <li>
          <strong>Quarantine</strong> (with an optional reason) is the reversible &quot;stop
          while I investigate&quot;. Allowed for owner, admin, security and developer.
        </li>
        <li>
          <strong>Kill</strong> is the incident action, with no reason field in the web app.
          It needs owner, admin or security.
        </li>
        <li>
          <strong>Resume</strong> (optional reason) returns the agent to active. It needs the
          same roles as Kill: restarting something stopped for cause is not a lesser decision.
        </li>
      </ul>
      <p>
        The form posts to the web app&apos;s <code>/api/agents/&lt;slug&gt;/control</code>, which
        calls <code>POST /api/agents/&#123;slug&#125;/quarantine</code>, <code>/kill</code> or{" "}
        <code>/resume</code>. The CLI does the same:
      </p>
      <Code>{`agentfox agents quarantine research-bot --reason "checking an odd tool call"
agentfox agents resume research-bot --reason "incident closed"`}</Code>
      <Output>{`research-bot killed → active  incident closed`}</Output>
      <p>(That resume followed a kill made in the web app.)</p>
      <Callout kind="warning">
        The kill switch only stops calls that go through AgentFox. An agent that calls a model
        or a tool directly, outside <code>agentfox.auto()</code>, the guard API or the proxy,
        is not stopped by it.
      </Callout>

      <h2>Owners and shadow agents</h2>
      <p>
        An agent with no owner shows <strong>unowned — assign</strong> on the list and an{" "}
        <code>unowned</code> tag on its Registration tab; assign one there. An unregistered
        agent is one the gateway saw in traffic under a slug nobody registered. It raises a
        high-severity attention item (&quot;&apos;slug&apos; is running and was never
        registered&quot;) and a finding. Register it with the same slug, give it an owner,
        then resolve the finding.
      </p>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "List agents, owners and shadow agents", run: "agentfox agents list" },
          { task: "See what one agent reached", run: "agentfox agents lineage payments-ops" },
          { task: "Stop an agent while you investigate", run: "agentfox agents quarantine research-bot --reason \"…\"", href: "#kill-switch" },
          { task: "Stop an agent now", run: "agentfox agents kill research-bot --reason \"…\"" },
          { task: "Bring it back", run: "agentfox agents resume research-bot --reason \"…\"" },
          { task: "Show the policy in force for it", run: "agentfox policy effective --agent payments-ops" },
          { task: "Declare what it may answer, in enforce", run: "agentfox declare boundary research-bot --systems wiki --mode enforce" },
          { task: "Let it call a tool", run: "agentfox permit grant research-bot web.fetch --yes", href: "/docs/guides/contain-tool-calls" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>Kill or Resume shows an error banner.</strong> Your role is developer;
          those need owner, admin or security. Quarantine is still available to you.
        </li>
        <li>
          <strong>&quot;no draft agent with that id&quot;</strong> on Approve or Reject. Someone
          already decided it; reload.
        </li>
        <li>
          <strong>Tools count is high but nothing is allowed.</strong> Tools are declared;
          grants are separate and default deny. See{" "}
          <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>.
        </li>
        <li>
          <strong>Blast radius reads 0.</strong> Lineage is built from observed traffic only;
          an agent with no traces has none.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>No screen for capability grants or tool declarations.</li>
        <li>Boundaries saved from the web app are always observe mode.</li>
        <li>The risk classification is a heuristic over purpose text and behaviour, not a legal determination.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/app/findings", label: "Findings", why: "what each agent tripped" },
          { href: "/docs/app/policies", label: "Policies and tuning", why: "customise what applies to one agent" },
          { href: "/docs/guides/approvals", label: "Approvals and the kill switch", why: "the incident playbook" },
          { href: "/docs/guides/rag", label: "Retrieval and answers", why: "knowledge boundaries in depth" },
        ]}
      />
    </article>
  );
}

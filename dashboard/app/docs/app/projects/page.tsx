import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Projects",
  description:
    "One project per agent: the project switcher, the canvas and its inspector, features a project inherits from the workspace, the setup banner, access, the knowledge boundary and the kill switch.",
  path: "/docs/app/projects",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Projects</h1>
      <p className="docs-lede">
        Each agent is a project: its guardrails, its traffic, what it may do and what it
        changed from the workspace&apos;s settings, on one set of pages. The API still calls
        a project an agent (<code>/api/agents</code>).
      </p>
      <InTheApp path="/app/projects">Projects</InTheApp>

      <h2>When to use this</h2>
      <ul>
        <li>To see and change what protects one agent, where it acts.</li>
        <li>To add projects a scan proposed, and find agents nobody registered or owns.</li>
        <li>To switch a feature on or off for one project without changing the others.</li>
        <li>To stop an agent now.</li>
      </ul>

      <h2 id="scope">All projects, or one</h2>
      <p>
        The switcher at the top of the sidebar picks the scope. <strong>All projects</strong>{" "}
        is the workspace: Home, Projects, Observe, Issues, Policies, Features, Approvals,
        Test and Reports. A project shows only its own pages: <strong>Canvas</strong>,{" "}
        <strong>Activity</strong>, <strong>Access</strong>, <strong>Features</strong>,{" "}
        <strong>Issues</strong>, <strong>Approvals</strong> and <strong>Settings</strong>.
        Issues and Approvals are the workspace pages filtered to the project
        (<code>?agent=&lt;slug&gt;</code>). Opening a project&apos;s link switches to it; the
        choice is remembered.
      </p>

      <h2>The projects list</h2>
      <p>
        <code>/app/projects</code>, built from <code>GET /api/agents</code>: every project with
        its owner, risk, requests and how many were stopped, open issues and last activity.{" "}
        <strong>Needs attention</strong> lists unregistered and unowned ones;{" "}
        <strong>Proposed</strong> lists the drafts a repository scan found, with{" "}
        <strong>Add project</strong> (<code>POST /api/agents/&#123;id&#125;/approve</code>) and{" "}
        <strong>Dismiss</strong>. A draft is inert until it is added. A multi-agent system
        (OpenAI Agents SDK, LangGraph, CrewAI, AutoGen, Google ADK) is proposed as one
        project per agent, each with its own tools, listed under the agent that hands it
        work; <strong>Add all</strong> adds the whole system
        (<code>POST /api/agents/&#123;id&#125;/approve-system</code>). The hand-offs its code
        declares show on each project&apos;s canvas before any traffic.
      </p>
      <h3>Creating a project by hand</h3>
      <p>
        <strong>New project</strong> is for an agent that does not live in a repository you can
        connect: an ID (unique, lowercase), name, purpose, owner and risk level, posted to{" "}
        <code>POST /api/agents</code>. An agent that calls the gateway before anyone registers
        it shows up as unregistered; creating the same ID claims it.
      </p>
      <Code>{`agentfox agents list`}</Code>

      <h2 id="canvas">The canvas</h2>
      <InTheApp path="/app/projects/support-triage">Projects → a project</InTheApp>
      <p>
        A project opens on its canvas: its guardrails drawn where they act. The user&apos;s
        message, the agent, its reply, documents and memory, tool calls, the tools, and what
        tools return. Each step is coloured by what applies there: enforcing, watching only,
        or nothing set. Agents it hands work to are drawn beside it and open their own
        project. Built from <code>GET /api/agents/&#123;slug&#125;/map</code>.
      </p>
      <ul>
        <li>
          <strong>Many tools</strong> are one <em>Tools</em> node until you choose{" "}
          <strong>Expand</strong>. Then they are drawn as groups (by risk, access, source or
          server), at most six, and an opened group shows at most six of its tools. A{" "}
          <em>+N more</em> node opens the full, searchable list in the inspector.
        </li>
        <li>
          <strong>The inspector</strong> on the right shows what is selected: a step&apos;s rules
          and checks, or a tool&apos;s access, rules and limits, each changeable for this project
          there. With nothing selected it shows the project: its requests, blocked, held and
          errors, its open issues, the guardrails that fired most, its lineage (the blast radius,
          and <strong>Open lineage map</strong> for everything within two hops), who owns it,
          its tools and the rules that apply at every step.
        </li>
      </ul>
      <p>
        <strong>Activity</strong> has the project&apos;s requests over the chosen range against
        the range before it (a window in the chart opens its runs), its runs, the guardrails
        that fired, and answer quality. <strong>Access</strong> is its tool permissions and limits and the
        knowledge boundary below. <strong>Settings</strong> has its owner and registration,
        the circuit breaker and the kill switch.
      </p>

      <h2 id="features">Features</h2>
      <InTheApp path="/app/features">Features</InTheApp>
      <p>
        The switches a developer reaches for, set once for every project on{" "}
        <code>/app/features</code> and changed per project on its own Features view.
      </p>
      <ul>
        <li>
          <strong>Protections</strong>: prompt attacks, personal data, secrets, harmful
          content, off-task actions, unsupported answers and insecure code, each off or at a
          sensitivity (low, medium, high), or off and on. Each shows whether it is blocking or
          only watching.
        </li>
        <li>
          <strong>Checks</strong>: the detectors that run on traffic, on or off. A check that
          is not installed in this deployment cannot be switched on.
        </li>
      </ul>
      <p>
        A project starts with the workspace&apos;s value for every switch and says so
        (&quot;Inherited from the workspace&quot;). Changing one marks it{" "}
        <em>changed here</em>; <strong>Reset</strong> goes back, and so does setting it to the
        workspace&apos;s value. A later change for every project reaches every project that
        inherits it.
      </p>
      <ul>
        <li>
          A project can always be <strong>stricter</strong> than the workspace.
        </li>
        <li>
          It can be <strong>lower</strong> (less sensitive, or off) only where the workspace
          ticked <strong>Projects may lower</strong> for that protection, which needs a role
          that may enforce policies. Until then the lower levels are shown locked, with the
          reason. Protections that keep the others from being switched off are never lowered
          per project.
        </li>
        <li>
          A check can be switched either way per project, except the always-on safety net.
          The gateway applies the project&apos;s choice on every call, not only on the screen.
        </li>
      </ul>
      <Code>{`GET  /api/features
GET  /api/agents/{slug}/features
POST /api/features/protections/{key}   {"level": "high", "agent": "support-triage"}
POST /api/features/checks/{key}        {"enabled": false, "agent": "support-triage"}`}</Code>
      <p>
        Every change is an operator action in the audit log. Under the hood a protection is a
        set of rules in a shipped pack; a project&apos;s change is a copy in its own layer (see{" "}
        <Link href="/docs/app/policies">Policies</Link>).
      </p>

      <h2 id="setup">The setup banner</h2>
      <p>
        Until setup is done, a line at the top of each page says what to do next, sized to the
        one missing step. In a project, in order: add it (it was proposed by a scan); send its
        first request (with a test request that names it, and the banner clears itself when
        that request arrives); allow the tools it should use; and turn blocking on, after
        seeing how many of last week&apos;s requests it would have stopped. With all projects
        in view it is about the workspace: connect the first agent, then the first request,
        then the next step on Get started. Built from <code>GET /api/onboarding</code> and{" "}
        <code>GET /api/agents/&#123;slug&#125;/setup</code>. Hiding it keeps it hidden for a
        week.
      </p>

      <h3 id="boundary">Knowledge boundary</h3>
      <p>
        On the Access view. A knowledge boundary is what the agent may answer from; without one,
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
        <code>unowned</code> tag; assign one on its Settings view. An unregistered
        agent is one the gateway saw in traffic under a slug nobody registered. It raises a
        high-severity attention item (&quot;&apos;slug&apos; is running and was never
        registered&quot;) and a finding. Register it with the same slug, give it an owner,
        then resolve the finding.
      </p>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "List projects, owners and shadow agents", run: "agentfox agents list" },
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
          grants are separate and default deny. Allow them on Access, or see{" "}
          <Link href="/docs/guides/contain-tool-calls">Contain tool calls</Link>.
        </li>
        <li>
          <strong>A lower level is locked on a project&apos;s Features.</strong> The workspace
          has not let projects lower that protection. Tick <strong>Projects may lower</strong>{" "}
          for it on the workspace&apos;s Features, or change it for every project.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
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

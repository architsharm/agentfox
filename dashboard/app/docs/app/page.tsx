import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Tour of the web app",
  description:
    "What the signed-in web app is for, how sign-in and workspaces work, every sidebar item and its CLI equivalent, the Overview page, search, notifications and demo data.",
  path: "/docs/app",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Web app</p>
      <h1>Tour of the web app</h1>
      <p className="docs-lede">
        The web app is the shared screen for the people who review what your agents did:
        findings to triage, calls waiting for a human, policies to promote, evidence to hand
        an auditor.
      </p>

      <h2>When to use the web app, and when the CLI</h2>
      <p>
        The web app is a client of the gateway&apos;s public HTTP API. It has no database
        access of its own: every page is a set of <code>/api/…</code> calls, and every button
        posts to one. Anything you can see in it, a script can fetch with a token.
      </p>
      <p>
        The <Link href="/docs/reference/cli">CLI</Link> mostly works on the database
        directly: the one in your state directory, or the one{" "}
        <code>AGENTFOX_DATABASE_URL</code> names. On a self-hosted deployment, run CLI
        commands where they can reach the gateway&apos;s database and both show the same
        data. An agent registered in the web app appears in <code>agentfox agents list</code>{" "}
        straight away, and the reverse. On a hosted workspace, the CLI commands on these
        pages apply to your own local install; the HTTP routes are what reach the workspace.
      </p>
      <ul>
        <li>
          Use the web app for queues a person works through (findings, approvals, hand-offs),
          for editing a policy with a simulation in front of you, and for anything a
          non-engineer has to read: compliance status, the board snapshot, evidence packages.
        </li>
        <li>
          Use the CLI in CI, in scripts, and for the things the web app has no screen for:
          capability grants (<Link href="/docs/reference/cli#cmd-permit-grant">agentfox permit grant</Link>),
          tool declarations, and change proposals.
        </li>
      </ul>

      <h2>Run it on your own machine</h2>
      <p>
        The web app lives in <code>dashboard/</code> in the repository. It needs a running
        gateway and a signed-in session. This is the shortest path to looking at it with
        data in it, and it is what these pages were checked against.
      </p>
      <Steps>
        <Step title="Load demo data and record some traffic">
          <p>
            <code>--demo</code> loads three agents, their tools and grants, an eval suite and
            five users. It records no traffic: until something runs, Overview says nothing is
            connected. <code>agentfox demo</code> runs the offline walkthrough, which records
            traces, decisions, findings and approvals.
          </p>
          <Code>{`agentfox init --demo
agentfox demo`}</Code>
          <Output>{`Setting up AgentFox
  ✓ database ready
…
  ✓ 43 controls across 7 frameworks  v0.1.0-draft (draft)
  ✓ 3 policy pack(s) loaded
      baseline                 observe  recorded, nothing blocked
      eu-ai-act-high-risk      observe  recorded, nothing blocked
      tool-containment         enforce  violations are blocked now
…
  ✓ wrote agentfox.toml
  ✓ demo fixtures loaded
    agents, policies and an eval suite; no traffic yet. \`agentfox demo\` sends sample requests through them.
…
╭───────────────────────────────────────────────╮
│ Walkthrough complete.                         │
│ agentfox serve      control plane on :8080    │
│ agentfox report verify  re-check the chain    │
│ agentfox report evidence --agent payments-ops │
╰───────────────────────────────────────────────╯
baseline policy restored to observe — the demo's promotion was temporary.`}</Output>
        </Step>
        <Step title="Start the gateway">
          <Code>{`agentfox serve`}</Code>
          <Output>{`AgentFox 0.3.1 → http://127.0.0.1:8080
  inline:  POST http://127.0.0.1:8080/v1/chat/completions
  api:     http://127.0.0.1:8080/api/agents
  docs:    http://127.0.0.1:8080/docs`}</Output>
        </Step>
        <Step title="Mint a token for a user that exists">
          <p>
            The demo seed creates <code>admin@example.com</code> as the workspace owner. A
            token is only ever shown once.
          </p>
          <Code>{`agentfox admin auth issue admin@example.com --name dashboard`}</Code>
          <Output>{`╭─ Token issued — copy it now ───────────────────────────────────╮
…
│ dashboard · admin@example.com · owner · org org_default         │
│ expires 2027-10-05T15:16:22.155630+00:00                        │
╰─────────────────────────────────────────────────────────────────╯
  Only a hash is stored. There is no way to show this value again — issue a new token if
it is lost.`}</Output>
        </Step>
        <Step title="Start the web app">
          <Code>{`cd dashboard
npm install
AGENTFOX_API_URL=http://127.0.0.1:8080 npm run dev`}</Code>
          <p>
            It serves on <code>http://localhost:3000</code>. Without a session every{" "}
            <code>/app</code> page redirects to <code>/login</code>.
          </p>
        </Step>
        <Step title="Sign in">
          <p>
            Sign-in is GitHub only (next section). On a laptop with no GitHub OAuth app, the
            button answers with a 503:
          </p>
          <Code>{`curl -s http://localhost:3000/api/auth/github/login`}</Code>
          <Output>{`{"error":"GitHub sign-in is not configured (GITHUB_CLIENT_ID is unset)."}`}</Output>
          <p>
            For a local evaluation only, the session is the token itself, held in a cookie
            named <code>nometria_session</code>. Open <code>http://localhost:3000/login</code>,
            then in the browser console:
          </p>
          <Code lang="ts" title="browser console">{`document.cookie = "nometria_session=<the token from step 3>; path=/"; location.href = "/app";`}</Code>
          <Callout kind="warning">
            This is a workaround for a local instance, not a sign-in method. Anything with that
            cookie acts as the token&apos;s user. Do not do it on a shared or public
            deployment; set up GitHub sign-in there.
          </Callout>
        </Step>
      </Steps>

      <h2>Signing in, workspaces and roles</h2>
      <p>
        <strong>Continue with GitHub</strong> on <code>/login</code> is the only way in. There
        is no password and no separate sign-up. The same grant lets the app list and scan
        your repositories, so it asks GitHub for <code>repo read:user user:email</code>.
      </p>
      <ol>
        <li>
          GitHub sends you back to <code>/api/auth/github/callback</code>. The web app reads
          your profile and email.
        </li>
        <li>
          It calls the gateway&apos;s <code>POST /api/auth/github/provision</code>, signed with
          a shared service secret. The gateway looks you up by GitHub user id. A GitHub
          identity it has never seen gets a brand-new workspace (an <em>org</em>), with you
          as its <code>owner</code>, and the control catalog and obligation calendar are
          loaded into it so Compliance is not empty.
        </li>
        <li>
          The gateway mints an API token named <code>github-login</code> (365 days). The
          web app stores it in an httpOnly cookie, and every page you load calls the gateway
          with it, so the workspace scoping is the gateway&apos;s, not the browser&apos;s.
        </li>
        <li>
          The GitHub access token is stored encrypted against your workspace for repository
          scans, and you land on <Link href="/docs/app/start">Start here → Connect</Link>.
        </li>
      </ol>
      <ul>
        <li>
          <strong>One GitHub identity is one workspace.</strong> There is no invite flow. Two
          colleagues who sign in separately get two workspaces that cannot see each
          other&apos;s data.
        </li>
        <li>
          The account menu (top right) shows who you are signed in as, the workspace (your
          GitHub login once GitHub is connected, otherwise the org id) and your role.
        </li>
        <li>
          Roles decide what a button may do. The gateway enforces them on every request,
          whatever the page shows: <code>owner</code> and <code>admin</code> can do
          everything; <code>security</code> can also kill or resume agents, decide approvals,
          create suppressions and change judgment posture; <code>developer</code> can register
          agents, quarantine them and edit policies; <code>compliance</code> can review
          framework mappings and record risk assessments; <code>auditor</code> can build
          evidence. A refused action comes back as an error banner on the page you were on.
        </li>
        <li>
          <strong>Sign out</strong> deletes the cookie. It does not revoke the{" "}
          <code>github-login</code> token, and every sign-in mints another one. Revoke old
          ones on <Link href="/docs/app/start#tokens">API tokens</Link>.
        </li>
        <li>
          When the gateway rejects your session, a page shows &quot;Your session has
          expired&quot; with a <strong>Sign in again</strong> link that clears the cookie.
        </li>
      </ul>

      <h2>Hosted or self-hosted</h2>
      <p>
        Whether a hosted workspace is open to you right now, and on what terms, is stated on
        the <Link href="/pricing">pricing page</Link>. Self-hosting the web app is always
        available: it is the <code>dashboard</code> service in{" "}
        <code>deploy/docker-compose.yml</code> (port 3000), the Render blueprint, or{" "}
        <code>npm run build &amp;&amp; npm start</code> in <code>dashboard/</code>. See{" "}
        <Link href="/docs/self-host">Self-hosting</Link> for the stack. These are the settings
        the web app itself reads:
      </p>
      <table>
        <thead>
          <tr>
            <th>Setting</th>
            <th>Where</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>AGENTFOX_API_URL</code> (or <code>NOMETRIA_API_URL</code>)</td>
            <td>web app</td>
            <td>The gateway, as the web app&apos;s server reaches it. Default <code>http://127.0.0.1:8080</code>.</td>
          </tr>
          <tr>
            <td><code>AGENTFOX_PLAYGROUND_API_URL</code></td>
            <td>web app</td>
            <td>The gateway as a visitor&apos;s browser reaches it, for <code>/playground</code> only. Falls back to the API URL.</td>
          </tr>
          <tr>
            <td><code>GITHUB_CLIENT_ID</code>, <code>GITHUB_CLIENT_SECRET</code></td>
            <td>web app</td>
            <td>Your GitHub OAuth app. Its callback must be <code>https://&lt;host&gt;/api/auth/github/callback</code>, exactly.</td>
          </tr>
          <tr>
            <td><code>AGENTFOX_SERVICE_AUTH_SECRET</code></td>
            <td>both, identical</td>
            <td>Signs the provisioning call. If it is still the built-in development value, anyone can mint accounts on your gateway.</td>
          </tr>
          <tr>
            <td><code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code></td>
            <td>gateway</td>
            <td>Encrypts stored GitHub tokens. Unset, connecting GitHub fails closed with a 503.</td>
          </tr>
          <tr>
            <td><code>AGENTFOX_PLAYGROUND_CORS_ORIGIN</code></td>
            <td>gateway</td>
            <td>Comma-separated origins allowed to call the playground routes from a browser.</td>
          </tr>
          <tr>
            <td><code>AGENTFOX_SELF_HOSTED</code></td>
            <td>web app</td>
            <td>Shows the &quot;start the gateway&quot; hint when the API is unreachable. On by default when the API URL is localhost.</td>
          </tr>
        </tbody>
      </table>
      <Callout kind="note" title="There is no command that creates a user">
        Users come from GitHub sign-in, or from the demo seed (<code>agentfox init --demo</code>{" "}
        or <code>agentfox admin seed</code>). On a deployment with neither,{" "}
        <code>agentfox admin auth issue</code> answers &quot;unknown user&quot; and there is no
        account to put in the web app.
      </Callout>

      <h2>The sidebar</h2>
      <p>
        Every item, what you go there for, and the closest command. Where a cell says HTTP,
        there is no CLI command; the route is in the{" "}
        <Link href="/docs/reference/api">HTTP API reference</Link>.
      </p>
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>Go there to</th>
            <th>Closest command</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><Link href="/docs/app#overview">Overview</Link> <code>/app</code></td>
            <td>See what needs a person, most severe first.</td>
            <td><code>agentfox findings</code></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/start">Start here</Link> <code>/app/start</code></td>
            <td>Work through setup, connect a repo or API, mint tokens.</td>
            <td><code>agentfox init</code>, <code>agentfox admin auth issue</code></td>
          </tr>
          <tr>
            <td colSpan={3}><strong>Discover</strong></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/agents">Agents</Link> <code>/app/agents</code></td>
            <td>The register: owners, risk, boundary, kill switch.</td>
            <td><code>agentfox agents list</code></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/access-and-sources#sources">Verified sources</Link> <code>/app/sources</code></td>
            <td>Tier the data agents answer from; connect and validate it.</td>
            <td><code>agentfox declare source</code></td>
          </tr>
          <tr>
            <td colSpan={3}><strong>Monitor</strong></td>
          </tr>
          <tr>
            <td>Threat coverage <code>/app/coverage</code></td>
            <td>
              Each OWASP LLM Top 10, OWASP Agentic and MITRE ATLAS threat, and whether a rule
              enforces against it, only watches, or nothing does. A threat counts as covered
              only when a rule enforces it. <code>?window=</code> sets the day window (30 by
              default).
            </td>
            <td>HTTP: <code>GET /api/coverage/threats</code></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/findings">Findings</Link> <code>/app/findings</code></td>
            <td>Triage, resolve or suppress what was detected.</td>
            <td><code>agentfox findings</code></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/traces">Traces</Link> <code>/app/traces</code></td>
            <td>One request taken apart, and why it was blocked.</td>
            <td>HTTP: <code>GET /api/traces</code></td>
          </tr>
          <tr>
            <td colSpan={3}><strong>Test</strong></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/evals">Evaluation</Link> <code>/app/evals</code></td>
            <td>Suites, runs, SLOs, drift, red-team campaigns.</td>
            <td><code>agentfox test run</code>, <code>agentfox test redteam</code></td>
          </tr>
          <tr>
            <td colSpan={3}><strong>Govern</strong></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/policies">Policies</Link> <code>/app/policies</code></td>
            <td>Rules and modes, simulation, canary, detector tuning, judgment posture.</td>
            <td><code>agentfox policy list</code></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/access-and-sources">Access control</Link> <code>/app/entitlement</code></td>
            <td>Who a shared agent is answering for, and what they may see.</td>
            <td><code>agentfox declare principal</code>, <code>agentfox permit user</code></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/approvals">Approvals</Link> <code>/app/approvals</code></td>
            <td>Decide held tool calls; work the hand-off queue.</td>
            <td>HTTP for approvals; <code>agentfox report escalations</code></td>
          </tr>
          <tr>
            <td><Link href="/docs/app/compliance">Compliance</Link> <code>/app/compliance</code></td>
            <td>Controls, frameworks, risk register, evidence, legal hold, board snapshot.</td>
            <td><code>agentfox report status</code></td>
          </tr>
        </tbody>
      </table>
      <p>
        The theme control sits at the foot of the sidebar: Light, Match system, Dark. It is
        the same control as on the public site and is remembered in this browser only.{" "}
        <code>/app/glossary</code> defines every term the app uses; it is not in the sidebar,
        but search finds it.
      </p>

      <h2 id="overview">Overview</h2>
      <InTheApp path="/app">Overview</InTheApp>
      <p>
        Overview answers one question: is anything wrong right now. It has two states.
      </p>
      <ul>
        <li>
          <strong>Nothing is sending traffic yet.</strong> Shown until the gateway has
          recorded a single trace. It shows the one line that starts recording (
          <code>import agentfox; agentfox.auto()</code>), a link to Start here, and the
          coverage strip below.
        </li>
        <li>
          <strong>Connected.</strong> If nothing needs attention you see &quot;Nothing needs
          attention&quot; with the number of governed traces and enforced decisions.
          Otherwise:
        </li>
      </ul>
      <table>
        <thead>
          <tr>
            <th>Panel</th>
            <th>What it shows</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Four stat cards</td>
            <td>
              Critical and high-priority items needing attention; decisions with a{" "}
              <code>block</code> verdict in the last 24 hours (&quot;stopped
              automatically&quot;); decisions made in observe mode in the same window
              (&quot;flagged but allowed&quot;). They count what detectors found in text; tool
              containment is on Policies.
            </td>
            <td><code>GET /api/attention</code></td>
          </tr>
          <tr>
            <td>Needs attention</td>
            <td>
              The six most severe items: open findings, hand-offs past their SLA, and agents
              sending traffic that were never registered. Identical findings fold into one row
              marked <code>×N</code>. Each row links to the finding, the escalation tab or the
              agent.
            </td>
            <td><code>GET /api/attention</code></td>
          </tr>
          <tr>
            <td>What is switched on</td>
            <td>
              Policy rules enforcing out of all rules, detectors running, attack simulations
              available, and controls effective out of those assessed. Each number links to the
              page that lists them.
            </td>
            <td><code>/api/policies</code>, <code>/api/detectors</code>, <code>/api/redteam/probes</code>, <code>/api/compliance/status</code></td>
          </tr>
          <tr>
            <td>Inventory</td>
            <td>Agents, unregistered, without an owner, knowledge boundaries, control effectiveness.</td>
            <td><code>/api/agents</code>, <code>/api/onboarding</code></td>
          </tr>
          <tr>
            <td>Next</td>
            <td>The first unfinished step of the Start here checklist.</td>
            <td><code>GET /api/onboarding</code></td>
          </tr>
        </tbody>
      </table>
      <p>
        The attention queue does not cover the Compliance risk register or agents without a
        risk assessment; the board snapshot does.
      </p>

      <h2>Top bar: counts, search, notifications, account</h2>
      <ul>
        <li>
          <strong>Critical / high counts</strong> are the same numbers as the first two
          Overview cards, visible on every page.
        </li>
        <li>
          <strong>Search</strong> opens with <code>⌘K</code> on macOS or <code>Ctrl+K</code>{" "}
          elsewhere, and the same key closes it; so does <code>Esc</code>. Arrow keys move,
          Enter opens. It matches page names and their group, including entries that are tabs
          rather than sidebar items: Connect GitHub, Connect a hosted API, API tokens,
          Guardrail tuning, Judgment posture, Egress, Escalation, Board view, OWASP LLM Top 10,
          OWASP Agentic, MITRE ATLAS and Glossary. Paste a trace id (<code>trc_…</code>) or a
          finding id (<code>fnd_…</code>) and the first result jumps straight to it. It does
          not search the contents of records.
        </li>
        <li>
          <strong>Notifications</strong> (the bell) is the attention queue from Overview: the
          badge is the total, the list shows the six most severe. When it is empty it says so,
          and points at the board snapshot for what it does not cover.
        </li>
        <li>
          <strong>Account menu</strong>: signed-in email, workspace, role, and links to
          Connect, API tokens, the public site, and Sign out.
        </li>
      </ul>

      <h2>Telling demo data apart</h2>
      <p>
        Records made by the demo seed carry a grey <strong>sample data</strong> tag:
        agents (on the list and the agent page), verified sources, and hand-offs whose
        conversation id starts with <code>seed-</code>. The board snapshot says how many of
        the agents it counts are sample data.
      </p>
      <p>
        Traffic recorded by <code>agentfox demo</code> is not tagged. Its findings, traces,
        decisions and approvals belong to the demo agents (<code>support-triage</code>,{" "}
        <code>payments-ops</code>, <code>hr-screening</code>) and to an unregistered{" "}
        <code>marketing-copy-bot</code>, and its red-team findings name tools starting{" "}
        <code>redteam.sim.</code>. To start clean, point the gateway at a new state directory
        or database and run <code>agentfox init</code> without <code>--demo</code>.
      </p>

      <h2>Common tasks</h2>
      <TaskTable
        rows={[
          { task: "Get a local web app with data in it", run: "agentfox init --demo", href: "/docs/app#run-it-on-your-own-machine" },
          { task: "Record demo traffic so Overview fills in", run: "agentfox demo" },
          { task: "Start the gateway the web app talks to", run: "agentfox serve" },
          { task: "Mint a token for a seeded user", run: "agentfox admin auth issue admin@example.com --name dashboard" },
          { task: "See the same queue as Overview in a terminal", run: "agentfox findings", href: "/docs/app/findings" },
          { task: "Jump to a trace or finding by id", run: "⌘K, paste the id" },
        ]}
      />

      <h2>What can go wrong</h2>
      <ul>
        <li>
          <strong>Every <code>/app</code> page sends you to <code>/login</code>.</strong> There
          is no session cookie. Sign in, or on a local instance set the cookie as above.
        </li>
        <li>
          <strong>&quot;Control-plane API unreachable.&quot;</strong> The web app cannot reach{" "}
          <code>AGENTFOX_API_URL</code>. Check the gateway is up with{" "}
          <code>curl http://127.0.0.1:8080/api/health</code>.
        </li>
        <li>
          <strong>&quot;Your session has expired.&quot;</strong> The token in the cookie was
          revoked, expired, or belongs to another gateway. Sign in again.
        </li>
        <li>
          <strong>Sign-in fails at &quot;could not provision an account&quot;.</strong> The
          service secret differs between the web app and the gateway.
        </li>
        <li>
          <strong>Overview stays on &quot;Nothing is sending traffic yet&quot; after{" "}
          <code>--demo</code>.</strong> The seed records no traces. Run{" "}
          <code>agentfox demo</code>, or govern a real agent.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>No invite flow and no shared workspaces; one GitHub identity, one workspace.</li>
        <li>No sign-in other than GitHub.</li>
        <li>
          Some areas have no screen: capability grants, tool declarations and change
          proposals are CLI and HTTP only. The pages that mention them say so.
        </li>
        <li>
          A few in-app hints still show command names from before the CLI was consolidated.
          They run as hidden aliases; these docs give the current names.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/app/start", label: "Start here and connect", why: "the checklist, repository scans and API tokens" },
          { href: "/docs/app/findings", label: "Findings", why: "the queue Overview summarises" },
          { href: "/docs/self-host", label: "Self-hosting", why: "the full stack, not just the web app" },
          { href: "/docs/app/playground", label: "Playground", why: "try enforcement without an account" },
        ]}
      />
    </article>
  );
}

import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, InTheApp, NextSteps, Output, Step, Steps, TaskTable } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Monitor connected sources",
  description:
    "Re-scan connected GitHub repositories, hosted-API specs and MCP servers on a schedule and on every push, turn what changed into findings, and alert Slack.",
  path: "/docs/guides/monitoring",
});

const cli = (path: string) => `/docs/reference/cli#cmd-${path.replace(/\s+/g, "-")}`;

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>Monitor connected sources</h1>
      <p className="docs-lede">
        A scan tells you what a repository could do on the day you ran it. A monitor runs
        that scan again on its own, on a schedule and on every push, and tells you what
        changed: a new lethal trifecta, a model call that lost its governance, a new tool, a
        new destructive endpoint.
      </p>

      <h2>When to use this</h2>
      <ul>
        <li>You connected a repository or an API once and want to hear when it changes, without anyone re-running a scan.</li>
        <li>Your agents ship several times a day and a reviewer cannot read every diff for new tools.</li>
        <li>An MCP server you depend on can change its tools after you reviewed them.</li>
      </ul>

      <TaskTable
        rows={[
          { task: "See what is monitored", run: "agentfox scan monitors list", href: cli("scan monitors list") },
          { task: "Watch a repository", run: "agentfox scan monitors add github_repo owner/repo", href: cli("scan monitors add") },
          { task: "Watch an API's OpenAPI document", run: "agentfox scan monitors add hosted_api https://…/openapi.json", href: cli("scan monitors add") },
          { task: "Run one now", run: "agentfox scan monitors run owner/repo", href: cli("scan monitors run") },
          { task: "Pause or resume one", run: "agentfox scan monitors pause owner/repo", href: cli("scan monitors pause") },
          { task: "Run scheduled work on a self-hosted box", run: "agentfox admin jobs run-due", href: cli("admin jobs run-due") },
          { task: "Rescan on every push", run: "POST /api/integrations/github/webhook", href: "#push" },
          { task: "Send alerts to Slack", run: "AGENTFOX_SLACK_WEBHOOK_URL", href: "#alerts" },
        ]}
      />

      <h2>What is watched, and what counts as a change</h2>
      <p>
        You rarely create a monitor yourself. One is created when you connect and scan a
        GitHub repository, scan a hosted API with its OpenAPI URL, or register an MCP server
        (from the web app, the API, or <code>agentfox scan mcp</code>).
      </p>
      <table>
        <thead>
          <tr>
            <th>Kind</th>
            <th>Each run</th>
            <th>Default interval</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>github_repo</code></td>
            <td>Downloads the repository with the stored GitHub token and runs the same static scan as <Link href="/docs/guides/scan-a-repo">agentfox scan</Link>. Nothing in it is imported or run.</td>
            <td>6 hours, and on every push once the webhook is set up</td>
          </tr>
          <tr>
            <td><code>hosted_api</code></td>
            <td>Fetches the OpenAPI document again (public addresses only, as the first scan did). Never calls an operation.</td>
            <td>6 hours</td>
          </tr>
          <tr>
            <td><code>mcp_server</code></td>
            <td>A remote Streamable HTTP server: reads its <code>tools/list</code> and checks it for drift and hidden instructions. A stdio server is never started; its pushed listings are watched.</td>
            <td>1 hour</td>
          </tr>
          <tr>
            <td><code>deployed_agent</code></td>
            <td>Sends the live probe library to a probe target someone opted in, and opens a finding when an attack that was contained gets through. Created by the opt-in; the target is never probed more than once in its interval.</td>
            <td>The target&apos;s own interval (at least 1 hour)</td>
          </tr>
        </tbody>
      </table>
      <p>
        The first run of a monitor stores a baseline and raises nothing: the scan that created
        it already showed you what was there. Every later run is compared with the run before
        it. Line numbers are ignored, so editing the file above a call is not a change.
      </p>
      <table>
        <thead>
          <tr>
            <th>Finding type</th>
            <th>Severity</th>
            <th>Raised when</th>
            <th>Closed when</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>monitor_lethal_trifecta</code></td>
            <td>critical</td>
            <td>A group of tools or MCP servers can now read private data, read untrusted content and send data out.</td>
            <td>The group no longer has all three.</td>
          </tr>
          <tr>
            <td><code>monitor_governance_removed</code></td>
            <td>high</td>
            <td>A model call that was governed (<code>agentfox.auto()</code>, an AgentFox import) no longer is.</td>
            <td>It is governed again, or removed.</td>
          </tr>
          <tr>
            <td><code>monitor_ungoverned_model_call</code></td>
            <td>high</td>
            <td>A new model call or agent entrypoint appears ungoverned.</td>
            <td>It is governed, or removed.</td>
          </tr>
          <tr>
            <td><code>monitor_new_tool</code>, <code>monitor_new_mcp_server</code></td>
            <td>medium (low for a tool with no risky capability)</td>
            <td>A tool or MCP server appears.</td>
            <td>It is removed. Resolve it yourself once reviewed.</td>
          </tr>
          <tr>
            <td><code>monitor_api_destructive_endpoint</code></td>
            <td>high</td>
            <td>A new <code>DELETE</code>, <code>PUT</code> or <code>PATCH</code>, or a <code>POST</code> whose path or summary says delete, pay, refund, send, transfer, run and the like.</td>
            <td>The operation leaves the spec.</td>
          </tr>
          <tr>
            <td><code>monitor_api_new_endpoint</code></td>
            <td>low</td>
            <td>Any other new operation.</td>
            <td>The operation leaves the spec.</td>
          </tr>
          <tr>
            <td><code>schema_drift</code>, <code>tool_poisoning</code></td>
            <td>high, critical</td>
            <td>An MCP server&apos;s tools changed, or a description carries instructions for the model. These are the same findings <Link href="/docs/guides/mcp">agentfox scan mcp</Link> raises.</td>
            <td>Poisoning: when the description is clean. Drift stays until you review it.</td>
          </tr>
          <tr>
            <td><code>monitor_failing</code></td>
            <td>medium</td>
            <td>Three runs in a row could not read the source (token revoked, repository renamed, spec down).</td>
            <td>The next run succeeds.</td>
          </tr>
        </tbody>
      </table>
      <p>
        One condition is one finding. A second run that sees the same trifecta adds nothing;
        a trifecta that was fixed and comes back reopens the same finding with its history.
        A run that fails, or that reads no source it understands, closes nothing and keeps
        the previous baseline: &quot;could not look&quot; is never reported as &quot;clean&quot;.
      </p>

      <h2>Worked example</h2>
      <Steps>
        <Step title="Watch a repository">
          <p>
            In the web app, connecting and scanning a repository is enough. From the CLI,
            against a deployment that holds a GitHub connection:
          </p>
          <Code>{`agentfox scan monitors add github_repo acme/support-bot --every 6h
agentfox scan monitors run acme/support-bot`}</Code>
          <Output>{`monitoring github_repo acme/support-bot every 6h  mon_01m47cj46n6r95tqcq
github_repo acme/support-bot: baseline`}</Output>
        </Step>
        <Step title="Someone pushes a change">
          <p>
            The push removes <code>agentfox.auto()</code> from <code>agent.py</code> and adds
            a triage bot with three tools. The next run (scheduled, pushed, or by hand):
          </p>
          <Code>{`agentfox scan monitors run acme/support-bot`}</Code>
          <Output>{`github_repo acme/support-bot: changed
  + critical acme/support-bot: new lethal trifecta in support_triage/tools.py
  + high acme/support-bot: governance removed from a model call in support_triage/agent.py
  + high acme/support-bot: new ungoverned model call in support_triage/tools.py
  + medium acme/support-bot: new tool 'read_customer_record' in support_triage/tools.py
  + medium acme/support-bot: new tool 'fetch_url' in support_triage/tools.py
  + medium acme/support-bot: new tool 'send_email' in support_triage/tools.py`}</Output>
          <p>
            Each line is a finding in the queue, with the file, the call and the fix in its
            evidence, and an alert if you set them up.
          </p>
        </Step>
        <Step title="The change is reverted">
          <Output>{`github_repo acme/support-bot: changed
  - critical acme/support-bot: new lethal trifecta in support_triage/tools.py  (cleared)
  - high acme/support-bot: governance removed from a model call in support_triage/agent.py  (cleared)
  …`}</Output>
          <p>
            Closed findings are resolved by <code>agentfox.monitoring</code>, marked automated
            on the audit chain, so nobody mistakes them for a person&apos;s decision.
          </p>
        </Step>
      </Steps>
      <InTheApp path="/app/findings">
        Monitor findings carry subject <code>monitor</code>; filter the queue by type{" "}
        <code>monitor_*</code>.
      </InTheApp>

      <h2 id="schedule">Run it on a schedule</h2>
      <p>
        Monitors are run by the <code>monitors.run</code> job, which the job runner enqueues
        every 10 minutes and which runs only the monitors whose own interval has passed. So
        how often anything runs is decided by how often the runner itself is called; calling
        it more often never runs a monitor early or twice.
      </p>
      <h3>Hosted (Vercel)</h3>
      <p>
        The Vercel cron calls <code>/api/internal/jobs/run</code> once a day (the Hobby tier
        limit). The repository&apos;s <code>.github/workflows/monitors.yml</code> calls it
        every 30 minutes. Give it two repository secrets:
      </p>
      <table>
        <thead>
          <tr>
            <th>Secret</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>AGENTFOX_API_URL</code></td>
            <td>The API&apos;s base URL, e.g. <code>https://api.example.com</code></td>
          </tr>
          <tr>
            <td><code>AGENTFOX_CRON_SECRET</code></td>
            <td>The deployment&apos;s cron secret (its <code>CRON_SECRET</code> or <code>AGENTFOX_CRON_SECRET</code>)</td>
          </tr>
        </tbody>
      </table>
      <p>Without them the workflow prints a line and succeeds, so forks do not fail. Any other scheduler works the same way:</p>
      <Code>{`curl -fsS -X POST -H "Authorization: Bearer $AGENTFOX_CRON_SECRET" \\
  https://api.example.com/api/internal/jobs/run`}</Code>
      <h3>Self-hosted</h3>
      <p>Run one pass of the job runner from cron, a systemd timer or a Kubernetes CronJob:</p>
      <Code title="crontab">{`*/15 * * * *  cd /srv/agentfox && agentfox admin jobs run-due`}</Code>
      <Output>{`scheduled 6, ran 6, recovered 0`}</Output>
      <p>
        <code>AGENTFOX_MONITOR_BATCH_LIMIT</code> (default 5) bounds how many monitors one
        pass runs; the rest stay due for the next. Set <code>AGENTFOX_SCHEDULER_ENABLED=false</code> to
        stop all scheduled work.
      </p>

      <h2 id="push">Rescan on every push</h2>
      <p>
        A push to a monitored repository&apos;s default branch can queue a rescan of exactly
        that commit. In GitHub, open the repository (or organisation) settings, Webhooks, Add
        webhook:
      </p>
      <table>
        <tbody>
          <tr>
            <td>Payload URL</td>
            <td><code>https://&lt;api host&gt;/api/integrations/github/webhook</code></td>
          </tr>
          <tr>
            <td>Content type</td>
            <td><code>application/json</code></td>
          </tr>
          <tr>
            <td>Secret</td>
            <td>The deployment&apos;s <code>AGENTFOX_GITHUB_WEBHOOK_SECRET</code>, or a secret for your connection (below)</td>
          </tr>
          <tr>
            <td>Events</td>
            <td>Just the push event</td>
          </tr>
        </tbody>
      </table>
      <p>On a shared deployment, ask for a secret of your own, shown once:</p>
      <Code>{`curl -fsS -X POST -H "Authorization: Bearer $AGENTFOX_TOKEN" \\
  https://api.example.com/api/integrations/github/webhook-secret`}</Code>
      <Output>{`{"secret":"q7…","payload_path":"/api/integrations/github/webhook","content_type":"application/json","events":["push"]}`}</Output>
      <p>
        Every delivery is checked against <code>X-Hub-Signature-256</code> before anything
        else; an unsigned or wrongly signed one is refused with 401, and with no secret
        configured anywhere the route refuses everything with 503. GitHub&apos;s ping shows
        up as <code>{`{"accepted": true, "event": "ping"}`}</code>. A push to another branch
        is accepted and skipped; set <code>config.branch</code> on the monitor to watch a
        different one. Ten pushes in a minute queue one rescan of the latest commit.
      </p>
      <Callout kind="note" title="On serverless">
        The rescan starts after the response is sent. A platform that freezes the function
        once it has answered leaves the job queued, and the next runner call picks it up.
      </Callout>

      <h2 id="alerts">Alerts</h2>
      <p>
        Monitor findings are findings, so the{" "}
        <Link href="/docs/guides/observability#webhooks">finding webhook</Link> already sends
        them (signed, at or above <code>AGENTFOX_WEBHOOK_MIN_SEVERITY</code>, default high),
        including when one is resolved. For people, add Slack:
      </p>
      <ul>
        <li>
          <code>AGENTFOX_SLACK_WEBHOOK_URL</code>: an incoming-webhook URL for the whole
          deployment, filtered by <code>AGENTFOX_SLACK_MIN_SEVERITY</code> (default medium).
        </li>
        <li>
          A tenant&apos;s own channel, stored encrypted:{" "}
          <code>PUT /api/alerts/slack</code> with{" "}
          <code>{`{"url": "https://hooks.slack.com/services/…", "min_severity": "high"}`}</code>.
          Only <code>hooks.slack.com</code> URLs are accepted. <code>POST /api/alerts/slack/test</code> sends a test message.
        </li>
      </ul>
      <Output title="Slack">{`AgentFox · New · CRITICAL: acme/support-bot: new lethal trifecta in support_triage/tools.py
github_repo acme/support-bot · Open finding`}</Output>
      <p>
        The link points at <code>AGENTFOX_CONSOLE_URL</code>/app/findings/…; without that
        setting the message carries the finding id instead. Both the webhook and Slack need{" "}
        <code>AGENTFOX_ALLOW_EGRESS=true</code>: an alert carries finding titles out of the
        deployment, so with egress off nothing is sent. Fetching the repository, the spec or an
        MCP listing is not gated by it: those are reads you asked for, and carry no data out.
      </p>

      <h2>Over HTTP</h2>
      <table>
        <thead>
          <tr>
            <th>Call</th>
            <th>What it does</th>
          </tr>
        </thead>
        <tbody>
          <tr><td><code>GET /api/monitors</code></td><td>Every monitor, its last result and next run.</td></tr>
          <tr><td><code>POST /api/monitors</code></td><td><code>{`{"kind", "target", "interval_seconds"?, "config"?}`}</code>. 409 if already monitored.</td></tr>
          <tr><td><code>GET /api/monitors/&#123;id&#125;</code></td><td>One monitor and its open findings.</td></tr>
          <tr><td><code>PATCH /api/monitors/&#123;id&#125;</code></td><td>Name, interval (5 minutes to 30 days), config, <code>enabled</code>.</td></tr>
          <tr><td><code>POST /api/monitors/&#123;id&#125;/pause</code>, <code>/resume</code></td><td>Stop or restart scheduled runs. Pausing closes nothing.</td></tr>
          <tr><td><code>POST /api/monitors/&#123;id&#125;/run</code></td><td>Run now through the job queue.</td></tr>
          <tr><td><code>DELETE /api/monitors/&#123;id&#125;</code></td><td>Stop watching. Findings are kept.</td></tr>
        </tbody>
      </table>
      <p>
        Reading is open to every role; changing monitors needs owner, admin, security or
        developer, and Slack settings need owner, admin or security. Full schemas are in the{" "}
        <Link href="/docs/reference/api">HTTP reference</Link>.
      </p>

      <h2>Troubleshooting</h2>
      <ul>
        <li>
          <strong>Status <code>failed</code>, &quot;no GitHub account is connected&quot;</strong>: the
          tenant has no GitHub connection, or it was removed. Connect again from the web app.
        </li>
        <li>
          <strong>Status <code>inconclusive</code></strong>: the rescan read no Python,
          TypeScript or JavaScript. The baseline and findings are kept as they were.
        </li>
        <li>
          <strong>Nothing runs</strong>: check that something calls the runner (the workflow&apos;s
          secrets, your crontab), that <code>AGENTFOX_SCHEDULER_ENABLED</code> is not false, and
          the monitor&apos;s <code>next_run_at</code>.
        </li>
        <li>
          <strong>The webhook answers 401</strong>: the secret in GitHub differs from the
          deployment&apos;s or the connection&apos;s. Rotating the connection secret invalidates the old one.
        </li>
      </ul>

      <h2>Limits</h2>
      <ul>
        <li>Diffs are as good as the static scan: code generated at runtime is invisible to both runs.</li>
        <li>A stdio MCP server&apos;s tools are only seen when someone pushes a listing.</li>
        <li>An MCP server that needs credentials to list its tools cannot be read yet.</li>
        <li>Monitoring reports change. What was already there when the monitor was created is in the scan that created it.</li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/guides/scan-a-repo", label: "Audit a repository", why: "the scan each run repeats" },
          { href: "/docs/guides/mcp", label: "MCP servers", why: "pinning and drift in depth" },
          { href: "/docs/guides/observability#webhooks", label: "Finding webhooks", why: "the signed payload and how to verify it" },
          { href: cli("scan monitors"), label: "agentfox scan monitors reference", why: "every option" },
        ]}
      />
    </article>
  );
}

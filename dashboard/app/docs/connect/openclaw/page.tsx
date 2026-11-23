import type { Metadata } from "next";

import { Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { OPENCLAW_RENDER_DEPLOY_URL, publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "OpenClaw",
  description:
    "Check every tool call an OpenClaw agent makes before it runs: shell, browser, files and the messages it sends. One command starts OpenClaw behind AgentFox.",
  path: "/docs/connect/openclaw",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>OpenClaw</h1>
      <p className="docs-lede">
        Share one OpenClaw with your team without giving it the keys to everything. Every shell
        command, browser step, file write and message it sends is checked by AgentFox first.
      </p>

      <p>
        This is for a team inside one trust boundary. OpenClaw&apos;s own security policy says one
        gateway should not be shared by people who do not trust each other, and a plugin does not
        change that. What AgentFox adds is a check on every action, an approver for the risky ones,
        and a record of all of them.
      </p>

      <h2>Start OpenClaw behind AgentFox</h2>
      <p>
        The kit in <code>deploy/openclaw/</code> starts AgentFox and OpenClaw together, with the
        AgentFox plugin loaded and AgentFox as OpenClaw&apos;s model endpoint.
      </p>
      <Steps>
        <Step title="Fill in the settings">
          <Code>{`git clone https://github.com/architsharm/agentfox && cd agentfox
cp deploy/openclaw/.env.example deploy/openclaw/.env`}</Code>
          <p>
            Set the two AgentFox secrets, your model provider&apos;s key and an OpenClaw token. The model
            key stays in AgentFox: OpenClaw and the people using it never see it.
          </p>
        </Step>
        <Step title="Start it">
          <Code>{`deploy/openclaw/up.sh`}</Code>
          <p>
            It starts AgentFox, tells it what OpenClaw&apos;s tools do, grants them to the{" "}
            <code>openclaw</code> agent, builds the plugin and starts OpenClaw. OpenClaw is on port
            18789 and AgentFox on 3000.
          </p>
        </Step>
        <Step title="Watch, then switch to Block">
          <p>
            AgentFox starts by watching: it records what it would have held and lets the call run.
            Destructive shell commands are blocked from the start. When the decisions look right:
          </p>
          <Code>{`docker compose --env-file deploy/openclaw/.env \\
  -f deploy/docker-compose.yml -f deploy/openclaw/compose.yml \\
  exec gateway agentfox policy enforce tool-containment`}</Code>
          <p>
            Or start in Block straight away with <code>deploy/openclaw/up.sh --block</code>.
          </p>
        </Step>
      </Steps>

      <h3>Or deploy it to Render, with no terminal</h3>
      <p>
        <a href={OPENCLAW_RENDER_DEPLOY_URL} target="_blank" rel="noreferrer">
          Deploy to Render
        </a>{" "}
        sets up the same kit on your own Render account: Postgres, the AgentFox gateway and dashboard, and
        OpenClaw with the plugin built in. Render asks for your model key and an AgentFox agent key
        (enter <code>unregistered</code> until you create one in the dashboard); neither is stored
        in the repository. The gateway and OpenClaw need Render&apos;s <code>starter</code>{" "}
        instance type. To sign in, open the gateway&apos;s Shell in Render and run{" "}
        <code>agentfox admin users create you@example.com --role owner --token</code>. OpenClaw is
        public there, behind the <code>OPENCLAW_GATEWAY_TOKEN</code> Render generates, where the
        local kit only listens on your machine. The blueprint is{" "}
        <code>deploy/openclaw/render.yaml</code>.
      </p>

      <h2>Add it to an OpenClaw you already run</h2>
      <Steps>
        <Step title="Build the plugin">
          <Code>{`cd sdk/openclaw && npm ci && npm run build`}</Code>
        </Step>
        <Step title="Load it in openclaw.json">
          <Code lang="json" title="openclaw.json">{`{
  "plugins": {
    "load": { "paths": ["/path/to/agentfox/sdk/openclaw"] },
    "entries": {
      "agentfox": {
        "enabled": true,
        "config": { "baseUrl": "http://localhost:8080", "apiKey": "nom_agt_…" }
      }
    }
  }
}`}</Code>
        </Step>
        <Step title="Declare and grant OpenClaw's tools">
          <p>Where the <code>agentfox</code> CLI reaches your AgentFox database:</p>
          <Code>{`deploy/openclaw/agentfox-setup.sh openclaw`}</Code>
        </Step>
      </Steps>

      <h2>What is checked</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>OpenClaw does</th>
            <th>AgentFox</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Runs a shell command</td>
            <td>Blocks destructive ones (recursive delete, <code>curl | sh</code>, reading credential files). Holds one built from content it read.</td>
          </tr>
          <tr>
            <td>Sends a message (WhatsApp, Slack, Teams…)</td>
            <td>Lets it through when the recipient and text came from the user. Holds it when either was copied out of a web page, a file or another tool&apos;s output.</td>
          </tr>
          <tr>
            <td>Uses the browser, writes files</td>
            <td>Checked against what the agent was granted and where the arguments came from.</td>
          </tr>
          <tr>
            <td>Schedules a job, reconfigures itself, starts another agent</td>
            <td>Waits for an approver every time.</td>
          </tr>
          <tr>
            <td>Calls a tool nobody granted</td>
            <td>Recorded as ungranted; refused in Block.</td>
          </tr>
        </tbody>
      </table></div>

      <h2>Approvals</h2>
      <p>
        By default a held call is refused with a link. An approver decides in AgentFox under
        Approvals, and when the agent tries the same call again it runs once. So the person chatting
        with OpenClaw cannot approve their own risky call. To use OpenClaw&apos;s own approval prompt
        instead, set <code>&quot;approvals&quot;: &quot;openclaw&quot;</code> in the plugin&apos;s config.
      </p>

      <h2>If AgentFox is down</h2>
      <p>
        The plugin fails closed: a call AgentFox cannot check does not run. Set{" "}
        <code>&quot;failMode&quot;: &quot;open&quot;</code> to let calls through instead.
      </p>

      <h2>What it does not cover</h2>
      <ul>
        <li>Code a skill or plugin runs on its own, outside a tool call.</li>
        <li>What a shell command starts after AgentFox allowed it.</li>
        <li>A held call in a run nobody is watching, such as a cron job: it is refused, not queued.</li>
        <li>
          In Block, a browser step or file write built from a fetched page is held. Research-heavy
          agents should watch first.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/govern/approvals", label: "Approvals", why: "deciding held calls" },
          { href: "/docs/govern", label: "Tool access", why: "what the openclaw agent may call" },
          { href: "/docs/connect/http", label: "Any language (HTTP)", why: "the guard API the plugin calls" },
        ]}
      />
    </article>
  );
}

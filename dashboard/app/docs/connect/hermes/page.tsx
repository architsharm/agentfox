import type { Metadata } from "next";

import { Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Hermes Agent",
  description:
    "Check every tool call Hermes Agent makes before it runs: terminal commands, code, the browser and file writes. One command starts Hermes behind AgentFox.",
  path: "/docs/connect/hermes",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Hermes Agent</h1>
      <p className="docs-lede">
        Let Hermes Agent run commands, write code and drive a browser for your team, with every one
        of those actions checked by AgentFox first.
      </p>

      <p>
        A plugin on Hermes&apos;s <code>pre_tool_call</code> hook asks AgentFox about each tool call
        before it runs. AgentFox allows it, blocks it with the rule&apos;s reason, or holds it for an
        approver, and records all of them. This is an independent integration, not made or endorsed by
        Nous Research.
      </p>

      <h2>Start Hermes behind AgentFox</h2>
      <p>
        The kit in <code>deploy/hermes/</code> starts AgentFox and builds Hermes with the AgentFox
        plugin loaded and AgentFox as its model endpoint.
      </p>
      <Steps>
        <Step title="Fill in the settings">
          <Code>{`git clone https://github.com/architsharm/agentfox && cd agentfox
cp deploy/hermes/.env.example deploy/hermes/.env`}</Code>
          <p>
            Set the two AgentFox secrets and your model provider&apos;s key. The model key stays in
            AgentFox: Hermes and the people using it never see it.
          </p>
        </Step>
        <Step title="Start it">
          <Code>{`deploy/hermes/up.sh`}</Code>
          <p>
            It starts AgentFox on port 3000, tells it what Hermes&apos;s tools do, grants them to the{" "}
            <code>hermes</code> agent and builds Hermes. It then prints the command that opens a chat
            with Hermes.
          </p>
        </Step>
        <Step title="Watch, then switch to Block">
          <p>
            AgentFox starts by watching: it records what it would have held and lets the call run.
            Destructive shell commands are blocked from the start. When the decisions look right:
          </p>
          <Code>{`docker compose --env-file deploy/hermes/.env \\
  -f deploy/docker-compose.yml -f deploy/hermes/compose.yml \\
  exec gateway agentfox policy enforce tool-containment`}</Code>
          <p>
            Or start in Block straight away with <code>deploy/hermes/up.sh --block</code>.
          </p>
        </Step>
      </Steps>

      <h2>Add it to a Hermes you already run</h2>
      <Steps>
        <Step title="Install the plugin">
          <Code>{`pip install agentfox   # into the Python environment Hermes runs in
cp -r sdk/hermes ~/.hermes/plugins/agentfox`}</Code>
        </Step>
        <Step title="Enable it and point it at AgentFox">
          <Code lang="yaml" title="~/.hermes/config.yaml">{`plugins:
  enabled:
    - agentfox`}</Code>
          <Code title="~/.hermes/.env">{`AGENTFOX_URL=http://localhost:8080
AGENTFOX_AGENT_KEY=nom_agt_…`}</Code>
        </Step>
        <Step title="Declare and grant Hermes's tools">
          <p>Where the <code>agentfox</code> CLI reaches your AgentFox database:</p>
          <Code>{`deploy/hermes/agentfox-setup.sh hermes`}</Code>
        </Step>
      </Steps>

      <h2>What is checked</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Hermes does</th>
            <th>AgentFox</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Runs a terminal command or code</td>
            <td>Blocks destructive ones (recursive delete, <code>curl | sh</code>, reading credential files). Holds one built from content it read.</td>
          </tr>
          <tr>
            <td>Drives the browser or the desktop, sends a message</td>
            <td>Lets it through when the arguments came from the user. Holds it when they were copied out of a web page, a file or another tool&apos;s output.</td>
          </tr>
          <tr>
            <td>Writes or patches files</td>
            <td>Checked against what the agent was granted and where the arguments came from.</td>
          </tr>
          <tr>
            <td>Schedules a job, starts a subagent, edits a skill, uses stored logins</td>
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
        Approvals, and when Hermes tries the same call again it runs once. So the person chatting
        with Hermes cannot approve their own risky call. To use Hermes&apos;s own approval gate
        instead, set <code>AGENTFOX_APPROVALS=hermes</code>.
      </p>

      <h2>If AgentFox is down</h2>
      <p>
        The plugin fails closed: a call AgentFox cannot check does not run. Set{" "}
        <code>AGENTFOX_FAIL_MODE=open</code> to let calls through instead.
      </p>

      <h2>What it does not cover</h2>
      <ul>
        <li>Code a skill or plugin runs on its own, outside a tool call.</li>
        <li>What a terminal command starts after AgentFox allowed it.</li>
        <li>A held call in a run nobody is watching, such as a cron job: it is refused, not queued.</li>
        <li>
          In Block, a browser step or file write built from a fetched page is held. Research-heavy
          agents should watch first.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/govern/approvals", label: "Approvals", why: "deciding held calls" },
          { href: "/docs/govern", label: "Tool access", why: "what the hermes agent may call" },
          { href: "/docs/connect/http", label: "Any language (HTTP)", why: "the guard API the plugin calls" },
        ]}
      />
    </article>
  );
}

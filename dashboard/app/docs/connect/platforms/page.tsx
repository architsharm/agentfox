import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Step, Steps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Voice and hosted platforms",
  description:
    "Check tool calls from Vapi, Retell, Copilot Studio and AWS AgentCore Gateway before they run, record finished calls, and find hosted agents in exported files.",
  path: "/docs/connect/platforms",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Voice and hosted platforms</h1>
      <p className="docs-lede">
        Check each tool call a hosted agent makes before it runs, and record its finished calls, by
        pointing the platform&apos;s tool URL at AgentFox.
      </p>

      <table>
        <thead>
          <tr>
            <th>Platform</th>
            <th>What is checked</th>
            <th>Where the URL goes</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Vapi</td>
            <td>Each tool call; the end-of-call report is recorded</td>
            <td>The tool&apos;s (or assistant&apos;s) Server URL, with a Bearer credential</td>
          </tr>
          <tr>
            <td>Retell</td>
            <td>Each custom function call, after its signature is verified; finished calls are recorded</td>
            <td>The custom function&apos;s URL, and the agent&apos;s webhook URL</td>
          </tr>
          <tr>
            <td>Copilot Studio</td>
            <td>Each planned tool call, after the Entra token is verified</td>
            <td>External threat detection, in the Power Platform admin center</td>
          </tr>
          <tr>
            <td>AWS AgentCore Gateway</td>
            <td>Each MCP <code>tools/call</code></td>
            <td>A Lambda REQUEST interceptor (below)</td>
          </tr>
        </tbody>
      </table>
      <p>
        An allowed call goes on to your own tool server unchanged. A refused one never reaches it: the
        agent says the action was not done, or that it was sent for approval. Once a person approves,
        the same call runs when the agent tries it again.
      </p>

      <h2>Vapi, Retell and Copilot Studio</h2>
      <Callout kind="note" title="API only for now">
        <p>
          Connections are created with the API, not in the app yet. You need an API key from{" "}
          <strong>Settings</strong>, <strong>API keys</strong>, and the agent already added to AgentFox.
        </p>
      </Callout>

      <Steps>
        <Step title="Create a connection">
          <p>
            Give the platform and, for Vapi and Retell, your tool server&apos;s URL. Retell also needs
            your Retell API key as <code>secret</code>; Copilot Studio needs <code>config</code> with the
            Entra <code>tenant_id</code> and <code>app_id</code>.
          </p>
          <Code>{`curl -s -X POST "$AGENTFOX_URL/api/agents/support-voice/platform-connections" \\
  -H "Authorization: Bearer $AGENTFOX_API_KEY" -H 'Content-Type: application/json' \\
  -d '{"platform": "vapi", "upstream_url": "https://tools.example.com/vapi"}'`}</Code>
          <p>
            The answer has a <code>hook_url</code>. For Vapi it also has a <code>secret</code>, shown
            once.
          </p>
        </Step>

        <Step title="Paste the URL into the platform">
          <ul>
            <li>
              <strong>Vapi:</strong> set the tool&apos;s Server URL to <code>hook_url</code>, with a Bearer
              credential holding the secret. Finished calls arrive at the same URL.
            </li>
            <li>
              <strong>Retell:</strong> set the custom function&apos;s URL to <code>hook_url</code>, and the
              agent&apos;s webhook URL to <code>hook_url</code> followed by <code>/webhook</code>.
            </li>
            <li>
              <strong>Copilot Studio:</strong> enter <code>hook_url</code> as the threat detection
              endpoint. Also set the option to block the query when the endpoint errors; Microsoft lets
              it through by default.
            </li>
          </ul>
        </Step>

        <Step title="Make a call and look at Traces">
          <p>
            Each tool call shows on the agent&apos;s <strong>Activity</strong> tab and on{" "}
            <strong>Traces</strong>. A finished call is recorded as one run with its turns, personal data
            and secrets masked.
          </p>
        </Step>
      </Steps>
      <p>
        <code>GET</code> the same path to list an agent&apos;s connections, and{" "}
        <code>DELETE …/platform-connections/&#123;id&#125;</code> to switch one off: its URL then answers
        404. Fields are in the <Link href="/docs/reference/api">HTTP API reference</Link>.
      </p>

      <h2>AWS AgentCore Gateway</h2>
      <p>
        A Lambda you deploy with SAM sends each MCP tool call to AgentFox before the gateway passes it to
        a target. Issue the agent a key, store it in Secrets Manager, deploy the function, and attach it
        as the gateway&apos;s REQUEST interceptor. If AgentFox cannot be reached in time, the call is
        refused unless you set <code>FailMode=open</code>. Steps are in the{" "}
        <a href="https://github.com/architsharm/agentfox/blob/main/deploy/aws-agentcore-interceptor/README.md">
          interceptor README
        </a>
        .
      </p>

      <h2 id="discovery">Find hosted agents in exported files</h2>
      <p>
        If your repository keeps a platform&apos;s exported agent files, <code>agentfox init</code> and{" "}
        <code>agentfox scan</code> list those agents and their tools, without calling the platform:
        Vapi, Retell, ElevenLabs, n8n, Dify, Flowise, Langflow, Voiceflow, Dialogflow, Copilot Studio,
        Agentforce and Amazon Bedrock. An agent that lives only in the vendor&apos;s console leaves
        nothing to read. See <Link href="/docs/discover">Map your agents</Link>.
      </p>

      <h2>Limits</h2>
      <ul>
        <li>Numbers spoken as words (&quot;four one one one&quot;) are not masked in recorded calls.</li>
        <li>
          Self-hosted, storing a connection&apos;s secret needs <code>AGENTFOX_TOKEN_ENCRYPTION_KEY</code>;
          without it the API answers 503.
        </li>
      </ul>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "grant the tools your hosted agent calls" },
          { href: "/docs/govern/approvals", label: "Approvals", why: "where held calls wait for a person" },
        ]}
      />
    </article>
  );
}

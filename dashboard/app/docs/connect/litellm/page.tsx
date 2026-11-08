import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "LiteLLM proxy",
  description:
    "Add AgentFox to a LiteLLM proxy's config so every agent behind it is checked, with no change to the agents.",
  path: "/docs/connect/litellm",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>LiteLLM proxy</h1>
      <p className="docs-lede">
        Add AgentFox to your LiteLLM proxy&apos;s config, and every agent behind the proxy is checked
        without changing any of them.
      </p>

      <h2>Before you start</h2>
      <ul>
        <li>
          A workspace key: the one from <strong>Create a key</strong> on the Agents page, or a new one
          under Settings, API keys.
        </li>
      </ul>

      <Steps>
        <Step title="Install on the proxy's machine">
          <Code>{`pip install agentfox
export AGENTFOX_URL=https://…
export AGENTFOX_API_KEY=nom_api_…`}</Code>
        </Step>

        <Step title="Add the guardrail to config.yaml">
          <Code lang="yaml" title="config.yaml">{`guardrails:
  - guardrail_name: agentfox
    litellm_params:
      guardrail: agentfox.frameworks.litellm_guardrail.AgentFoxGuardrail
      mode: [pre_call, post_call]
      default_on: true
      api_base: os.environ/AGENTFOX_URL
      api_key: os.environ/AGENTFOX_API_KEY`}</Code>
        </Step>

        <Step title="Name your agents">
          <p>
            Each call is recorded against an agent: <code>agent</code> in the config, else{" "}
            <code>metadata.agentfox_agent</code> on the request, else the LiteLLM key&apos;s alias, else{" "}
            <code>litellm</code>. Giving each agent its own LiteLLM key is usually enough.
          </p>
        </Step>

        <Step title="Restart the proxy and send a request">
          <p>The call shows up on the agent&apos;s Activity tab with the checks it went through.</p>
          <Screenshot {...SCREENS.activity} />
        </Step>
      </Steps>

      <h2>What is checked</h2>
      <div className="docs-table"><table>
        <thead>
          <tr>
            <th>When</th>
            <th>What</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Before the model</td>
            <td>The newest user message and every tool result, for prompt attacks, secrets and personal data.</td>
          </tr>
          <tr>
            <td>After the model</td>
            <td>Each tool call the model asks for, against what that agent may do, then the reply.</td>
          </tr>
          <tr>
            <td>Streaming</td>
            <td>Text streams as normal. Once a tool call starts, the rest is held until it is checked.</td>
          </tr>
        </tbody>
      </table></div>
      <p>
        A stopped call returns HTTP 400 with the rule&apos;s message. A call that needs approval carries
        an <code>approval_id</code>; once someone approves it, the same call sent again goes through
        once. Content rules start in Watch, so you see what they would stop first; tool access applies
        from the start.
      </p>

      <h2>If AgentFox is down</h2>
      <p>
        The proxy refuses the call with HTTP 503, so nothing goes unchecked. Add{" "}
        <code>fail_open: true</code> under <code>litellm_params</code> to let calls through instead.
      </p>

      <NextSteps
        items={[
          { href: "/docs/govern", label: "Tool access", why: "what each agent behind the proxy may call" },
          { href: "/docs/connect/http", label: "Any language (HTTP)", why: "the routes the guardrail calls" },
        ]}
      />
    </article>
  );
}

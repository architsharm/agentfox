import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "LiteLLM proxy",
  description:
    "Add AgentFox to a LiteLLM proxy's config so every agent behind it is checked, with no change to the agents.",
  path: "/docs/guides/litellm",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Guide</p>
      <h1>LiteLLM proxy</h1>
      <p className="docs-lede">
        If your agents already call models through a LiteLLM proxy, add AgentFox as a
        guardrail in its <code>config.yaml</code>. Every agent behind the proxy is checked,
        and none of them changes.
      </p>

      <h2>Install</h2>
      <p>On the machine that runs the proxy:</p>
      <Code>{`pip install agentfox`}</Code>
      <p>
        You also need an AgentFox gateway it can reach: <code>agentfox serve</code> on your
        own server, or the hosted one. Create an API token in the dashboard under Settings.
      </p>

      <h2>Configure</h2>
      <Code lang="yaml" title="config.yaml">{`guardrails:
  - guardrail_name: agentfox
    litellm_params:
      guardrail: agentfox.frameworks.litellm_guardrail.AgentFoxGuardrail
      mode: [pre_call, post_call]
      default_on: true
      api_base: os.environ/AGENTFOX_URL
      api_key: os.environ/AGENTFOX_API_TOKEN
      # agent: support-bot     # optional; see "Which agent" below
      # fail_open: true        # let calls through if AgentFox is unreachable`}</Code>

      <h2>What is checked</h2>
      <ul>
        <li>
          <strong>Before the model:</strong> the newest user message and every tool result in
          the request, for prompt injection, secrets and personal data. A redaction rewrites
          the message before it is sent.
        </li>
        <li>
          <strong>After the model:</strong> each tool call the model asks for, against what
          that agent is allowed to do. The request&apos;s messages go with it, so an argument
          copied out of a tool result counts as untrusted without the agent declaring
          anything. Then the reply text.
        </li>
        <li>
          <strong>Streaming:</strong> text streams through as normal. Once a tool call
          starts, the rest of the stream is held and the call is checked when it is complete.
        </li>
      </ul>
      <p>
        A stopped call returns HTTP 400 with the rule&apos;s message. If the call needs a
        person&apos;s approval, the error carries an <code>approval_id</code>; once someone
        approves it, the same call sent again goes through once.
      </p>
      <Callout>
        New rules start in watch mode: nothing is blocked, and the dashboard shows what would
        have been. See <Link href="/docs/guides/tuning">tuning</Link> before you enforce.
      </Callout>

      <h2>Which agent</h2>
      <p>
        Each call is recorded against one agent, chosen in this order: <code>agent</code> in
        the config; <code>metadata.agentfox_agent</code> on the request; the LiteLLM
        key&apos;s alias; otherwise <code>litellm</code>. Giving each agent its own LiteLLM
        key is usually enough. Pass <code>metadata.session_id</code> to group one
        conversation into one run.
      </p>

      <h2>If AgentFox is down</h2>
      <p>
        By default the proxy refuses the call with HTTP 503, so nothing goes unchecked. Set{" "}
        <code>fail_open: true</code> to let calls through instead; each one is logged.
      </p>
    </article>
  );
}

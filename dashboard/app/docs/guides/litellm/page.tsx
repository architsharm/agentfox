import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps } from "@/components/docs/blocks";
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
        The proxy needs an AgentFox gateway it can reach (the hosted one, or{" "}
        <code>agentfox serve</code> on your own server) and a workspace API key (
        <code>nom_api_…</code>): the one from <strong>Create a key</strong> on the setup
        card, or a new one under Settings → API keys.
      </p>
      <Code>{`export AGENTFOX_URL=https://…
export AGENTFOX_API_KEY=nom_api_…`}</Code>

      <h2>Configure</h2>
      <Code lang="yaml" title="config.yaml">{`guardrails:
  - guardrail_name: agentfox
    litellm_params:
      guardrail: agentfox.frameworks.litellm_guardrail.AgentFoxGuardrail
      mode: [pre_call, post_call]
      default_on: true
      api_base: os.environ/AGENTFOX_URL
      api_key: os.environ/AGENTFOX_API_KEY
      # agent: support-bot     # optional; see "Which agent" below
      # fail_open: true        # let calls through if AgentFox is unreachable`}</Code>

      <h2>What is checked</h2>
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>What</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Before the model</td>
            <td>
              The newest user message and every tool result in the request, for prompt
              injection, secrets and personal data. A redaction rewrites the message before it
              is sent.
            </td>
          </tr>
          <tr>
            <td>After the model</td>
            <td>
              Each tool call the model asks for, against what that agent is allowed to do,
              then the reply text. The request&apos;s messages go with the tool call, so an
              argument copied out of a tool result counts as untrusted without the agent
              declaring anything.
            </td>
          </tr>
          <tr>
            <td>Streaming</td>
            <td>
              Text streams through as normal. Once a tool call starts, the rest of the stream
              is held and the call is checked when it is complete.
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        A stopped call returns HTTP 400 with the rule&apos;s message. If the call needs a
        person&apos;s approval, the error carries an <code>approval_id</code>; once someone
        approves it, the same call sent again goes through once.
      </p>
      <Callout>
        Content rules start in watch mode: nothing is blocked, and the dashboard shows what
        would have been. Tool containment applies from the start. Read{" "}
        <Link href="/docs/guides/tuning">Tune detectors</Link> before you switch content rules
        to blocking.
      </Callout>

      <h2>Which agent</h2>
      <p>
        Each call is recorded against one agent, chosen in this order: <code>agent</code> in
        the config; <code>metadata.agentfox_agent</code> on the request; the LiteLLM
        key&apos;s alias; otherwise <code>litellm</code>. Giving each agent its own LiteLLM
        key is usually enough. Pass <code>metadata.session_id</code> (or LiteLLM&apos;s own{" "}
        <code>litellm_session_id</code>) to group one conversation into one run.
      </p>

      <h2>If AgentFox is down</h2>
      <p>
        By default the proxy refuses the call with HTTP 503, so nothing goes unchecked. Set{" "}
        <code>fail_open: true</code> to let calls through instead; the proxy logs a warning
        for each one.
      </p>

      <NextSteps
        items={[
          { href: "/docs/guides/contain-tool-calls", label: "Contain tool calls", why: "what each agent behind the proxy may call" },
          { href: "/docs/guides/approvals", label: "Approvals", why: "where a held call waits for a person" },
          { href: "/docs/guides/gateway", label: "Any language: the gateway", why: "the routes the guardrail calls" },
        ]}
      />
    </article>
  );
}

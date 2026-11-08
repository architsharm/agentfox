import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Who may see what",
  description:
    "When one agent serves many people, filter what retrieval returns down to what the person asking may see.",
  path: "/docs/govern/data-access",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Who may see what</h1>
      <p className="docs-lede">
        Make an agent that serves many people show each person only the documents they may see, even
        though the agent itself can read them all.
      </p>

      <p>
        <strong>Before you start:</strong> your retrieval needs to know who is asking, for example the
        signed-in user&apos;s email.
      </p>

      <Steps>
        <Step title="Add the people and teams">
          <p>
            Go to <strong>Settings → Data access</strong> and press <strong>+ Add a person or group</strong>.
            Give their email or team name, the teams they belong to, and any sensitive categories they are
            cleared to see.
          </p>
          <Screenshot {...SCREENS.dataAccess} />
        </Step>

        <Step title="Grant them sources">
          <Tabs>
            <Tab label="In the app">
              <p>
                Press <strong>+ Add a grant</strong>. Pick the source (a name or a pattern such as{" "}
                <code>kb/support/*</code>) and the person or team. Tick a sensitive category only if the
                grant covers one.
              </p>
            </Tab>
            <Tab label="CLI">
              <Code>{`agentfox declare principal ana@example.com --groups support
agentfox permit user "kb/support/*" support`}</Code>
            </Tab>
          </Tabs>
          <p>
            Anything without a grant is hidden from everyone. A sensitive category, such as insider
            financial information, also needs the matching clearance on the person.
          </p>
        </Step>

        <Step title="Filter retrieval for the caller">
          <p>
            Between retrieval and the model, send the caller and the retrieved chunks to{" "}
            <code>POST /api/entitlement/filter</code>. Use the chunks it returns as the model&apos;s context.
            With <code>agentfox.auto()</code>, pass <code>agentfox_principal</code> and{" "}
            <code>agentfox_chunks</code> on the model call instead.
          </p>
          <Code lang="python">{`client.chat.completions.create(
    model="gpt-4o-mini", messages=messages,
    agentfox_principal="ana@example.com",
    agentfox_chunks=chunks,
)`}</Code>
        </Step>

        <Step title="Check what was held back">
          <p>
            Once checks run, the page shows how much content was held back and why. That share is what the
            agent could reach and the caller could not. It is not an error rate.
          </p>
          <Code>{`agentfox report entitlement`}</Code>
        </Step>
      </Steps>

      <Callout kind="note">
        With <code>auto()</code>, an answer that quotes a chunk the caller may not see raises a critical
        Issue, and is refused when the agent blocks. A paraphrase gets past that check, so filter before
        the model as well.
      </Callout>

      <h2>Which sources to trust</h2>
      <p>
        <strong>Settings → Verified sources</strong> records how far each source can be trusted (system of
        record, approved, unverified, external), who owns it and how fresh it must be. Press{" "}
        <strong>+ Add a source</strong> to register one. An answer built on a deprecated or stale source
        raises an Issue.
      </p>
      <Screenshot {...SCREENS.verifiedSources} />
      <p>
        To make the agent say it does not know instead of guessing, see{" "}
        <Link href="/docs/protect/custom-rules#answers">Custom rules</Link>.
      </p>

      <h2>If something goes wrong</h2>
      <table>
        <thead>
          <tr>
            <th>You see</th>
            <th>Do this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Nobody is being checked yet</td>
            <td>People and grants do nothing alone. Your retrieval must call the filter.</td>
          </tr>
          <tr>
            <td>unknown principal</td>
            <td>Add that person first, or add them from your sign-in code.</td>
          </tr>
          <tr>
            <td>A grant has no effect</td>
            <td>The team name must match exactly, and the pattern must match the source each chunk carries.</td>
          </tr>
        </tbody>
      </table>

      <NextSteps
        items={[
          { href: "/docs/reference/api", label: "HTTP API reference", why: "the filter request and response" },
          { href: "/docs/govern", label: "Tool access", why: "what the agent may do, rather than see" },
        ]}
      />
    </article>
  );
}

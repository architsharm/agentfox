import type { Metadata } from "next";
import Link from "next/link";

import { Code, NextSteps, Screenshot, Step, Steps } from "@/components/docs/blocks";
import { Tab, Tabs } from "@/components/docs/tabs";
import { SCREENS } from "@/lib/docs/screens";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Guardrails",
  description:
    "See the rules on your agents, add a library of guardrails, watch what they would have done, then switch them to Block.",
  path: "/docs/protect",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Guardrails</h1>
      <p className="docs-lede">
        Turn on guardrails for your agents, see what they would have stopped, and switch them to Block
        once you trust them.
      </p>

      <Steps topLevel>
        <Step title="See the rules on your agents">
          <p>
            Open <strong>Policies</strong>. <strong>Applied rules</strong> lists each rule, what it does
            (blocks, asks a person, or watches), which agents it applies to, and the library it comes from.
            Pick a project in the sidebar to see only its agents.
          </p>
          <Screenshot {...SCREENS.policies} />
        </Step>

        <Step title="Add a library">
          <p>
            Open the <strong>Libraries</strong> tab. A library is a set of rules you switch on together: the
            basic guardrails, prompt attacks, EU AI Act controls and more. Press{" "}
            <strong>Apply to</strong> your project, or <strong>Apply to every agent</strong>. Every library
            starts by watching.
          </p>
          <Screenshot {...SCREENS.libraries} />
        </Step>

        <Step title="Read what it would have done">
          <p>
            While a rule watches, it records what it would have done and stops nothing. Open a library from
            its card to see its rules and its mode. Open a rule to see its hits, how many calls it{" "}
            <strong>Would have stopped</strong>, and the runs behind them.
          </p>
          <Screenshot {...SCREENS.ruleDetail} />
        </Step>

        <Step title="Switch to Block">
          <Tabs>
            <Tab label="In the app">
              <p>
                Press <strong>Simulate</strong> to replay recent traffic as if the rules blocked, then{" "}
                <strong>Start blocking</strong>. Start blocking stays unavailable until a simulation of
                exactly these rules has run. <strong>Switch to watching</strong> undoes it.
              </p>
            </Tab>
            <Tab label="CLI">
              <Code>{`agentfox policy list
agentfox policy enforce baseline`}</Code>
            </Tab>
          </Tabs>
        </Step>
      </Steps>

      <h2>What is on by default</h2>
      <ul>
        <li>Tool access blocks from the start: a tool the agent was not given is refused.</li>
        <li>
          The basic guardrails stop prompt attacks and hide personal data and secrets in replies. On an
          agent with real traffic they watch first.
        </li>
      </ul>

      <h2>Change a rule for one agent</h2>
      <p>
        Open a rule and press <strong>Change</strong>. Under <strong>Applies to</strong>, choose{" "}
        <strong>Every agent</strong> or <strong>Only some agents</strong>, then the action or the
        sensitivity. AgentFox checks the change against the last 7 days before you press{" "}
        <strong>Apply</strong>. One agent can always be stricter than the workspace; looser only where
        the rule allows it.
      </p>

      <h2 id="tuning">Tuning</h2>
      <p>
        A guardrail blocked a real user? See <Link href="/docs/protect/tuning">Fix false positives</Link>.
      </p>

      <NextSteps
        items={[
          { href: "/docs/protect/custom-rules", label: "Custom rules", why: "your own words, limits and imported policies" },
          { href: "/docs/reference/policies", label: "Policy language", why: "the rule YAML behind every library" },
        ]}
      />
    </article>
  );
}

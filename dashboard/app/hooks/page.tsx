/**
 * /hooks — the coding-agent page.
 *
 * Built on the same template as the other seven product pages. It used to
 * have its own layout, which meant three product pages looked like one
 * product and five looked like another.
 *
 * What it keeps is the thing that is only true here: the capability table.
 * Every competitor page in this category claims enforcement at a hook and
 * none of them says which hook is a gate and which is a bystander, so that
 * table is the page and it goes in the `feature` slot.
 */

import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Agent hooks for coding agents",
  description:
    "Claude Code has three hooks. Two can stop a call. One cannot, and this page says which.",
  path: "/hooks",
});

/** Mirrors `src/agentfox/hooks/capability.py`. That file is the source of truth. */
const EVENTS = [
  {
    event: "UserPromptSubmit",
    sees: "The turn you submitted",
    verdict: "Stops it",
    blocks: true,
    detail: "A refusal returns before the model sees the turn.",
  },
  {
    event: "PreToolUse",
    sees: "The call about to run",
    verdict: "Stops it",
    blocks: true,
    detail: "The command does not run. The hook can also rewrite the call.",
  },
  {
    event: "PostToolUse",
    sees: "What the tool returned",
    verdict: "Cannot stop it",
    blocks: false,
    detail: "The call has already run. The model is told the result is untrusted.",
  },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Agent hooks"
      title={["Which hooks can", "stop a call"]}
      lede="Claude Code has three. Two can stop a call. One cannot."
      docs="/docs/hooks"
      challenge={
        <p>
          A coding agent on a laptop can reach production. It reads comments and logs
          written by strangers, and it holds the developer&rsquo;s credentials.
        </p>
      }
      feature={{
        title: "Three checkpoints, and they are not equal",
        lede: "PostToolUse cannot stop a call. The side effect has already happened.",
        body: (
          <div className="hk-events mk-stagger">
            {EVENTS.map((row) => (
              <div
                key={row.event}
                className={row.blocks ? "hk-event" : "hk-event hk-event-observe"}
              >
                <div className="hk-event-head">
                  <code>{row.event}</code>
                  <span className={row.blocks ? "hk-verdict hk-blocks" : "hk-verdict"}>
                    {row.verdict}
                  </span>
                </div>
                <p className="hk-sees">{row.sees}</p>
                <p className="hk-detail">{row.detail}</p>
              </div>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "A comment inside a fetched issue is not the request",
          body: <p>The fetch was ordinary. PostToolUse is what reads what came back.</p>,
        },
        {
          title: "The check is already running",
          body: <p>Cold, a fresh process costs 3.9 seconds. Against the warm daemon it is about 6ms.</p>,
        },
      ]}
      gaps={{
        title: "What a hook is not",
        body: (
          <p>
            It only sees the agent on this machine. A session that runs in the
            vendor&rsquo;s cloud is invisible. Other harnesses are not claimed here.
          </p>
        ) }}
      related={["/mcp", "/runtime", "/control-points"]}
    />
  );
}

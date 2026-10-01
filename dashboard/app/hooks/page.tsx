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
import { REPO } from "@/components/marketing/nav";
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
    detail:
      "A refusal returns before the turn is sent, so the model never sees it. Most often this catches a pasted stack trace carrying something nobody read.",
    evidence: "Read in the shipped bundle",
    why: "This event fires on your submission, and nothing inside an agent's turn can trigger it. Weaker than a probe, and the row says so.",
  },
  {
    event: "PreToolUse",
    sees: "The call about to run",
    verdict: "Stops it",
    blocks: true,
    detail:
      "The command does not run and the reason reaches the agent verbatim. This event can also rewrite the call — strip the credential, bound the statement — rather than only refuse it.",
    evidence: "Probed against a live session",
    why: "A hook denied one sentinel string and allowed everything else, so the session stayed usable while the deny path was exercised for real.",
  },
  {
    event: "PostToolUse",
    sees: "What the tool returned",
    verdict: "Cannot stop it",
    blocks: false,
    detail:
      "By the time this fires the call has run. What a refusal buys is real and smaller: the model is told, in the same turn, that the result it holds is untrusted before it acts on it.",
    evidence: "Probed against a live session",
    why: "We emitted a block on a shell call and the command's own output came back anyway. The harness calls this blocking; it is not, and we would rather say so.",
  },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Agent hooks"
      title={["Which hooks can", "stop a call"]}
      lede="Claude Code has three. Two can stop a call. One cannot, and this page says which."
      docs="/docs/hooks"
      challenge={
        <p>
          A coding agent on a laptop can reach production. It reads issue comments and
          CI logs written by strangers, and it holds the same credentials the developer
          does.
        </p>
      }
      feature={{
        title: "Three checkpoints, and they are not equal",
        lede: "Two of the three can stop a call. One cannot.",
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
                <p className="hk-evidence">
                  <b>{row.evidence}</b> · Claude Code 2.1.220
                </p>
                <p className="hk-why">{row.why}</p>
              </div>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "The one a tool-call hook cannot see",
          body: (
            <p>
              The agent fetches an issue. The call was ordinary; the comment inside it
              is not. A guard bound only to the request sees nothing, which is why{" "}
              <code>PostToolUse</code> evaluates the result on the{" "}
              <code>tool_result</code> surface.
            </p>
          ),
        },
        {
          title: "The source of the text stays attached to it",
          body: (
            <p>
              An argument later derived from that result cannot exceed the ceiling for
              tool-sourced data, whatever the model decided in between. Catching the
              injection is best; bounding what it can reach is the part that still
              holds when we miss it.
            </p>
          ),
        },
        {
          title: "The check is already running when the hook fires",
          body: (
            <p>
              The harness spawns a fresh process per call. Cold, that costs 3.9 seconds;
              against a warm daemon over a private Unix socket it is about 6ms. A hook
              that costs two seconds a call is a hook the developer removes.
            </p>
          ),
        },
        {
          title: "Turn on the pack built for this job",
          body: (
            <p>
              Not a standard — a job. A coding agent&rsquo;s inputs are diffs, stack
              traces and JSON, so instruction-shaped English in a tool result is far
              more anomalous here than in a support agent&rsquo;s mailbox, and is caught
              at a threshold that would be intolerable there.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What a hook is not",
        body: (
          <p>
            It governs the agent on this machine. Anything not going through this
            harness is not going through this — and a session that runs in the
            vendor&rsquo;s cloud rather than on your laptop is not visible to it at all.
            One harness is probed; the others have no row, which is deliberate. Every
            claim here comes from{" "}
            <a
              href={`${REPO}/blob/main/src/agentfox/hooks/capability.py`}
              target="_blank"
              rel="noreferrer"
            >
              hooks/capability.py
            </a>
            .
          </p>
        ) }}
      related={["/mcp", "/runtime", "/control-points"]}
    />
  );
}

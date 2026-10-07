import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Access control for agent tool calls",
  description:
    "You write down what each agent is allowed to do before it runs. A prompt cannot add to that.",
  path: "/grants",
});

/** Both ladders are ordered least to most dangerous, and both come straight
 *  from the engine — `models.py` for impact, `guardrails/base.py` for taint. */
const IMPACT = [
  { k: "read", what: "Returns something. Changes nothing." },
  { k: "write", what: "Changes state that can be changed back." },
  { k: "high_impact", what: "Wide blast radius, or spawns something with its own tools." },
  { k: "irreversible", what: "Money moved, data deleted, mail sent. No undo." },
] as const;

const TAINT = [
  { k: "none", what: "Constant, from your own code." },
  { k: "user", what: "The operator typed it." },
  { k: "retrieved", what: "It came out of a document." },
  { k: "tool_result", what: "A tool returned it. A third party wrote it." },
  { k: "subagent", what: "Another agent asserted it." },
  { k: "memory", what: "It was written to memory earlier, by something." },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Access control"
      title={["What each agent", "is allowed to do"]}
      lede="You write that down before the agent runs. A prompt cannot add to it."
      docs="/docs/guides/contain-tool-calls"
      challenge={
        <p>A text filter has to guess. This asks whether the agent was allowed to do this.</p>
      }
      feature={{
        title: "What the tool can do, and where the argument came from",
        lede: "How dangerous the tool is, and whether a document supplied the value.",
        body: (
          <div className="ladders mk-stagger">
            <div className="ladder">
              <p className="mk-label">Tool impact</p>
              <ol>
                {IMPACT.map((r) => (
                  <li key={r.k}>
                    <code>{r.k}</code>
                    <span>{r.what}</span>
                  </li>
                ))}
              </ol>
            </div>
            <div className="ladder">
              <p className="mk-label">Argument taint</p>
              <ol>
                {TAINT.map((r) => (
                  <li key={r.k}>
                    <code>{r.k}</code>
                    <span>{r.what}</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        ) }}
      steps={[
        {
          title: "Declare what the tool does",
          body: (
            <p>
              Read, write, high impact, or irreversible. For a shell, <code>ls</code> and{" "}
              <code>rm</code> are the same tool, so the label is only a floor.
            </p>
          ),
        },
        {
          title: "Grant it, with a ceiling",
          body: <p>Anything not granted is refused. A grant can cap the amount, and how untrusted an argument may be.</p>,
        },
        {
          title: "Where the value came from changes the answer",
          body: (
            <p>
              The same transfer is allowed when a person typed the amount, and stopped
              when the amount came out of a document.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What grants do not do",
        body: (
          <p>
            If you declare a destructive tool as read, the check believes you. It also
            cannot see what that tool does on the other side of its own API.
          </p>
        ) }}
      related={["/runtime", "/discovery", "/control-points"]}
    />
  );
}

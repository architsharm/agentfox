import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Runtime guardrails for AI agents",
  description:
    "The tool call is checked, and so are the prompt, the result, the document the agent read, and what it saves to memory.",
  path: "/runtime",
});

/**
 * The nine surfaces, exactly as `guardrails/base.py` names them. `rare` marks
 * the two most products do not have — and they are the two that matter most
 * for an agent, because one is the model deciding and the other is the model
 * claiming it is finished.
 */
const SURFACES: { key: string; what: string; rare?: boolean }[] = [
  { key: "input", what: "What the operator typed or pasted" },
  { key: "output", what: "What the model is about to say" },
  { key: "tool_args", what: "The arguments of a call about to run" },
  { key: "tool_result", what: "What a tool sent back" },
  { key: "retrieved", what: "A document pulled into context" },
  { key: "memory_write", what: "Something being written to long-term memory" },
  { key: "agent_message", what: "A claim from another agent" },
  { key: "reasoning", what: "The model's own thinking, before it acts", rare: true },
  { key: "completion", what: "The claim that it finished", rare: true },
];

export default function Page() {
  return (
    <CapabilityPage
      kicker="Runtime guardrails"
      title={["The tool call", "is checked too"]}
      lede="So are the prompt, the reply, the document the agent read, and what it saves. If a detector runs out of time, that is written down."
      docs="/docs/reference/policies"
      challenge={
        <p>A scanner gives you a score. You still have to decide what to do with it.</p>
      }
      feature={{
        title: "Nine places a check can run",
        lede: "The prompt is one of them.",
        body: (
          <div className="surf-grid mk-stagger">
            {SURFACES.map((s) => (
              <div key={s.key} className={s.rare ? "surf surf-rare" : "surf"}>
                <code>{s.key}</code>
                <p>{s.what}</p>
                {s.rare && <span className="surf-tag">Rare</span>}
              </div>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "The same sentence means something different in each place",
          body: (
            <p>
              Instruction-shaped text in a document is an attempt. The same text in the
              model&rsquo;s own reasoning is further along, so it is caught sooner.
            </p>
          ),
        },
        {
          title: "Detection blocks nothing until you turn it on",
          body: <p>Detector packs ship in observe. They record what they would have done, against real traffic. Tool containment is the exception: it enforces from install, because a missing grant is a fact, not a guess.</p>,
        },
        {
          title: "A check that runs out of time says so",
          body: (
            <p>
              Each detector has 40ms. Over budget, it is marked on that decision rather
              than quietly skipped.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What the detectors do not do",
        body: (
          <p>
            A new phrasing gets through. That is why the grant check sits underneath
            them. On some tasks another scanner is more precise, and{" "}
            <a href="/compare">the comparison</a> names which.
          </p>
        ) }}
      related={["/grants", "/hooks", "/evidence"]}
    />
  );
}

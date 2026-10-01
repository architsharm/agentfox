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
      lede="So are the prompt, the result, the document the agent read, and what it saves to memory. If a detector runs out of time, that is written down."
      docs="/docs/runtime"
      challenge={
        <p>
          A scanner gives you a score. You still have to decide what to do with it:
          which surface it came from, how far to trust the source, what this agent is
          allowed to do, and whether a check was down at the time.
        </p>
      }
      feature={{
        title: "Nine places a check can run",
        lede: "The prompt is one of them. A tool call, a tool result, and a document the agent reads are others.",
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
          title: "The prompt is only one of them",
          body: (
            <p>
              Input, output, tool arguments, tool results, retrieved documents, memory
              writes and messages from other agents — plus two most products do not
              have: the model&rsquo;s own <code>reasoning</code>, and its{" "}
              <code>completion</code> claim that it finished. The same text means
              different things on different surfaces.
            </p>
          ),
        },
        {
          title: "Text from a document is trusted less than text you typed",
          body: (
            <p>
              Injection-shaped text in a retrieved document is an attempt. The same text
              in the model&rsquo;s own reasoning is a compromise in progress, so it is
              caught at a lower confidence. That asymmetry is the argument for having
              surfaces at all.
            </p>
          ),
        },
        {
          title: "Rules you can read, in packs you can choose",
          body: (
            <p>
              50 rules across four packs — a detector baseline, tool containment, an EU
              AI Act pack, and one tuned for coding agents. YAML, in the repository, with
              a lint that catches a rule shadowed by another and a rule whose conditions
              can never all hold.
            </p>
          ),
        },
        {
          title: "Nothing blocks until you say so",
          body: (
            <p>
              Every pack ships in observe. It records the verdict it would have returned
              against real traffic, and you promote it when the counterfactual looks
              right rather than when the documentation says to.
            </p>
          ),
        },
        {
          title: "A check that cannot run says so",
          body: (
            <p>
              350ms for the whole request, 300ms for the pipeline, 40ms for any one
              detector. Over budget, a detector is marked degraded on that decision
              rather than quietly skipped — and four controls, including tenant
              isolation and the audit chain, may not be configured to fail open at all.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What the detectors do not do",
        body: (
          <p>
            They are pattern and classifier based, and a sufficiently novel phrasing gets
            through — which is the entire reason grants exist underneath them and why the
            benchmark is run with every detector switched off. On some individual
            detection tasks a specialised scanner is more precise than ours, and{" "}
            <a href="/compare">/compare</a> names which.
          </p>
        ) }}
      related={["/grants", "/hooks", "/evidence"]}
    />
  );
}

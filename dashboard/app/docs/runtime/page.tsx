import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Runtime",
  description: "See what is in force, watch it in observe, then turn enforcement on.",
  path: "/docs/runtime",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Runtime</h1>
      <p>
        <code>agentfox init</code> loads four packs. <code>baseline</code>,{" "}
        <code>coding-agent</code> and <code>eu-ai-act-high-risk</code> start in observe: they record the verdict they
        would have returned and change nothing. <code>tool-containment</code> starts in
        enforce, because a missing grant and an untrusted argument on an irreversible
        tool are structural facts, not classifier scores.
      </p>

      <h2>What is in force</h2>
      <pre>
        <code>{`agentfox policy list
agentfox policy effective --agent my-agent
agentfox policy lint`}</code>
      </pre>
      <p>
        <code>policy list</code> is the mode of each pack. <code>policy effective</code>{" "}
        is what is in force for one agent, and where each rule came from.{" "}
        <code>policy lint</code> exits 1 on a critical or high finding. The packs are
        YAML. Lint catches a rule hidden by another, and a rule whose conditions can
        never all hold.
      </p>

      <h2>Watch, then enforce</h2>
      <p>
        On a proxied model call, <code>x-nometria-verdict</code> is what happened and{" "}
        <code>x-nometria-effective-verdict</code> is what the policy would have done.
        In observe they differ. When that gap stops being a surprise:
      </p>
      <pre>
        <code>{`agentfox policy enforce baseline
agentfox policy observe baseline`}</code>
      </pre>
      <p>
        <code>policy enforce baseline</code> is the step that starts blocking model
        traffic. <code>policy observe baseline</code> puts it back. Promoting baseline
        adds the detector-driven rules on top of containment, which was already
        enforcing. Replay a candidate against recorded traffic first, on{" "}
        <Link href="/docs/test">Test</Link>.
      </p>

      <h2>One agent, without touching the rest</h2>
      <pre>
        <code>{`agentfox agents quarantine support-triage --reason "investigating"
agentfox agents resume support-triage`}</code>
      </pre>
      <p>Both are reversible, and both are written to the audit chain.</p>

      <h2>The pack for a coding agent</h2>
      <pre>
        <code>agentfox policy observe coding-agent</code>
      </pre>
      <p>
        A coding agent reads diffs, stack traces, and JSON. Instruction-shaped English
        in a tool result is caught at a threshold that would be wrong for a support
        agent. How the hooks themselves bind is on <Link href="/docs/hooks">Coding agents</Link>.
      </p>
    </article>
  );
}

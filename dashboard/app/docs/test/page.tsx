import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Test",
  description: "Score a suite, probe a deployment, and replay traffic against a candidate policy.",
  path: "/docs/test",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Product</p>
      <h1>Test</h1>
      <p>
        Run these before <Link href="/docs/runtime">turning enforcement on</Link>. Each
        one tells you whether this deployment got weaker. None of them is a certificate
        that an attacker cannot get through.
      </p>

      <h2>A regression gate</h2>
      <pre>
        <code>{`agentfox test run support-quality
agentfox test gate support-quality`}</code>
      </pre>
      <p>
        <code>eval run</code> scores a suite. <code>eval gate</code> compares it with
        the recorded baseline and exits 1 on a regression, which is why it belongs in
        CI. Registered scorers include groundedness, safety, and tool trajectory.
      </p>

      <h2>A probe of this deployment</h2>
      <pre>
        <code>agentfox test redteam support-triage</code>
      </pre>
      <p>
        Fires the built-in adversarial suite, mapped to the OWASP LLM Top 10 and MITRE
        ATLAS, at this deployment&apos;s actual grants and policy bindings, then retries
        probes in mutated form. It includes benign controls, so a configuration that
        blocks everything scores badly rather than perfectly. Read the result as a
        posture delta.
      </p>

      <h2>A candidate policy, against traffic you already have</h2>
      <pre>
        <code>{`agentfox policy lint
agentfox policy simulate --file candidate.yaml`}</code>
      </pre>
      <p>
        <code>policy lint</code> exits 1 on a critical or high finding: a rule hidden by
        another, or a rule whose conditions can never all hold.{" "}
        <code>policy simulate</code> replays the traffic already in the database against
        the candidate, so you can see what a rule change would have done before it does
        it.
      </p>
      <p>
        The published numbers, and the cases they do not cover, are on{" "}
        <Link href="/docs/benchmarks">Benchmarks</Link>.
      </p>
    </article>
  );
}

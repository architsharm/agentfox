import type { Metadata } from "next";
import Link from "next/link";

import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Benchmarks",
  description: "The published results, and where each one stops being a defence.",
  path: "/docs/benchmarks",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <p className="docs-kicker">Help</p>
      <h1>Benchmarks</h1>
      <p>
        We do not claim adversarial robustness. An adaptive attacker who can read the
        verdict and retry gets through published defences, including ours. The number
        we lead with is the one that does not depend on catching the text.
      </p>
      <p>
        Both rows below were measured with every detector switched off. Capability
        grants, argument provenance, and declared impact did the work.
      </p>
      <table>
        <thead>
          <tr>
            <th>Evidence</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Containment, detectors disabled</td>
            <td>8 of 8 attacks contained, with zero detector signal. 4 of 4 legitimate calls still allowed.</td>
          </tr>
          <tr>
            <td>AgentDojo, 97 user tasks and 949 attack pairs, ground truth replayed with provenance inferred from the real tool outputs. No model run, detectors disabled</td>
            <td>Session-level taint (the default): 588 of 588 attack pairs contained, but only 24 of 97 benign tasks (24.7% [17.2, 34.2]) ran without escalating to a human. Per-argument taint: 527 of 588 contained, 37 of 97 benign tasks. With provenance taken from the benchmark&apos;s labels, 97 of 97 and 588 of 588: an upper bound, not a measurement.</td>
          </tr>
        </tbody>
      </table>

      <h2>Detection, published because it is the layer we trust least</h2>
      <ul>
        <li>
          Held-out injection recall is 26.7% for the default heuristic detector, at 100%
          precision; the opt-in classifier ensemble (the <code>classifiers</code> extra
          and a weights download) reaches 66.7%. An adaptive attacker that reads the
          verdict and retries gets about 73% of what the default stack catches through
          within 50 attempts.
        </li>
        <li>
          Against a real, independently installed <code>llm-guard</code> on indirect
          injection via tool output, it is more precise than us: 81.8% against our
          66.7%, on the same 20 cases. Of the 10 attacks among them, we catch all 10 and it
          catches 9.
        </li>
        <li>
          On AgentDojo, per-argument taint misses 61 of 702 attacker write calls: short
          identifiers are never matched, and attacker text inside a longer argument is not
          found. Session-level taint misses none and escalates three benign tasks in four.
        </li>
        <li>
          The opt-in classifier ensemble reaches 85.6% and 98.6% recall on two
          independent datasets. It is not the shipped default. On long prompts it
          mostly times out.
        </li>
      </ul>
      <p>
        Treat every detection number as a speed bump that raises attacker cost. The
        product is built so this layer failing is survivable. The same figures, with
        the methodology, are on <Link href="/benchmark">Benchmarks</Link>.
      </p>

      <h2>Where a standard score does not apply</h2>
      <p>
        Not every area has a recall and precision number, and the benchmark index says
        so rather than forcing one. Source authority is a declared registry, not a
        classifier, so labeled hallucination datasets test a different capability.
        Secrets datasets we looked at need a licence or a data agreement we do not
        have. Entitlement on PrivacyLens is a mechanical check of purpose limitation,
        expected by construction, not a classifier stress test. Composed privilege
        escalation is implemented and tested. No labeled dataset exists to score it.
      </p>
      <p>
        Each directory under <code>benchmarks/</code> in the repository has its own
        fetch and run scripts, committed data, and a README. A figure on the site is
        checked against <code>benchmarks/claims.yaml</code> in CI, so it cannot drift
        from the results file it came from.
      </p>
    </article>
  );
}

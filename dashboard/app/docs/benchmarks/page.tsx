import type { Metadata } from "next";
import Link from "next/link";

import { Callout, Code, NextSteps } from "@/components/docs/blocks";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Benchmarks",
  description: "What was measured, what containment costs in legitimate work, and where each result stops.",
  path: "/docs/benchmarks",
});

export default function Page() {
  return (
    <article className="docs-doc">
      <h1>Benchmarks</h1>
      <p className="docs-lede">
        What containment and detection were measured to do, what containment costs in
        escalated legitimate work, and where each number stops applying. Read it before you quote
        a number or choose <code>taint_scope</code>. The method for each result is on{" "}
        <Link href="/benchmark">Benchmark methodology</Link> and in each{" "}
        <code>benchmarks/&lt;name&gt;/README.md</code>.
      </p>
      <Callout kind="warning" title="Read this first">
        AgentFox does not claim adversarial robustness. An attacker who can read the verdict
        and retry gets through published defences, including these detectors. The numbers we
        lead with were measured with every detector switched off, because that is the
        layer that does not depend on recognising the attack.
      </Callout>

      <h2>Containment, with every detector off</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Benchmark</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Containment scenarios (<code>benchmarks/containment</code>)</td>
            <td>8/8 attacks contained with zero detector signal; 4/4 legitimate calls still allowed.</td>
          </tr>
          <tr>
            <td>
              AgentDojo, 97 user tasks and 949 attack pairs, ground truth replayed with
              provenance inferred from the real tool outputs; no model run
            </td>
            <td>
              Session-level taint (the default): 588 of 588 attack pairs contained, but
              only 24 of 97 benign tasks (24.7% [17.2, 34.2]) ran without escalating to a human.
            </td>
          </tr>
        </tbody>
      </table></div>

      <h2 id="utility">What containment costs: AgentDojo utility</h2>
      <p>
        Containment is cheap to make complete and expensive to make useful. When provenance
        has to be inferred, a legitimate call that copies a value out of a tool output looks
        exactly like an attack, and it is escalated to a person. The whole trade, from{" "}
        <code>benchmarks/agentdojo/README.md</code>:
      </p>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Provenance</th>
            <th>Benign tasks run without escalation</th>
            <th>Attack pairs contained</th>
            <th>Attacker write calls contained</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Session-level taint (shipped default)</td>
            <td>24/97 (24.7% [17.2, 34.2])</td>
            <td>588/588</td>
            <td>702/702</td>
          </tr>
          <tr>
            <td>Argument-level taint</td>
            <td>37/97 (38.1% [29.1, 48.1])</td>
            <td>527/588</td>
            <td>641/702</td>
          </tr>
          <tr>
            <td>Argument-level taint, read-only tools exempt</td>
            <td>62/97 (63.9% [54.0, 72.8])</td>
            <td>527/588</td>
            <td>641/702</td>
          </tr>
          <tr>
            <td>Taken from the benchmark&apos;s labels (upper bound)</td>
            <td>97/97</td>
            <td>588/588</td>
            <td>702/702</td>
          </tr>
          <tr>
            <td>None: grants and impact tiers only</td>
            <td>97/97</td>
            <td>0/588</td>
            <td>61/702</td>
          </tr>
        </tbody>
      </table></div>
      <ul>
        <li>
          <b>Session-level taint is complete and expensive.</b> Once the agent reads any tool
          output, every later irreversible call counts as untrusted. It escalates three
          benign tasks in four.
        </li>
        <li>
          <b>Argument-level taint misses 61 of 702 attacker write calls</b>: identifiers
          shorter than six characters are never matched, and attacker text inside a longer
          argument is not found.
        </li>
        <li>
          <b>Most of the remaining cost is not fixable by provenance alone.</b> With read-only
          tools exempt, 43 of 73 legitimate write and irreversible calls (59%) are still
          escalated, and every one copies a value out of a tool output: paying a bill to an
          account number read from the bill. A user/tool-output label cannot tell those from
          an attack. <a href="/docs/concepts#output-trust">Declaring a tool&apos;s output trusted</a>{" "}
          is the lever you have.
        </li>
        <li>
          <b>Labels are an upper bound.</b> 97/97 with 588/588 needs provenance someone
          labelled correctly, which a deployment does not get for free.
        </li>
        <li>
          It is not AgentDojo&apos;s &quot;utility under attack&quot; metric, which needs a live
          model. No model was run.
        </li>
      </ul>
      <p>
        The setting that picks the row is <code>taint_scope</code> (
        <Link href="/docs/concepts#taint-scope">Concepts</Link>).
      </p>

      <h2>Detection, the layer we trust least</h2>
      <div className="docs-table" tabIndex={0}><table>
        <thead>
          <tr>
            <th>Benchmark</th>
            <th>Result</th>
            <th>Where it stops</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Adaptive attacker vs. the default detectors</td>
            <td>73% attack success at 50 attempts on the attacks they catch</td>
            <td>37/37 of those bypasses were still contained at the action.</td>
          </tr>
          <tr>
            <td>Adaptive red team vs. the capability and taint layer</td>
            <td>
              <code>provenance</code> 0/30, <code>tool_scope</code> 0/29, <code>structural</code>{" "}
              0/105 escapes
            </td>
            <td>
              <code>structural</code> is after a nested-argument fix this benchmark found. A
              posture delta, not a pass rate.
            </td>
          </tr>
          <tr>
            <td>Opt-in classifier ensemble, SPML</td>
            <td>85.6% recall</td>
            <td>
              Needs the <code>classifiers</code> extra and weights; not the shipped default,
              and on long prompts it mostly times out.
            </td>
          </tr>
          <tr>
            <td>Crescendo (multi-turn)</td>
            <td>10/13 detected; control false positives 0/9</td>
            <td>Small set; the signal is the trajectory, not any single turn.</td>
          </tr>
          <tr>
            <td>Cross-lingual parity</td>
            <td>19/19 matched pairs reach the same verdict</td>
            <td>Benign non-English text is still flagged more often.</td>
          </tr>
        </tbody>
      </table></div>

      <h2>Judgment tiers, opt-in</h2>
      <p>
        Judgment tiers add a model to the decisions where measurement says a model wins, and
        are forbidden from the ones where it loses. They are off by default and need{" "}
        <code>allow_egress</code> for the hosted ones (<Link href="/docs/reference/config#judgment">Configuration</Link>).
      </p>
      <ul>
        <li>
          160/165 of the injection payloads that defeated our own pattern detectors are caught
          once a tier is on, at the cost of a network round trip per guarded call.
        </li>
        <li>
          The deterministic answerability check abstains on 57/676 contested questions; with
          a judgment tier that becomes 572/676, with more over-refusal on answerable ones.
        </li>
        <li>SQL blast-radius analysis is unchanged with every tier on, because no model may decide it.</li>
      </ul>

      <h2>Where a standard score does not apply</h2>
      <p>
        Source authority is a declared registry, not a classifier, so labelled hallucination
        datasets test something else. Entitlement on PrivacyLens is a mechanical check of
        purpose limitation, expected by construction. Composed privilege escalation is
        implemented and tested, but no labelled dataset exists to score it. The benchmark
        index says so rather than forcing a number.
      </p>

      <h2>Check the numbers yourself</h2>
      <p>
        Headline numbers are bound to their result files in <code>benchmarks/claims.yaml</code>.
        From a clone of the repository, this lists each one with its current value; with{" "}
        <code>--check</code>, as CI runs it, it fails if a page quotes a number that drifted.
      </p>
      <Code>{`python scripts/check/claims.py --check`}</Code>

      <NextSteps
        items={[
          { href: "/docs/limits", label: "Limits", why: "what is not built, and what only declarations can fix" },
          { href: "/docs/concepts#provenance", label: "Provenance", why: "the setting behind the utility table" },
          { href: "/benchmark", label: "Benchmark methodology", why: "every result with its method" },
        ]}
      />
    </article>
  );
}

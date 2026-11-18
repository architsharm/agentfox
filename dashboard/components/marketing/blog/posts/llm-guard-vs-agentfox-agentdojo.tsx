import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import {
  Diagram,
  Figure,
  InlineCTA,
  Stat,
  StatRow,
  Takeaways,
  type FaqItem,
} from "@/components/marketing/blog/blocks";

export const toc: TocItem[] = [
  { id: "what-we-ran", label: "What we ran" },
  { id: "the-numbers", label: "The four arms" },
  { id: "where-it-beats-us", label: "Where llm-guard beats us" },
  { id: "tuning", label: "Why tuning does not close the gap" },
  { id: "false-positives", label: "What the catching costs" },
  { id: "latency", label: "Latency" },
  { id: "which-one", label: "Which one you want" },
];

export const faq: FaqItem[] = [
  {
    q: "Is AgentFox an alternative to LLM Guard?",
    a: "They do different jobs. LLM Guard reads text and scores how likely it is to be an injection. AgentFox containment decides whether a tool call is allowed given what the agent was granted and where its arguments came from. You can run both, and on AgentDojo running both stops every attack but finishes the fewest benign tasks of any arm we measured.",
  },
  {
    q: "Does LLM Guard stop prompt injection?",
    a: "Partly. On AgentDojo's 588 injection pairs, llm-guard at its default threshold let 86 through. Lowering the threshold catches more attacks and flags more clean text, and no threshold we swept both kept false positives under 5% and closed the gap.",
  },
  {
    q: "Which completes more legitimate tasks?",
    a: "LLM Guard. At its defaults it finished 42 of AgentDojo's 97 benign tasks against AgentFox containment's 24. Containment is stricter because it escalates to a human rather than guessing, and that is a real cost we publish next to the win.",
  },
  {
    q: "Why does a detector miss attacks a permission check catches?",
    a: "A detector has to recognise the attack in the text. A containment check never reads the payload: it compares the tool being called and the provenance of its arguments against what that agent was granted. An attack phrased in a way no classifier has seen still has to call a tool it was never allowed to call.",
  },
  {
    q: "Can I reproduce these numbers?",
    a: "Yes. The runner and the result file are in benchmarks/head_to_head/ in the repository, and every figure on this page is bound to that result file, so a rerun that moves a number fails our CI before it reaches the site.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "On the same 588 AgentDojo injection pairs, llm-guard at its defaults let 86 through. Containment let none through, and never read the payload text.",
          "llm-guard finishes nearly twice as many legitimate tasks as we do. That is the trade, and we would rather print it than bury it.",
          "No llm-guard threshold we swept both held false positives under 5% and closed the attack gap. The failure is not a tuning problem.",
        ]}
      />

      <p>
        Most guardrail comparisons are a feature table written by whoever is selling one of
        the products. This one is a benchmark run, on one machine, with the result file
        checked into the repository. It is also a comparison we lose part of, so it seems
        worth being clear about that up front.
      </p>

      <h2 id="what-we-ran">What we ran</h2>
      <p>
        <a href="https://github.com/protectai/llm-guard" rel="noopener">llm-guard</a> is the
        most widely used open source prompt-injection scanner. It takes text and returns a
        score. <Link href="/docs/concepts">AgentFox containment</Link> is a different kind of
        control: it decides whether a tool call may proceed, from the grant the agent holds
        and the provenance of each argument. It never looks at the payload.
      </p>
      <p>
        <a href="https://github.com/ethz-spylab/agentdojo" rel="noopener">AgentDojo</a> gives
        both of them the same work: 588 attack pairs, where an injected instruction arrives
        inside a tool result, and 97 benign tasks the agent is supposed to finish. An arm is
        scored on both. Stopping every attack by refusing everything is easy and useless, so
        the benign column is the one that keeps the attack column honest.
      </p>

      <h2 id="the-numbers">The four arms</h2>
      <p>
        Four configurations, same harness, same traces. Attacks through is lower-is-better.
        Benign tasks finished is higher-is-better.
      </p>

      <Diagram
        label="Attacks through and benign tasks finished, by arm"
        caption="Each pair of bars is one arm. The left bar is attacks that got through out of 588, the right is benign tasks finished out of 97. Nothing here is a tie."
      >
        <svg className="dg" viewBox="0 0 760 300" xmlns="http://www.w3.org/2000/svg">
          <line x1="150" y1="250" x2="740" y2="250" className="dg-line" />
          {[
            { y: 40, name: "llm-guard", atk: 86, ben: 42 },
            { y: 92, name: "containment", atk: 0, ben: 24 },
            { y: 144, name: "both", atk: 0, ben: 11 },
            { y: 196, name: "llm-guard tuned", atk: 389, ben: 82 },
          ].map((row) => (
            <g key={row.name}>
              <text x="140" y={row.y + 14} textAnchor="end" className="dg-strong">
                {row.name}
              </text>
              <rect
                x="150"
                y={row.y}
                width={Math.max(2, (row.atk / 588) * 280)}
                height="16"
                className="dg-fill-stop"
              />
              <text x={150 + Math.max(2, (row.atk / 588) * 280) + 8} y={row.y + 13} className="dg-small">
                {row.atk} through
              </text>
              <rect
                x="450"
                y={row.y}
                width={Math.max(2, (row.ben / 97) * 280)}
                height="16"
                className="dg-fill-good"
              />
              <text x={450 + Math.max(2, (row.ben / 97) * 280) + 8} y={row.y + 13} className="dg-small">
                {row.ben} done
              </text>
            </g>
          ))}
          <text x="150" y="275" className="dg-small">
            attacks through, of 588
          </text>
          <text x="450" y="275" className="dg-small">
            benign tasks finished, of 97
          </text>
        </svg>
      </Diagram>

      <p>
        At its default threshold, llm-guard alone let 86 of 588 attack pairs through, and it
        finished 42 of 97 benign tasks. With detectors switched off entirely, AgentFox
        containment let 0 of 588 through, and finished 24 of 97 benign tasks. Run both and
        no attack survives either, but the pair finishes 11 of 97, which is the worst benign
        score on the board.
      </p>

      <StatRow>
        <Stat
          value="86"
          label="attacks through llm-guard at its default, of 588"
          source="benchmarks/head_to_head"
        />
        <Stat value="0" label="attacks through containment, of 588" source="benchmarks/head_to_head" />
        <Stat value="42 vs 24" label="benign tasks finished, llm-guard against containment" source="benchmarks/head_to_head" />
      </StatRow>

      <h2 id="where-it-beats-us">Where llm-guard beats us</h2>
      <p>
        It gets more work done. Forty-two finished tasks against twenty-four is not a rounding
        difference, and if your agent does something low-stakes where a blocked call costs more
        than a leaked row, that difference is the whole decision.
      </p>
      <p>
        The reason is in how the two controls fail. A detector that is unsure lets the text
        past, because its job ends at a score. Containment that is unsure escalates to a
        person, because its job ends at an action that cannot be taken back. We chose the
        second behaviour deliberately, and the benign column is what it costs. We publish
        that column on the <Link href="/benchmark">benchmark page</Link> next to the attack
        column, in the same table, at the same size.
      </p>

      <Figure
        src="/blog/benchmark-containment.png"
        alt="The AgentFox benchmark page showing containment results, with the benign task column beside the attack column."
        width={1600}
        height={900}
        caption="The benchmark page. The losses are in the same table as the wins, which is the only arrangement we trust ourselves with."
      />

      <h2 id="tuning">Why tuning does not close the gap</h2>
      <p>
        The obvious reply is that we ran llm-guard at its defaults and defaults are nobody&apos;s
        production config. So we swept the threshold.
      </p>
      <p>
        Hold its false positive rate on clean text at 5% or below, which is roughly the most a
        team will tolerate before they turn the thing off, and it still lets 389 of 588
        through. Push the threshold the other way until it stops every attack, and it only gets
        there once the text is chunked and tuned on the test set, at which point it flags 130
        of 339 clean outputs. That is more than a third of normal traffic interrupted.
      </p>
      <p>
        This is the shape of every detector result we have run, and it is not a criticism of
        llm-guard specifically. A classifier trades recall against precision along one dial.
        Somewhere on that dial is a setting you can ship, and that setting lets attacks
        through, because the attacks that matter are the ones phrased to look ordinary. We
        wrote about the general case in{" "}
        <Link href="/blog/prompt-injection-containment-not-detection">
          why detection is a speed bump
        </Link>
        .
      </p>

      <h2 id="false-positives">What the catching costs</h2>
      <p>
        The number that gets left out of detector comparisons is what the detector does to
        traffic that was fine. At its default threshold llm-guard flagged 82 of 339 clean tool
        outputs. Roughly one in four normal results is treated as an attack.
      </p>
      <p>
        Nobody runs that for long. They raise the threshold, the false positives fall, and the
        attacks that were already slipping through slip through more easily. The dial does not
        have a setting that makes both columns good, which is the point of showing the sweep
        rather than one row from it.
      </p>

      <h2 id="latency">Latency</h2>
      <p>
        A detector runs a model. A containment check runs a comparison. On the same traces,
        llm-guard added 71.9 ms at the median against our 6.9 ms, and its tail is longer
        still. If you are checking every tool call in an interactive session, that difference
        is the one your users feel. There is a fuller breakdown in{" "}
        <Link href="/blog/ai-agent-guardrail-latency">the latency study</Link>.
      </p>

      <h2 id="which-one">Which one you want</h2>
      <p>
        If your agent only reads and summarises, a detector is a reasonable and cheap control,
        and llm-guard is a good one. Nothing it can get wrong is permanent.
      </p>
      <p>
        If your agent sends, writes, pays, deletes or deploys, the question stops being whether
        the text looked suspicious. It becomes whether this agent was ever entitled to make
        this call with these arguments. That question has an answer that does not depend on
        recognising the attack, which is why we build the second control and measure it
        against the first in public.
      </p>
      <p>
        Running both is defensible if you can live with the benign column. We would rather you
        picked that knowingly than discovered it in week three.
      </p>

      <InlineCTA
        title="Run the comparison yourself"
        body="The harness, the traces and the result file are in the repository. Clone it and rerun both arms on your own machine."
        href="/benchmark"
        label="See the benchmark"
        secondary={{ href: "/playground", label: "Try the playground" }}
      />
    </>
  );
}

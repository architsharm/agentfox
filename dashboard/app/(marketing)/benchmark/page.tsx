import type { Metadata } from "next";
import Link from "next/link";

import { BarCard, Contents, DocSection, Limits, PaperCard, Rerun, Source, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata } from "@/lib/site";

export const dynamic = "force-dynamic";

export const metadata: Metadata = publicPageMetadata({
  title: "Security benchmarks",
  description:
    "AgentFox against LLM Guard and Prompt Guard 2 on AgentDojo, held-out injections and harmless look-alikes, with every detector switched off, and against an attacker who adapts. Results, losses and scripts.",
  path: "/benchmark",
});

/*
 * Every number on this page is copied from a results file in benchmarks/, and the
 * file is named under each table.
 */

const SECTIONS = [
  { id: "agentdojo", label: "Attacks on a tool-using agent" },
  { id: "detectors-off", label: "With every detector switched off" },
  { id: "cost", label: "What containment costs" },
  { id: "detection", label: "Detection accuracy" },
  { id: "agent-attacks", label: "Attacks a text scanner can't see" },
  { id: "adaptive", label: "An attacker who adapts" },
  { id: "rerun", label: "Rerun it yourself" },
];

export default function Benchmark() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main>
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <span className="lp-pill">Security benchmarks</span>
            <h1>
              Measured against
              <br />
              <span className="lp-muted">the guardrails you use today</span>
            </h1>
            <p className="lp-lead">
              Public datasets, each tool at its own default. Every number links to the script and the results file behind it,
              including the ones we lose.
            </p>
          </div>
        </section>

        <section className="lp-section lp-section-tight">
          <div className="lp-wrap">
            <div className="lp-pairs lp-pairs-wide" data-reveal>
              <BarCard
                title="Attacks that got through"
                hint="AgentDojo, 588 attacks · lower is better"
                max={588}
                rows={[
                  { name: "No guardrail", value: 588, label: "588" },
                  { name: "LLM Guard", value: 86, label: "86" },
                  { name: "AgentFox", value: 0, label: "0", ours: true },
                ]}
              />
              <BarCard
                title="Real attacks caught"
                hint="held-out injections · higher is better"
                rows={[
                  { name: "LLM Guard's model", value: 31.7, label: "31.7%" },
                  { name: "Prompt Guard 2", value: 20.0, label: "20.0%" },
                  { name: "AgentFox", value: 68.3, label: "68.3%", ours: true },
                ]}
              />
              <BarCard
                title="Harmless messages blocked"
                hint="339 look-alikes · lower is better"
                rows={[
                  { name: "LLM Guard's model", value: 42.2, label: "42.2%" },
                  { name: "AgentFox", value: 11.5, label: "11.5%", ours: true },
                  { name: "Prompt Guard 2", value: 3.5, label: "3.5%" },
                ]}
                note="Prompt Guard 2 blocks fewer harmless messages and catches far fewer attacks."
              />
              <BarCard
                title="Normal tasks done without a person"
                hint="AgentDojo, 97 tasks · higher is better"
                max={97}
                loss
                rows={[
                  { name: "LLM Guard", value: 42, label: "42" },
                  { name: "AgentFox", value: 24, label: "24", ours: true },
                ]}
                note="AgentFox sends the rest to a person to approve. Section 3 shows how to get to 62."
              />
            </div>
            <p className="lp-note">Prompt Guard 2 is the 86M model. Every model at its published threshold.</p>
            <Contents items={SECTIONS} />
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection
            id="agentdojo"
            n={1}
            title="Attacks on a tool-using agent"
            lead={
              <>
                <a href="https://github.com/ethz-spylab/agentdojo">AgentDojo</a> (ETH Zurich) is the standard benchmark for
                prompt injection against agents that call tools. We replayed its 97 user tasks, and its 588 attacks that try to
                make the agent write, send or pay something it shouldn&apos;t.
              </>
            }
          >
            <Table
              head={["Defence", "Attacks that got through", "Normal tasks done without a person", "Harmless tool outputs flagged"]}
              rows={[
                { cells: ["No defence", "588 / 588", "97 / 97", "–"] },
                { cells: ["LLM Guard, default", "86 / 588 (14.6%)", "42 / 97", "82 / 339 (24.2%)"] },
                { cells: ["AgentFox, default", "0 / 588", "24 / 97", "0 / 339"], ours: true },
                { cells: ["AgentFox, detectors off", "0 / 588", "24 / 97", "–"], ours: true },
                { cells: ["LLM Guard and AgentFox together", "0 / 588", "11 / 97", "82 / 339"] },
              ]}
              source={{ label: "benchmarks/head_to_head", path: "benchmarks/head_to_head/README.md" }}
            />
            <p>
              LLM Guard reads each tool output and decides whether it holds an injection. Most of its 86 misses are attacks past
              the first 512 tokens of an output, which is all its model reads. AgentFox doesn&apos;t have to spot the injection.
              It tracks where each argument of a tool call came from, and a payment or email whose details came from a tool
              output goes to a person first.
            </p>
            <p>
              LLM Guard can close the gap. In its long-input mode, with a threshold picked on this test set, it stops all 588 at
              the same 24 tasks, but flags 38% of harmless tool outputs on the way.
            </p>
            <Limits
              items={[
                "No model was run. The agent's calls are AgentDojo's own answer key, so this measures the guardrail, not how easily a model is fooled.",
                "Sending a call to a person counts as stopping it. If the reviewer approves an attacker's call, it goes through.",
                "Prompt Guard 2 isn't in this AgentDojo replay. It is measured in the detector comparison below.",
              ]}
            />
          </DocSection>

          <DocSection
            id="detectors-off"
            n={2}
            title="With every detector switched off"
            lead="Once attackers can adapt, published defences fail more than 90% of the time (Nasr, Carlini et al., 2025). So we tested what happens after the detectors have already lost: eight attacks, one for each way AgentFox stops a call, with detection disabled."
          >
            <div className="lp-stats" data-reveal>
              <div className="lp-stat">
                <span className="lp-stat-n">8 of 8</span>
                <span className="lp-stat-l">attacks stopped with detectors off</span>
                <span className="lp-stat-vs">The same as with detectors on</span>
              </div>
              <div className="lp-stat">
                <span className="lp-stat-n">4 of 4</span>
                <span className="lp-stat-l">legitimate calls still allowed</span>
                <span className="lp-stat-vs">A refund, a search, a ticket update, a lookup</span>
              </div>
              <div className="lp-stat">
                <span className="lp-stat-n">0</span>
                <span className="lp-stat-l">detector signals raised</span>
                <span className="lp-stat-vs">Down from 10 with detectors on</span>
              </div>
            </div>
            <Table
              head={["Attack", "Result", "Stopped by"]}
              rows={[
                ["Send data out through a tool the agent was never given", "block", "capability.denied"],
                ["Transfer money to an account taken from attacker text", "escalate", "taint.irreversible_tool"],
                ["Transfer above the declared limit", "block", "capability constraint"],
                ["Refund above the declared limit", "block", "capability constraint"],
                ["Unbounded DELETE inside a tool argument", "block", "sql.unbounded_mutation"],
                ["SQL injection in an ordinary lookup", "block", "scope.sql_fragment_in_value"],
                ["Output of a read tool reused in an irreversible call", "escalate", "taint.irreversible_tool"],
                ["Allowed call while the agent is quarantined", "block", "agent.quarantined"],
              ].map((c) => ({ cells: [c[0], c[1], <code key="r">{c[2]}</code>] }))}
              source={{ label: "benchmarks/containment", path: "benchmarks/containment/README.md" }}
            />
            <Limits
              items={[
                "Containment is only as good as what you declare. A tool that sends money but is declared read-only is invisible to it.",
                "Eight scenarios is a small set: one per mechanism, chosen to differ from each other.",
              ]}
            />
          </DocSection>

          <DocSection
            id="cost"
            n={3}
            title="What containment costs"
            lead="Stopping every attack has a price. By default, three in four normal AgentDojo tasks needed a person to approve a step. That is a setting, and these are the trade-offs on the same replay."
          >
            <div className="lp-pairs lp-pairs-wide" data-reveal>
              <BarCard
                title="Attacks stopped"
                hint="of 588 · higher is better"
                max={588}
                rows={[
                  { name: "Session taint (default)", value: 588, label: "588", ours: true },
                  { name: "Argument taint", value: 527, label: "527" },
                  { name: "Grants only", value: 0, label: "0" },
                ]}
              />
              <BarCard
                title="Normal tasks without a person"
                hint="of 97 · higher is better"
                max={97}
                rows={[
                  { name: "Session taint (default)", value: 24, label: "24", ours: true },
                  { name: "Argument taint, reads exempt", value: 62, label: "62" },
                  { name: "Grants only", value: 97, label: "97" },
                ]}
              />
            </div>
            <Table
              head={["Setting", "Normal tasks without a person", "Attacks stopped"]}
              rows={[
                { cells: ["Session-level taint (default)", "24 / 97", "588 / 588"], ours: true },
                { cells: ["Argument-level taint", "37 / 97", "527 / 588"] },
                { cells: ["Session-level, read-only tools exempt", "43 / 97", "588 / 588"] },
                { cells: ["Argument-level, read-only tools exempt", "62 / 97", "527 / 588"] },
                { cells: ["Perfect labels (upper bound)", "97 / 97", "588 / 588"] },
                { cells: ["Grants and impact tiers only", "97 / 97", "0 / 588"] },
              ]}
              source={{ label: "benchmarks/agentdojo", path: "benchmarks/agentdojo/README.md" }}
            />
            <p>
              Session-level taint treats everything after the agent reads a tool output as untrusted. It stops every attack, and
              most legitimate payments and messages with them. Argument-level taint checks each argument. It lets more work
              through and misses 61 attacks: short values like a file id of &quot;13&quot;, and attacker text buried inside a
              longer argument.
            </p>
            <p>
              Most of what&apos;s left can&apos;t be fixed by provenance alone. Paying a bill means copying an IBAN out of a
              document, which is exactly what an attack that redirects a payment does.
            </p>
            <Limits
              items={[
                "The read-only exemption was designed after seeing the other rows.",
                "This checks whether legitimate work could run without a person, not whether the agent did it well.",
              ]}
            />
          </DocSection>

          <DocSection
            id="detection"
            n={4}
            title="Detection accuracy"
            lead="The detectors are the second layer. These are their numbers on held-out data that nothing was tuned on."
          >
            <Table
              head={["Model", "Held-out attacks caught", "SPML", "Multilingual", "Harmless look-alikes flagged"]}
              rows={[
                { cells: ["AgentFox default (PIGuard and patterns)", "68.3%", "29.6%", "76.0%", "11.5%"], ours: true },
                { cells: ["LLM Guard's model (ProtectAI DeBERTa v2)", "31.7%", "–", "–", "42.2%"] },
                { cells: ["Prompt Guard 2, 86M", "20.0%", "38.4%", "44.7%", "3.5%"] },
                { cells: ["Prompt Guard 2, 22M", "16.7%", "11.2%", "7.4%", "0%"] },
                { cells: ["AgentFox patterns only, no model", "16.7%", "9.6%", "0.9%", "0%"] },
              ]}
              source={{ label: "benchmarks/injection/model_choice", path: "benchmarks/injection/model_choice/results/summary.json" }}
            />
            <p>
              Held-out attacks are 116 examples from deepset/prompt-injections, scored with no false alarms on that split.
              Harmless look-alikes are NotInject&apos;s 339 prompts, written to use the same words attacks do. Prompt Guard 2 86M
              does better on SPML and flags less harmless text. PIGuard catches the most, so it stays the default.
            </p>
            <p>
              A second model can run beside PIGuard. With it on, 41% of the look-alikes are flagged, so its hits are recorded
              and never block: an enforcing rule acts on PIGuard alone.
            </p>
            <PaperCard />
            <Limits
              items={[
                "Without the model weights (installed without the classifiers extra) AgentFox runs the patterns alone, at 16.7%. The Docker image ships the weights.",
                "An earlier version of the patterns was fitted to the held-out misses and scored 26.7%. Those patterns were removed and the benchmark rerun.",
              ]}
            />
          </DocSection>

          <DocSection
            id="agent-attacks"
            n={5}
            title="Attacks a text scanner can't see"
            lead="A prompt-injection scanner checks one string at a time. These attacks only show up across messages, inside tool arguments, or in what the agent is allowed to do. LLM Guard was installed and called for real."
          >
            <div className="lp-compare lp-compare-text lp-compare-wide" data-reveal>
              <div className="lp-compare-head">
                <span>Attack</span>
                <span>LLM Guard</span>
                <span>AgentFox</span>
              </div>
              {[
                ["One attack split across 3 messages", "Flagged all 3 fragments on their own", "Caught the assembled attack only"],
                ["Attacks hidden in tool output (10 attacks, 10 harmless)", "9 of 10 caught, 81.8% precision", "10 of 10 caught, 66.7% precision"],
                ["Attacks in tool arguments (5 attacks, 5 harmless)", "Can't check structured arguments", "5 of 5 blocked"],
                ["Agent going beyond its permissions (6 scenarios)", "No permission model", "5 of 6 correct"],
              ].map((r) => (
                <div key={r[0]} className="lp-compare-row">
                  <span className="lp-compare-msg">{r[0]}</span>
                  <span className="lp-compare-them">{r[1]}</span>
                  <span className="lp-compare-us">{r[2]}</span>
                </div>
              ))}
            </div>
            <Source label="benchmarks/agent_security" path="benchmarks/agent_security/README.md" />
            <p>
              LLM Guard is more precise on attacks hidden in tool output, with 2 false alarms on the harmless half against our 5.
              The permission scenario AgentFox got wrong was an ordinary ticket update held for approval, because the demo
              declares that updating a ticket sends an email.
            </p>
            <Limits items={["The multi-message check runs in the SDK only, not yet in the gateway."]} />
          </DocSection>

          <DocSection
            id="adaptive"
            n={6}
            title="An attacker who adapts"
            lead="Here the attacker sees our verdict and rewrites the attack, up to 50 times. It starts only from attacks our detectors already stop, so every success is a real bypass."
          >
            <AsrChart />
            <p>
              With rewrites a model could still read (paraphrases, other languages, no encoding), three in four attacks got past
              the detectors within 50 tries. With encodings allowed, all of them did within 25. Detectors alone don&apos;t hold,
              which is why the next check happens at the tool call.
            </p>
            <div className="lp-stats" data-reveal>
              <div className="lp-stat">
                <span className="lp-stat-n">37 of 37</span>
                <span className="lp-stat-l">bypasses still stopped at the tool call</span>
                <span className="lp-stat-vs">Each successful payload carried into the action it asked for</span>
              </div>
              <div className="lp-stat">
                <span className="lp-stat-n">17</span>
                <span className="lp-stat-l">tried to send data out by email</span>
                <span className="lp-stat-vs">Blocked: the tool wasn&apos;t granted</span>
              </div>
              <div className="lp-stat">
                <span className="lp-stat-n">12</span>
                <span className="lp-stat-l">tried to move money</span>
                <span className="lp-stat-vs">Sent to a person for approval</span>
              </div>
            </div>
            <Source label="benchmarks/adaptive" path="benchmarks/adaptive/README.md" />
            <Limits
              items={[
                "Search-based attacks only. Gradient-based attacks and human red-teamers are stronger, so read this as a lower bound.",
                "It measured the pattern-only stack, the default until October 2026. The classifier now in the default hasn't been re-measured.",
                "A bypass means the detector allowed the text, not that a model would obey it. No model was in the loop.",
              ]}
            />
          </DocSection>

          <DocSection
            id="rerun"
            n={7}
            title="Rerun it yourself"
            lead="Each benchmark is one script with its own throwaway database, and it writes the results file quoted here. A number that doesn't match is a bug."
          >
            <Rerun
              commands={[
                "uv run python -m benchmarks.containment.run_containment_benchmark",
                "uv run python -m benchmarks.head_to_head.run_agentdojo_h2h",
                "uv run python -m benchmarks.agent_security.tier_b_indirect_injection",
                "uv run python -m benchmarks.injection.run_prompt_injection_benchmark",
                "uv run python -m benchmarks.adaptive.run_adaptive_benchmark",
              ]}
            />
            <p>
              The LLM Guard comparisons need <code>LLM_GUARD_VENV_PYTHON</code> pointing at a separate environment, because LLM
              Guard pins an older transformers. None of these runs needs a model API key. Each figure is a single run, and the run
              dates, hardware and LLM Guard version weren&apos;t recorded.
            </p>
            <p className="lp-doc-more">
              <Link href="/benchmark/latency">
                Latency: what a check adds to your agent <Arrow />
              </Link>
              <Link href="/docs/limits">
                What AgentFox doesn&apos;t catch yet <Arrow />
              </Link>
            </p>
          </DocSection>
        </div>

        <LpCta />
      </main>
      <LpFooter />
    </div>
  );
}

/** Attack success by attempts allowed, readable rewrites only (benchmarks/adaptive). */
function AsrChart() {
  const xs = [1, 5, 10, 25, 50];
  const series = [
    { name: "In the user message", v: [0, 50.0, 76.1, 82.6, 82.6], cls: "a" },
    { name: "In retrieved content", v: [0, 34.0, 48.9, 72.3, 74.5], cls: "b" },
  ];
  const W = 680;
  const H = 280;
  const L = 48;
  const R = 72;
  const T = 16;
  const B = 40;
  const x = (i: number) => L + (i / (xs.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / 100) * (H - T - B);
  return (
    <figure className="lp-chart" data-reveal>
      <figcaption>Attacks that got past the detectors, by attempts allowed</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Attack success reaches 82.6% in the user message and 74.5% in retrieved content by 50 attempts">
        {[0, 25, 50, 75, 100].map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} className="lp-chart-grid" />
            <text x={L - 10} y={y(g) + 4} textAnchor="end" className="lp-chart-axis">
              {g}%
            </text>
          </g>
        ))}
        {xs.map((t, i) => (
          <text key={t} x={x(i)} y={H - 14} textAnchor="middle" className="lp-chart-axis">
            {t}
          </text>
        ))}
        {series.map((s) => (
          <g key={s.name} className={`lp-chart-s lp-chart-${s.cls}`}>
            <polyline points={s.v.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
            {s.v.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r={3.5} />
            ))}
            <text x={x(xs.length - 1) + 10} y={y(s.v[s.v.length - 1]) + 4} className="lp-chart-end">
              {s.v[s.v.length - 1]}%
            </text>
          </g>
        ))}
      </svg>
      <div className="lp-chart-legend">
        {series.map((s) => (
          <span key={s.name} className={`lp-chart-${s.cls}`}>
            <i />
            {s.name}
          </span>
        ))}
        <span className="lp-chart-x">Attempts allowed, readable rewrites only</span>
      </div>
    </figure>
  );
}

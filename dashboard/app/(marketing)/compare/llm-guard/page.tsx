import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Limits, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "LLM Guard vs AgentFox",
  description:
    "LLM Guard and AgentFox on the same 588 AgentDojo attacks, the same held-out injections and the same latency run. It finishes more tasks than we do; we let fewer attacks through.",
  path: "/compare/llm-guard",
});

/** Numbers from /benchmark and /benchmark/latency only. */
export default function LlmGuardPage() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              LLM Guard vs AgentFox
              <br />
              <span className="lp-muted">measured, not described</span>
            </h1>
            <p className="lp-lead">
              Both ran on the same AgentDojo replay, the same held-out injections and the same machine. LLM Guard
              finishes more normal tasks than we do. We stop more attacks, including with our detectors off. LLM
              Guard&apos;s repository was archived in July 2026, after Protect AI&apos;s acquisition; the numbers stand,
              the project does not move.
            </p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="shape" title="Two different shapes" lead="This is the difference every number below comes from.">
            <Table
              head={["", "LLM Guard", "AgentFox"]}
              rows={[
                { cells: ["Made by", "Protect AI", "Nometria"] },
                { cells: ["Licence", "MIT", "Apache-2.0"] },
                { cells: ["Looks at", "One string at a time: a prompt, or a model output", "Model calls and tool calls, with what the agent was granted"] },
                { cells: ["Decides by", "Scanners: a classifier for injection, plus PII, secrets, toxicity and more", "Detectors, then capability grants and argument provenance at the tool call"] },
                { cells: ["Keeps", "A verdict per scan", "A hash-chained audit trail with a standalone verifier"] },
                { cells: ["Runs as", "Python library or API server", "Python library, proxy, MCP governor, coding-agent hooks or HTTP gateway"] },
              ]}
            />
          </DocSection>

          <DocSection
            id="agentdojo"
            title="Attacks on a tool-using agent"
            lead="AgentDojo's 97 user tasks and 588 injection attacks, replayed through each guard with the model's calls taken from the answer key."
          >
            <Table
              head={["Defence", "Attacks that got through", "Normal tasks done without a person", "Harmless tool outputs flagged"]}
              rows={[
                { cells: ["No defence", "588 / 588", "97 / 97", "–"] },
                { cells: ["LLM Guard, default", "86 / 588 (14.6%)", "42 / 97", "82 / 339 (24.2%)"] },
                { cells: ["AgentFox, default", "0 / 588", "24 / 97", "0 / 339"], ours: true },
                { cells: ["AgentFox, detectors off", "0 / 588", "24 / 97", "–"], ours: true },
                { cells: ["Both together", "0 / 588", "11 / 97", "82 / 339"] },
              ]}
              source={{ label: "benchmarks/head_to_head", path: "benchmarks/head_to_head/README.md" }}
            />
            <p>
              LLM Guard reads each tool output and decides whether it holds an injection; most of its 86 misses are attacks
              past that point. AgentFox stops the call the injection asks for, which is why the detectors-off row is the
              same as the default row. The cost is on the other side: three in four normal tasks needed a person to approve
              a step. In its long-input mode, with a threshold picked on this test set, LLM Guard also stops all 588 at the
              same 24 tasks, but flags 38% of harmless tool outputs on the way.
            </p>
          </DocSection>

          <DocSection id="detection" title="Detection accuracy" lead="The detectors alone, on prompts neither tool had seen.">
            <Table
              head={["", "Held-out injections caught", "Harmless look-alikes flagged", "Attacks hidden in tool output"]}
              rows={[
                { cells: ["LLM Guard's model (ProtectAI DeBERTa v2)", "31.7%", "37.5%", "9 of 10 caught, 81.8% precision"] },
                { cells: ["AgentFox default (PIGuard and patterns)", "68.3%", "11.5%", "10 of 10 caught, 66.7% precision"], ours: true },
              ]}
              source={{ label: "benchmarks/injection", path: "benchmarks/injection/README.md" }}
            />
            <p>
              LLM Guard is the more precise of the two on attacks hidden in tool output, with two false alarms on the
              harmless half against our five.
            </p>
          </DocSection>

          <DocSection id="latency" title="What each check costs" lead="p50 and p95 on the same machine, short and long messages.">
            <Table
              head={["", "Checks for", "Short, p50 / p95 ms", "Long, p50 / p95 ms"]}
              rows={[
                { cells: ["LLM Guard, prompt-injection scanner", "Prompt injection", "56.1 / 66.2", "90.7 / 218"] },
                { cells: ["AgentFox, no model", "Seven kinds of deterministic check", "7.4 / –", "–"], ours: true },
                { cells: ["AgentFox, default", "Injection, PII, secrets, unsafe content, code", "63.1 / 77.6", "117 / 412"], ours: true },
                { cells: ["LLM Guard, nine default scanners", "Injection, PII, secrets, toxicity and five more", "249 / 316", "348 / 650"] },
              ]}
              source={{ label: "benchmarks/latency", path: "benchmarks/latency/README.md" }}
            />
            <p className="lp-doc-more">
              <Link href="/benchmark/latency">
                The full latency run <Arrow />
              </Link>
            </p>
          </DocSection>

          <DocSection id="pick" title="Which one" lead="Honest version.">
            <p>
              If you need a scanner in front of a chat model and nothing touches a tool, LLM Guard is lighter, more precise
              on tool-output injections, and a few milliseconds faster for injection alone. If your agent calls tools and
              you have to show what it was allowed to do and what it did, AgentFox holds after the scanner misses, and
              keeps the record. Running both is supported and stops the same 588; it also leaves only 11 tasks running
              without a person, so tune the grants first.
            </p>
            <Limits
              items={[
                "No model was run in the AgentDojo replay; the agent's calls are the benchmark's own answer key.",
                "Each figure is one run at published default thresholds. The LLM Guard version and run dates were not recorded.",
                "Sending a call to a person counts as stopping it.",
              ]}
            />
            <p className="lp-doc-more">
              <Link href="/docs/reference/migrate-from-llm-guard">
                Moving from LLM Guard: the same calls, mapped <Arrow />
              </Link>
              <Link href="/blog/llm-guard-vs-agentfox-agentdojo">
                The write-up of this run <Arrow />
              </Link>
              <Link href="/compare">
                All guardrails compared <Arrow />
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

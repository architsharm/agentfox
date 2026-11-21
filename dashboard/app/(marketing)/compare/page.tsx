import type { Metadata } from "next";
import Link from "next/link";

import { DocSection, Limits, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Open source AI guardrails compared (2026)",
  description:
    "AgentFox, LLM Guard, NeMo Guardrails, Guardrails AI, Prompt Guard 2 and Lakera Guard: what each one is, what they measure the same on our benchmarks, and where each one wins.",
  path: "/compare",
});

/**
 * The pillar page for "guardrails compared" queries. Every number is copied from
 * /benchmark or /benchmark/latency, where its script and limits live; nothing is
 * measured here. Tools we have not run are described from their own documentation
 * and say so.
 */
export default function ComparePage() {
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main id="main">
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <h1>
              AI guardrails, compared
              <br />
              <span className="lp-muted">on the same tests, losses included</span>
            </h1>
            <p className="lp-lead">
              Six tools people shortlist for prompt injection and agent safety. What each one is, what we could measure
              on the same data, and which to pick for what. Where we lose, it says so.
            </p>
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection id="what" title="What each one is" lead="Licence and shape first, because they decide most shortlists before any benchmark does.">
            <Table
              head={["Tool", "Licence", "What it is", "Where it runs"]}
              rows={[
                {
                  cells: [
                    "AgentFox",
                    "Apache-2.0",
                    "Control plane: detectors on model traffic, tool calls bounded by capability grants, hash-chained audit trail",
                    "Self-hosted, offline by default; hosted version optional",
                  ],
                  ours: true,
                },
                { cells: ["LLM Guard (Protect AI)", "MIT", "Scanners for prompts and outputs: injection, PII, secrets, toxicity and more", "Python library or API server"] },
                { cells: ["NeMo Guardrails (NVIDIA)", "Apache-2.0", "Dialogue rails in Colang, with LLM self-checks on input and output", "Python library"] },
                { cells: ["Guardrails AI", "Apache-2.0", "Validators on inputs and outputs from a hub, including a jailbreak detector", "Python library"] },
                { cells: ["Prompt Guard 2 (Meta)", "Model licence", "A classifier for injection and jailbreaks, 22M and 86M; a model, not a product", "Wherever you serve it"] },
                { cells: ["Lakera Guard (Check Point)", "Proprietary", "Hosted detection API for prompts and agent traffic; self-hosting on enterprise terms", "SaaS, or your VPC by quote"] },
              ]}
            />
            <p className="lp-doc-more">
              <Link href="/compare/llm-guard">
                LLM Guard vs AgentFox, in detail <Arrow />
              </Link>
              <Link href="/compare/lakera">
                Lakera Guard vs AgentFox <Arrow />
              </Link>
            </p>
          </DocSection>

          <DocSection
            id="measured"
            title="Measured on the same data"
            lead="These rows come from our benchmark pages, where each number has a script, a results file and a limits list. Blank cells were not run, not hidden."
          >
            <Table
              head={["", "Held-out injections caught", "Harmless look-alikes flagged", "AgentDojo attacks through", "p50 latency, short message"]}
              rows={[
                { cells: ["AgentFox, default", "68.3%", "11.5%", "0 / 588", "63.1 ms"], ours: true },
                { cells: ["LLM Guard, injection scanner", "31.7%", "42.2%", "86 / 588", "56.1 ms"] },
                { cells: ["Prompt Guard 2, 86M", "20.0%", "3.5%", "–", "54.4 ms"] },
                { cells: ["Guardrails AI, DetectJailbreak", "–", "–", "–", "99.4 ms"] },
                { cells: ["NeMo Guardrails, self-check", "–", "–", "–", "758 ms"] },
                { cells: ["Lakera Guard", "–", "–", "–", "–"] },
              ]}
              source={{ label: "benchmarks", path: "benchmarks/README.md" }}
            />
            <p>
              Where we lose: on AgentDojo, LLM Guard finishes 42 of 97 normal tasks without a person approving a step, and
              AgentFox finishes 24. Prompt Guard 2 flags fewer harmless prompts than we do, 3.5% against 11.5%. On attacks
              hidden in tool output, LLM Guard is more precise, 81.8% against our 66.7%. And LLM Guard&apos;s injection
              scanner answers 7 ms faster than our default, which runs five kinds of check.
            </p>
            <p className="lp-doc-more">
              <Link href="/benchmark">
                Every security result with its limits <Arrow />
              </Link>
              <Link href="/benchmark/latency">
                The latency head-to-head <Arrow />
              </Link>
            </p>
          </DocSection>

          <DocSection id="pick" title="Which one, for what" lead="Most teams need one of these, not all of them.">
            <Table
              head={["You need", "Start with"]}
              rows={[
                { cells: ["A scanner for prompts and model outputs, nothing in the tool path", "LLM Guard, or Prompt Guard 2 if false alarms matter more than recall"] },
                { cells: ["Scripted dialogue flows and topic rails for a chatbot", "NeMo Guardrails"] },
                { cells: ["Validation of structured output, with a catalogue of checks", "Guardrails AI"] },
                { cells: ["A managed service with a vendor on the hook", "Lakera Guard"] },
                { cells: ["Agents that call tools, with a record an auditor can check without you", "AgentFox"], ours: true },
              ]}
            />
            <Limits
              items={[
                "Lakera Guard was not run: it is closed and its terms do not allow the kind of benchmark we publish. Its row is described from Lakera's documentation.",
                "NeMo Guardrails and Guardrails AI appear in the latency run only. Their detection was not measured on our injection sets.",
                "Each figure is a single run at the tool's published default threshold. Versions and dates are on the benchmark pages where they were recorded, and missing where they were not.",
              ]}
            />
          </DocSection>
        </div>

        <LpCta />
      </main>
      <LpFooter />
    </div>
  );
}

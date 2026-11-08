import type { Metadata } from "next";
import Link from "next/link";

import { Contents, DocSection, Limits, Rerun, Source, Table } from "@/components/lp/bench";
import { Reveal } from "@/components/lp/client";
import { FlowArt } from "@/components/lp/FlowArt";
import { Arrow, LpCta, LpFooter, LpNav } from "@/components/lp/parts";
import { publicPageMetadata } from "@/lib/site";

export const dynamic = "force-dynamic";

/*
 * Every figure is copied from a results file and bound in benchmarks/claims.yaml, so a
 * rerun that moves a number fails CI here too:
 *
 *   benchmarks/latency/results/headline.json               the 109-repository study
 *   benchmarks/latency/head_to_head/results/summary.json   the head-to-head
 */

export const metadata: Metadata = publicPageMetadata({
  title: "Latency benchmark",
  description:
    "What an AgentFox guard check adds, measured on traffic from 109 real agent repositories and against other guards on the same machine.",
  path: "/benchmark/latency",
});

const STATS: { figure: string; unit: string; label: string; vs: string }[] = [
  {
    figure: "57.4",
    unit: "ms",
    label: "median per check, with the ML classifier",
    vs: "With the ML prompt-injection classifier included; 302 ms at p95.",
  },
  {
    figure: "3.1",
    unit: "ms",
    label: "median per tool call",
    vs: "Tool calls are checked on structure, so they skip the classifier.",
  },
  {
    figure: "2.3",
    unit: "ms",
    label: "median without the model",
    vs: "Patterns, PII, secrets, schema, unicode and code checks only.",
  },
];

/** Short messages, p50 ms, from the head-to-head. `checks` is what each one looks for. */
const RACE: { name: string; checks: string; ms: number; ours?: boolean }[] = [
  { name: "AgentFox, no model", checks: "7 kinds of check", ms: 7.4, ours: true },
  { name: "Prompt Guard 2 22M", checks: "Injection, jailbreaks", ms: 25.5 },
  { name: "Prompt Guard 2 86M", checks: "Injection, jailbreaks", ms: 54.4 },
  { name: "LLM Guard, injection scanner", checks: "Injection", ms: 56.1 },
  { name: "AgentFox default", checks: "Injection, PII, secrets, unsafe content, code", ms: 63.1, ours: true },
  { name: "Guardrails AI, DetectJailbreak", checks: "Jailbreaks", ms: 99.4 },
  { name: "LLM Guard, nine scanners", checks: "Injection, PII, secrets, toxicity, more", ms: 249 },
  { name: "OpenAI moderation (hosted)", checks: "Harm categories", ms: 387 },
  { name: "NeMo Guardrails, self-check", checks: "One LLM policy check", ms: 758 },
];

const LAYERS: [string, string, string, string][] = [
  ["Deterministic", "Patterns, PII, secrets, schema, unicode and code checks", "2.3 / 6.4", "8.8"],
  ["Default", "Deterministic + ML prompt-injection classifier", "57.4 / 302", "179"],
  ["Extended", "Default + similarity search against known attacks, score cache on", "9.9 / 276", "77.1"],
  ["With an LLM judge", "Extended + injection and PII judged by gpt-4.1-mini", "76.5 / 1,009", "1,086"],
];

const HEAD_TO_HEAD: [string, string, string, string][] = [
  ["AgentFox deterministic", "PII, secrets, injection patterns, unsafe content, schema, unicode, insecure code", "7.4 / 9.1", "11.7 / 38.9"],
  ["AgentFox default", "The above, plus injection and jailbreaks by classifier", "63.1 / 77.6", "117 / 412"],
  ["AgentFox default, cache on", "Same", "60.1 / 67.2", "104 / 401"],
  ["AgentFox extended", "The above, plus similarity to known attacks", "71.0 / 89.0", "126 / 464"],
  ["AgentFox with LLM judges, default mode", "The above, plus injection and PII judged by gpt-4.1-mini when a rule relies on it", "74.1 / 98.5", "122 / 356"],
  ["AgentFox with LLM judges always inline", "Same, judged on every check", "865 / 1,093", "879 / 1,448"],
  ["LLM Guard, prompt-injection scanner", "Prompt injection", "56.1 / 66.2", "90.7 / 218"],
  ["Meta Prompt Guard 2 86M", "Prompt injection and jailbreaks", "54.4 / 62.6", "86.8 / 209"],
  ["Meta Prompt Guard 2 22M", "Prompt injection and jailbreaks", "25.5 / 29.9", "48.4 / 106"],
  ["Guardrails AI, DetectJailbreak", "Jailbreaks", "99.4 / 107", "149 / 325"],
  ["LLM Guard, nine default scanners", "Injection, PII, secrets, toxicity and five more", "249 / 316", "348 / 650"],
  ["OpenAI omni-moderation (hosted)", "Harm categories, not injection", "387 / 484", "395 / 509"],
  ["NeMo Guardrails, self-check (gpt-4.1-mini)", "One LLM policy check", "758 / 1,049", "787 / 1,201"],
];

const PUBLISHED: [string, string, string, string][] = [
  ["Protect AI LLM Guard, injection scanner", "https://protectai.github.io/llm-guard/input_scanners/prompt_injection/", "104 ms mean / 107 ms p95 (ONNX)", "AWS m5.xlarge CPU, 384-token input"],
  ["Meta Prompt Guard 2", "https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Prompt-Guard-2/86M/MODEL_CARD.md", "86M: 92.4 ms; 22M: 19.3 ms", "A100 GPU, 512 tokens"],
  ["Lakera Guard", "https://docs.lakera.ai/docs/evaluation-overview", "p95 50 ms to 300 ms", "1 to 16 detectors, about 1k to 5k characters"],
  ["NVIDIA NeMo Guardrails", "https://developer.nvidia.com/blog/measuring-the-effectiveness-and-performance-of-ai-guardrails-in-generative-ai-applications/", "about 0.5 s added per chat turn", "Three rails, GPU microservices"],
  ["Palo Alto Prisma AIRS", "https://docs.paloaltonetworks.com/prisma-airs/ai-runtime-security/airs-vm-firewall/performance-in-prisma-airs", "about 700 ms added", "Network firewall intercept mode"],
];

const SECTIONS = [
  { id: "head-to-head", label: "Head to head on one machine" },
  { id: "layers", label: "Per check and per agent turn" },
  { id: "drivers", label: "What makes a check slower" },
  { id: "published", label: "What other vendors publish" },
  { id: "method", label: "How it was measured" },
  { id: "reproduce", label: "Rerun it yourself" },
];

export default function LatencyBenchmarkPage() {
  const max = Math.max(...RACE.map((r) => r.ms));
  return (
    <div className="lp">
      <Reveal />
      <LpNav />
      <main>
        <section className="lp-hero lp-hero-short">
          <FlowArt mode="ribbon" />
          <div className="lp-hero-copy">
            <span className="lp-pill">Latency benchmark</span>
            <h1>
              What a guard check
              <br />
              <span className="lp-muted">adds to your agent</span>
            </h1>
            <p className="lp-lead">
              Measured on 41,520 guard calls replayed from 109 real agent repositories, and against other guards on the same
              machine.
            </p>
          </div>
        </section>

        <section className="lp-section lp-section-tight">
          <div className="lp-wrap">
            <div className="lp-stats" data-reveal>
              {STATS.map((s) => (
                <div key={s.label} className="lp-stat">
                  <span className="lp-stat-n">
                    {s.figure}
                    <small> {s.unit}</small>
                  </span>
                  <span className="lp-stat-l">{s.label}</span>
                  <span className="lp-stat-vs">{s.vs}</span>
                </div>
              ))}
            </div>
            <p className="lp-note">
              Engine time on a laptop CPU with no GPU. The network and the agent&apos;s own model are excluded.
            </p>
            <Contents items={SECTIONS} />
          </div>
        </section>

        <div className="lp-wrap lp-doc">
          <DocSection
            id="head-to-head"
            n={1}
            title="Head to head on one machine"
            lead="Every guard ran on the same 880 messages, on the same laptop CPU, one request at a time. AgentFox runs five kinds of check in about the time the others take for one."
          >
            <div className="lp-race" data-reveal>
              <div className="lp-race-head">
                <h3>Median time per short message</h3>
                <span>milliseconds · lower is faster</span>
              </div>
              <div className="lp-pairs-in">
                {RACE.map((r) => (
                  <div key={r.name} className={`lp-pair-row${r.ours ? " is-ours" : ""}`}>
                    <span className="lp-pair-name">
                      {r.name}
                      <small>{r.checks}</small>
                    </span>
                    <span className="lp-pair-track">
                      <i style={{ "--w": `${Math.max(0.8, (r.ms / max) * 100)}%` } as React.CSSProperties} />
                    </span>
                    <span className="lp-pair-v">{r.ms} ms</span>
                  </div>
                ))}
              </div>
            </div>
            <p>
              Base-size models (AgentFox&apos;s classifier, the one in LLM Guard&apos;s scanner, Prompt Guard 2 86M) all take
              about 50 ms. AgentFox adds an HTTP round trip and its deterministic checks, 7.4 ms on their own. Its default
              checks take 63.1 ms, against 56.1 ms for LLM Guard&apos;s prompt-injection scanner, which looks for injection only.
            </p>
            <Table
              head={["System", "Checks for", "Short messages, p50 / p95 (ms)", "Long messages, p50 / p95 (ms)"]}
              rows={HEAD_TO_HEAD.map(([name, detects, short, long]) => ({
                cells: [name, detects, short, long],
                ours: name === "AgentFox default",
              }))}
              source={{ label: "benchmarks/latency/head_to_head", path: "benchmarks/latency/head_to_head/results/summary.json" }}
            />
            <p>
              On long messages AgentFox reads the first 4,000 characters, where the others stop at 512 tokens. It does more work
              there, at a p95 of 412 ms, and reads every message to the end. With every LLM judge inline, AgentFox is about 100
              ms slower than NeMo&apos;s single self-check, because its judge answers three questions where NeMo asks one. By
              default a judge only waits inline when an enforcing rule relies on it.
            </p>
            <Limits
              items={[
                <>
                  This measures speed only. What each guard catches is on the <Link href="/benchmark">security benchmark</Link>.
                </>,
              ]}
            />
          </DocSection>

          <DocSection
            id="layers"
            n={2}
            title="Per check and per agent turn"
            lead="Each repository was mapped with agentfox init, and its own agents, tools and handoffs drove the traffic: single turns, five-turn sessions and multi-agent handoffs, through the same endpoints the SDK calls."
          >
            <Table
              head={["Layer", "What runs", "Per check, p50 / p95 (ms)", "Per single-agent turn, p50 (ms)"]}
              rows={LAYERS.map(([layer, what, check, turn]) => ({ cells: [layer, what, check, turn], ours: layer === "Default" }))}
              source={{ label: "benchmarks/latency/results/headline.json", path: "benchmarks/latency/results/headline.json" }}
            />
            <p>
              Tool calls are the cheapest step in every layer, 3.1 ms at the median with the default detectors. Text the
              classifier has to read (inputs, tool results, replies) is where the time goes. A single turn makes four guard
              calls, summed in the last column.
            </p>
            <p>
              Extended&apos;s median is lower than Default&apos;s because it was measured with the score cache on, so text the
              classifier has already scored is not read again. The similarity search itself adds only a few milliseconds over Default with the
              cache on (benchmarks/latency/README.md).
            </p>
            <p>
              Messages under 200 characters take 54.5 ms at the median and 83.5 ms at p95. Between 200 and 600 characters they
              take 188 ms and 374 ms, because longer text gets a 1,000 ms budget so the classifier can finish reading it. Replies
              with judges on pay the commitment check, about 0.88 s.
            </p>
          </DocSection>

          <DocSection id="drivers" n={3} title="What makes a check slower">
            <div className="lp-cards lp-cards-2" data-reveal>
              <article className="lp-card">
                <h3>Message length: yes</h3>
                <p>The classifier reads text in 256-token windows, so a 500-character tool result costs several times a short question.</p>
              </article>
              <article className="lp-card">
                <h3>Where it runs: yes</h3>
                <p>A hosted guard pays the network on every call. From Bengaluru to a US region that is about 310 ms before any check runs. Run the gateway next to the agent.</p>
              </article>
              <article className="lp-card">
                <h3>Session length: no</h3>
                <p>Per-check latency is flat from the first turn of a session to the fifth.</p>
              </article>
              <article className="lp-card">
                <h3>Framework: barely</h3>
                <p>LangGraph, CrewAI, AutoGen, the OpenAI Agents SDK, ADK and the rest land within a few milliseconds of each other per check.</p>
              </article>
            </div>
          </DocSection>

          <DocSection
            id="published"
            n={4}
            title="What other vendors publish"
            lead="Few vendors publish latency, and fewer say under what conditions. Azure Prompt Shields, AWS Bedrock Guardrails, Google Model Armor, OpenAI Moderation, Llama Guard and Guardrails AI publish none. These are the figures we found, as their authors state them."
          >
            <Table
              head={["Product", "Published latency", "Conditions"]}
              rows={PUBLISHED.map(([name, href, figure, conditions]) => ({
                cells: [
                  <a key="n" href={href} target="_blank" rel="noreferrer" className="lp-table-link">
                    {name}
                  </a>,
                  figure,
                  conditions,
                ],
              }))}
            />
          </DocSection>

          <DocSection id="method" n={5} title="How it was measured">
            <Limits
              items={[
                "119 agent repositories were examined; 109 produced an agent map and were tested: 76 public, 26 held out from the mapper work and 7 local, four of them private and anonymised.",
                "Apple M1 Pro, CPU only, one gateway worker on SQLite, Python 3.12 as in the production image. A server with more workers and a server database will do better, so read these as a floor.",
                "Engine time is the gateway's own time per check. The agent's model and the network are excluded unless a row says otherwise.",
                "The default layer is reported with the score cache off, because the attack suite repeats text and the cache would flatter it.",
              ]}
            />
          </DocSection>

          <DocSection
            id="reproduce"
            n={6}
            title="Rerun it yourself"
            lead="Every recorded call, the scripts and the head-to-head harness are in benchmarks/latency."
          >
            <Rerun
              commands={[
                "uv run python -m benchmarks.latency.fetch_repos var/latency/repos",
                "uv run python -m benchmarks.latency.map_repos var/latency/repos var/latency",
                "uv run python -m benchmarks.latency.run_latency var/latency/maps var/latency/run",
                "uv run python -m benchmarks.latency.report var/latency var/latency/results run",
              ]}
            />
            <Source label="benchmarks/latency" path="benchmarks/latency/README.md" />
            <p className="lp-doc-more">
              <Link href="/benchmark">
                Security benchmarks: what each guard catches <Arrow />
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

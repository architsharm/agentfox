import type { Metadata } from "next";
import Link from "next/link";

import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { publicPageMetadata } from "@/lib/site";

/**
 * Public latency benchmark: what a guard check adds, on traffic replayed from real agent
 * repositories, and how it compares with other guards on the same machine.
 *
 * Every figure is copied from a results file in the repository and bound in
 * benchmarks/claims.yaml, so a rerun that moves a number fails CI here too:
 *
 *   benchmarks/latency/results/headline.json        the 109-repository study
 *   benchmarks/latency/head_to_head/results/summary.json   the head-to-head
 */

export const metadata: Metadata = publicPageMetadata({
  title: "Latency benchmark",
  description:
    "What an AgentFox guard check adds, measured on traffic from 109 real agent repositories and against other guards on the same machine.",
  path: "/benchmark/latency",
});

const REPO = "https://github.com/architsharm/agentfox";

function Source({ children }: { children: React.ReactNode }) {
  return <p className="source">Source: {children}</p>;
}

const CLAIMS: { question: string; figure: string; unit?: string; detail: string; limit: string }[] = [
  {
    question: "What does a check add?",
    figure: "49.6",
    unit: " ms",
    detail:
      "median per check with the default detectors, the ML prompt-injection classifier included; 260 ms at p95.",
    limit:
      "Engine time on a laptop CPU with no GPU, network and the agent's own model excluded, cache off. The p95 is the 300 ms check budget, reached on longer text.",
  },
  {
    question: "And without the model?",
    figure: "2.1",
    unit: " ms",
    detail: "median per check for the deterministic detectors alone: patterns, PII, secrets, schema, unicode, insecure code.",
    limit: "These catch less on their own; the classifier is what reads an injection phrased in ordinary words.",
  },
  {
    question: "Against LLM Guard?",
    figure: "58.4",
    unit: " ms",
    detail:
      "median for AgentFox's default checks on short messages, against 51.1 ms for LLM Guard's prompt-injection scanner on the same messages and machine.",
    limit:
      "LLM Guard's scanner detects injection only; AgentFox also runs PII, secrets and the rest, over HTTP. Speed only, not accuracy.",
  },
];

const CONTENTS: { id: string; title: string }[] = [
  { id: "layers", title: "Per check and per agent turn" },
  { id: "head-to-head", title: "Head to head on one machine" },
  { id: "drivers", title: "What moves latency, and what does not" },
  { id: "published", title: "What other vendors publish" },
  { id: "method", title: "Method and limits" },
  { id: "reproduce", title: "How to reproduce it" },
];

const LAYERS: [string, string, string, string][] = [
  ["Deterministic", "Patterns, PII, secrets, schema, unicode and code checks", "2.1 / 6.0", "8.0"],
  ["Default", "Deterministic + ML prompt-injection classifier", "49.6 / 260", "156"],
  ["Extended", "Default + similarity search against known attacks", "9.4 / 262", "73.9"],
  ["With an LLM judge", "Extended + injection and PII judged by gpt-4.1-mini", "68.7 / 949", "1,017"],
];

const HEAD_TO_HEAD: [string, string, string, string][] = [
  ["AgentFox default", "Injection, jailbreaks, PII, secrets, unsafe content, schema, unicode, insecure code", "58.4 / 64.6", "99.8 / 273"],
  ["LLM Guard, prompt-injection scanner", "Prompt injection", "51.1 / 56.3", "83.3 / 194"],
  ["Meta Prompt Guard 2 86M", "Prompt injection and jailbreaks", "49.7 / 55.6", "81.6 / 191"],
  ["Meta Prompt Guard 2 22M", "Prompt injection and jailbreaks", "21.7 / 24.6", "44.5 / 99.3"],
  ["Guardrails AI, DetectJailbreak", "Jailbreaks", "99.4 / 107", "149 / 325"],
  ["LLM Guard, nine default scanners", "Injection, PII, secrets, toxicity and five more", "249 / 316", "348 / 650"],
  ["OpenAI omni-moderation (hosted)", "Harm categories, not injection", "411 / 548", "446 / 552"],
  ["NeMo Guardrails, self-check (gpt-4.1-mini)", "One LLM policy check", "871 / 1,288", "838 / 1,311"],
  ["AgentFox with the LLM judge (gpt-4.1-mini)", "The default checks, plus injection and PII judged by an LLM", "1,025 / 1,436", "1,070 / 1,777"],
];

const PUBLISHED: [string, string, string, string][] = [
  ["Protect AI LLM Guard, injection scanner", "https://protectai.github.io/llm-guard/input_scanners/prompt_injection/", "104 ms mean / 107 ms p95 (ONNX)", "AWS m5.xlarge CPU, 384-token input"],
  ["Meta Prompt Guard 2", "https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Prompt-Guard-2/86M/MODEL_CARD.md", "86M: 92.4 ms; 22M: 19.3 ms", "A100 GPU, 512 tokens"],
  ["Lakera Guard", "https://docs.lakera.ai/docs/evaluation-overview", "p95 50 ms to 300 ms", "1 to 16 detectors, about 1k to 5k characters"],
  ["NVIDIA NeMo Guardrails", "https://developer.nvidia.com/blog/measuring-the-effectiveness-and-performance-of-ai-guardrails-in-generative-ai-applications/", "about 0.5 s added per chat turn", "Three rails, GPU microservices"],
  ["Palo Alto Prisma AIRS", "https://docs.paloaltonetworks.com/prisma-airs/ai-runtime-security/airs-vm-firewall/performance-in-prisma-airs", "about 700 ms added", "Network firewall intercept mode"],
];

export default function LatencyBenchmarkPage() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <div>
              <h1 className="mk-h1">What a guard check adds to your agent</h1>
              <p className="mk-lede" style={{ marginTop: 18 }}>
                Measured on 41,540 guard calls replayed from 109 real agent repositories,
                and against other guards on the same machine.
              </p>
            </div>
            <div className="bm-claims">
              {CLAIMS.map((c) => (
                <div key={c.question} className="bm-claim">
                  <h2>{c.question}</h2>
                  <p className="figure figure-lg bm-claim-figure">
                    {c.figure}
                    {c.unit && <span className="unit">{c.unit}</span>}
                  </p>
                  <p className="bm-claim-detail">{c.detail}</p>
                  <p className="bm-claim-limit">{c.limit}</p>
                </div>
              ))}
            </div>
            <nav className="bm-index" style={{ marginTop: 28 }} aria-label="Sections">
              {CONTENTS.map((c, i) => (
                <a key={c.id} href={`#${c.id}`}>
                  <i>{String(i + 1).padStart(2, "0")}</i>
                  <span>{c.title}</span>
                </a>
              ))}
            </nav>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <article className="bm-doc">
              <p className="lede">
                Each repository was mapped with <code className="mono">agentfox init</code>, and its own
                agents, tools and handoffs drove the traffic: single turns, five-turn sessions and
                multi-agent handoffs, through the same guard endpoints an SDK calls.
              </p>

              <h2 id="layers">1. Per check and per agent turn</h2>
              <p>
                Tool calls are the cheapest step in every layer, 2.4 ms at the median with the
                default detectors. Text the classifier must read (inputs, tool results, replies) carries
                the cost. A turn is every guard call it makes, summed: four for a single turn.
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Layer</th>
                    <th>What runs</th>
                    <th>Per check, p50 / p95 (ms)</th>
                    <th>Per single-agent turn, p50 (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {LAYERS.map(([layer, what, check, turn]) => (
                    <tr key={layer}>
                      <td>{layer}</td>
                      <td>{what}</td>
                      <td className="mono">{check}</td>
                      <td className="mono">{turn}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p>
                Messages under 200 characters take 49.0 ms at the median and 60.3 ms at p95 with the
                default detectors, and none runs out of time. Between 200 and 600 characters, 22.3%
                reach the 300 ms check budget before the classifier finishes on a CPU with no GPU;
                those checks return without its verdict and say so. With judges on, a judge waits
                inline only when an enforcing rule relies on it, the default, so most checks do not
                wait for it; replies pay the commitment check, about 0.85 s.
              </p>
              <Source>
                <code className="mono">benchmarks/latency/results/headline.json</code>, from{" "}
                <a href={`${REPO}/tree/main/benchmarks/latency`}>benchmarks/latency</a>
              </Source>

              <h2 id="head-to-head">2. Head to head on one machine</h2>
              <p>
                Every system ran on the same 880 messages, on the same machine, on CPU, under the same
                Python, one request at a time. Base-size models (AgentFox&apos;s classifier, the one in
                LLM Guard&apos;s scanner, Prompt Guard 2 86M) all take about 50 ms; AgentFox adds an HTTP
                round trip and its other checks.
              </p>
              <table>
                <thead>
                  <tr>
                    <th>System</th>
                    <th>Detects</th>
                    <th>Short messages, p50 / p95 (ms)</th>
                    <th>Long messages, p50 / p95 (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {HEAD_TO_HEAD.map(([name, detects, short, long]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td className="small">{detects}</td>
                      <td className="mono">{short}</td>
                      <td className="mono">{long}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p>
                On long messages AgentFox reads the first 4,000 characters, where the others stop at 512
                tokens, so it does more work: on CPU 51 of 150 long inputs ran past the 300 ms check budget
                before the classifier finished. With an LLM judge it is about 150 ms slower than NeMo&apos;s
                single self-check, mostly because its judge answers three questions where NeMo asks one.
              </p>
              <Source>
                <code className="mono">benchmarks/latency/head_to_head/results/summary.json</code>
              </Source>

              <h2 id="drivers">3. What moves latency, and what does not</h2>
              <ul>
                <li>
                  <strong>Message length moves it.</strong> The classifier reads text in 256-token windows,
                  so a 500-character tool result costs several times a short question.
                </li>
                <li>
                  <strong>Session length does not.</strong> Per-check latency is flat from the first turn of
                  a session to the fifth.
                </li>
                <li>
                  <strong>Framework and repository shape barely do.</strong> Single-agent, independent-agent
                  and multi-agent repositories, and LangGraph, CrewAI, AutoGen, the OpenAI Agents SDK, ADK
                  and the rest, land within a few milliseconds of each other per check.
                </li>
                <li>
                  <strong>Where it runs does.</strong> A hosted guard pays the network every call; from
                  Bengaluru to a US region that is about 260 ms before the guard does anything. Run the
                  gateway beside the agent.
                </li>
              </ul>

              <h2 id="published">4. What other vendors publish</h2>
              <p>
                Few vendors publish latency, and fewer say under what conditions. Azure Prompt Shields, AWS
                Bedrock Guardrails, Google Model Armor, OpenAI Moderation, Llama Guard and Guardrails AI
                publish none. These are the figures we found, as their authors state them:
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Published latency</th>
                    <th>Conditions</th>
                  </tr>
                </thead>
                <tbody>
                  {PUBLISHED.map(([name, href, figure, conditions]) => (
                    <tr key={name}>
                      <td>
                        <a href={href}>{name}</a>
                      </td>
                      <td>{figure}</td>
                      <td className="small">{conditions}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h2 id="method">5. Method and limits</h2>
              <ul>
                <li>
                  119 agent repositories were examined; 109 produced an agent map and were tested,
                  76 public, 26 held out from the mapper work and 7 local, four of them private and anonymised.
                </li>
                <li>
                  Apple M1 Pro, CPU only, one gateway worker on SQLite, Python 3.12 as in the production image.
                  A server with more workers and a server database will do better; read these as a floor.
                </li>
                <li>
                  Engine time is the gateway&apos;s own time per check. The agent&apos;s model and the network
                  are excluded, except where a row says otherwise.
                </li>
                <li>
                  The default layer is reported with the score cache off: the attack suite repeats text, and
                  the cache would flatter it.
                </li>
                <li>This measures speed. What each guard catches is on the <Link href="/benchmark">security benchmarks</Link> page.</li>
              </ul>

              <h2 id="reproduce">6. How to reproduce it</h2>
              <pre className="hero-code">
                python -m benchmarks.latency.fetch_repos var/latency/repos{"\n"}
                python -m benchmarks.latency.map_repos var/latency/repos var/latency{"\n"}
                python -m benchmarks.latency.run_latency var/latency/maps var/latency/run{"\n"}
                python -m benchmarks.latency.report var/latency var/latency/results run
              </pre>
              <p>
                Every recorded call, the scripts and the head-to-head harness are in{" "}
                <a href={`${REPO}/tree/main/benchmarks/latency`}>benchmarks/latency</a>.
              </p>
            </article>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}

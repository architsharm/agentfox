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
    figure: "57.4",
    unit: " ms",
    detail:
      "median per check with the default detectors, the ML prompt-injection classifier included; 302 ms at p95.",
    limit:
      "Engine time on a laptop CPU with no GPU, network and the agent's own model excluded, cache off. Long text costs more: 188 ms at the median between 200 and 600 characters.",
  },
  {
    question: "And without the model?",
    figure: "2.3",
    unit: " ms",
    detail: "median per check for the deterministic detectors alone: patterns, PII, secrets, schema, unicode, insecure code.",
    limit: "These catch less on their own; the classifier is what reads an injection phrased in ordinary words.",
  },
  {
    question: "Against LLM Guard?",
    figure: "63.1",
    unit: " ms",
    detail:
      "median for AgentFox's default checks on short messages, against 56.1 ms for LLM Guard's prompt-injection scanner on the same messages and machine.",
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
  ["Deterministic", "Patterns, PII, secrets, schema, unicode and code checks", "2.3 / 6.4", "8.8"],
  ["Default", "Deterministic + ML prompt-injection classifier", "57.4 / 302", "179"],
  ["Extended", "Default + similarity search against known attacks", "9.9 / 276", "77.1"],
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
                Measured on 41,520 guard calls replayed from 109 real agent repositories,
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
                Tool calls are the cheapest step in every layer, 3.1 ms at the median with the
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
                Messages under 200 characters take 54.5 ms at the median and 83.5 ms at p95 with the
                default detectors. Between 200 and 600 characters they take 188 ms and 374 ms: text
                over 200 characters gets a 1,000 ms check budget, so the classifier finishes reading it
                rather than returning without a verdict. With judges on, a judge waits inline only when
                an enforcing rule relies on it, the default, so most checks do not wait for it; replies
                pay the commitment check, about 0.88 s.
              </p>
              <Source>
                <code className="mono">benchmarks/latency/results/headline.json</code>, from{" "}
                <a href={`${REPO}/tree/main/benchmarks/latency`}>benchmarks/latency</a>
              </Source>

              <h2 id="head-to-head">2. Head to head on one machine</h2>
              <p>
                Every system ran on the same 880 messages, on the same machine, on CPU, under the same
                Python, one request at a time, with AgentFox at each of its levels. Base-size models
                (AgentFox&apos;s classifier, the one in LLM Guard&apos;s scanner, Prompt Guard 2 86M)
                all take about 50 ms; AgentFox adds an HTTP round trip and its deterministic checks,
                7.4 ms on their own.
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
                tokens, so it does more work, at a long-message p95 of 412 ms, and reads every one to the
                end. In its default mode a judge waits only when a rule relies
                on it; with every judge inline, AgentFox is about 100 ms slower than NeMo&apos;s single
                self-check, mostly because its judge answers three questions where NeMo asks one.
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

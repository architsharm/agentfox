import Link from "next/link";

import type { TocItem } from "@/components/marketing/blog/article";
import { InlineCTA, Takeaways, type FaqItem } from "@/components/marketing/blog/blocks";

export const toc: TocItem[] = [
  { id: "short", label: "The short answer" },
  { id: "how", label: "How we measured it" },
  { id: "layers", label: "What each layer costs" },
  { id: "drivers", label: "What moves latency, and what does not" },
  { id: "others", label: "Against other guards, on one machine" },
  { id: "judge", label: "When an LLM judge is in the loop" },
  { id: "deploy", label: "Keeping it fast in production" },
];

export const faq: FaqItem[] = [
  {
    q: "How much latency does an AI agent guardrail add?",
    a: "With AgentFox's default detectors, 49.6 ms at the median and 260 ms at p95 per check on a laptop CPU, measured on traffic from 109 real agent repositories; the p95 is the 300 ms check budget, reached on longer text. Deterministic checks alone add 2.1 ms. An LLM judge in the loop adds about a second, mostly the model's own response time.",
  },
  {
    q: "Is AgentFox slower than LLM Guard or Prompt Guard?",
    a: "On short messages on the same machine, AgentFox's default checks took 58.8 ms at the median against 52.2 ms for LLM Guard's prompt-injection scanner and 51.7 ms for Prompt Guard 2 86M. The models are the same size; AgentFox adds an HTTP round trip and its PII, secrets and other checks. Prompt Guard 2 22M is faster, at 23.9 ms. AgentFox's deterministic checks alone took 6.9 ms.",
  },
  {
    q: "Does guardrail latency grow over a long conversation?",
    a: "No. Per-check latency was flat from the first turn of a session to the fifth. What moves it is the length of the text being checked.",
  },
  {
    q: "Where can I see the raw data?",
    a: "Every recorded call, the per-repository results, the scripts and the head-to-head harness are in benchmarks/latency in the AgentFox repository, and the latency benchmark page on this site summarises them.",
  },
];

export function Body() {
  return (
    <>
      <Takeaways
        items={[
          "A check with AgentFox's default detectors adds 49.6 ms at the median and 260 ms at p95, on a laptop CPU, across 109 real agent repositories.",
          "Tool calls cost about 2.4 ms; what costs is text the classifier has to read, and latency does not grow over a conversation.",
          "Model for model, guards of the same size run at the same speed. The choice that matters is how much you check, and where the guard runs.",
        ]}
      />

      <h2 id="short">The short answer</h2>
      <p>
        Every team we talk to asks the same question before they put a guardrail in front of an
        agent: how much slower will it get? So we measured it on agents people actually built:
        41,540 guard calls replayed from 109 open agent repositories and a few private ones.
      </p>
      <p>
        With the default detectors, which include an ML prompt-injection classifier, a check adds{" "}
        <strong>49.6 ms at the median and 260 ms at p95</strong>. With only the deterministic
        checks, it adds <strong>2.1 ms</strong>. That p95 is not a slow model: it is the
        300 ms budget a check is allowed. On a laptop CPU with no GPU, about a fifth of messages
        between 200 and 600 characters run out of it before the classifier finishes, and those
        checks say so. Messages under 200 characters take 49.0 ms at the median and 60.3 ms at
        p95. The rest of this post is where those numbers come from, what moves them, and how
        they compare with other guards.
      </p>

      <h2 id="how">How we measured it</h2>
      <p>
        We pointed <code>agentfox init</code> at each repository. It maps the agents the code
        defines, the tools each one is handed and which agent hands work to which, across
        LangGraph, CrewAI, AutoGen, the OpenAI Agents SDK, Google ADK, Agno, Pydantic AI,
        TypeScript frameworks and plain code. From each map we replayed three kinds of traffic
        through the same guard endpoints an SDK calls:
      </p>
      <ul>
        <li>a single turn: user message, tool call, tool result, reply;</li>
        <li>a five-turn session, benign questions first and attacks after;</li>
        <li>a multi-agent handoff: root agent, sub-agent, its tool, and back.</li>
      </ul>
      <p>
        The messages are attacks and benign controls written against each repository&apos;s real
        agents and tools. Everything ran on an Apple M1 Pro, CPU only, one gateway worker, Python
        3.12 as in our production image. We report the gateway&apos;s own time per check, so the
        agent&apos;s model and the network are not in it.
      </p>

      <h2 id="layers">What each layer costs</h2>
      <p>
        AgentFox runs detectors in layers you choose. Per check, at the median and p95:
      </p>
      <ul>
        <li>
          <strong>Deterministic</strong> (patterns, PII, secrets, schema, invisible Unicode,
          insecure code): 2.1 / 6.0 ms.
        </li>
        <li>
          <strong>Default</strong> (plus the ML prompt-injection classifier): 49.6 / 260 ms.
        </li>
        <li>
          <strong>Extended</strong> (plus similarity search against known attacks): 9.4 / 262 ms,
          with the score cache on.
        </li>
        <li>
          <strong>With LLM judges</strong>, in the default mode where a judge waits only when a
          rule relies on it: 68.7 / 949 ms. Replies pay a commitment check, about 0.85 s.
        </li>
      </ul>
      <p>
        A whole single-agent turn, four guard calls, adds 156 ms at the median with the default
        layer. The full tables, per step and per scenario, are on the{" "}
        <Link href="/benchmark/latency">latency benchmark</Link> page.
      </p>

      <h2 id="drivers">What moves latency, and what does not</h2>
      <p>
        <strong>Text length moves it.</strong> Checking a tool call&apos;s arguments costs about
        2.4 ms, because there is little prose to read. A long tool result costs several times a
        short question, because the classifier reads text in 256-token windows.
      </p>
      <p>
        <strong>Conversation length does not.</strong> Per-check latency was flat from the first
        turn of a session to the fifth: a guard that re-read the whole history on every turn would
        get slower as the conversation went on, and this one does not.
      </p>
      <p>
        <strong>Framework and shape barely matter.</strong> Single-agent, independent-agent and
        multi-agent repositories landed within a few milliseconds of each other per check, and so
        did the frameworks. The guard does no framework-specific work on a check.
      </p>

      <InlineCTA
        title="See it on your own agent"
        body="The playground runs AgentFox's checks on text you paste, with no account."
        href="/playground"
        label="Open the playground"
        secondary={{ href: "/benchmark/latency", label: "Latency benchmark" }}
      />

      <h2 id="others">Against other guards, on one machine</h2>
      <p>
        Published latency figures are hard to compare: few vendors publish one, fewer say on what
        hardware, with how long a message or whether the network is included. So we ran the
        others ourselves, on the same 880 messages, the same machine and the same Python.
      </p>
      <p>
        We ran AgentFox at every level. On short messages, its deterministic checks took 6.9 ms
        at the median and its default checks took <strong>58.8 ms</strong>. LLM Guard&apos;s
        prompt-injection scanner took <strong>52.2 ms</strong>, Prompt Guard 2 86M 51.7 ms, Prompt
        Guard 2 22M 23.9 ms, and the Guardrails AI jailbreak validator 99.4 ms. LLM Guard&apos;s
        nine default scanners together took 249 ms, and OpenAI&apos;s hosted moderation API 410
        ms, about 260 ms of it the network.
      </p>
      <p>
        The base-size models are the same speed: AgentFox&apos;s classifier, the one inside LLM
        Guard&apos;s scanner and Prompt Guard 2 86M all take about 50 ms. The difference is what
        surrounds them. AgentFox answers over HTTP and runs its PII, secrets and other checks on
        the same call; LLM Guard&apos;s scanner detects injection and nothing else. The 22M model
        is faster because it is a quarter of the size.
      </p>
      <p>
        On long messages AgentFox does more work on purpose. It reads the first 4,000 characters in
        overlapping windows, where the others stop at 512 tokens, so an injection buried deep in a
        long document is read at all. On a laptop CPU that pushes some long inputs past the 300 ms
        check budget; those checks return without the classifier&apos;s verdict, and say so.
      </p>

      <h2 id="judge">When an LLM judge is in the loop</h2>
      <p>
        An LLM judge is a different order of cost. NVIDIA NeMo Guardrails&apos; self-check rail,
        one gpt-4.1-mini call, took 738 ms at the median on the same messages; AgentFox with its
        judges on every check took 838 ms. Most of that gap is the answer: our judge scores
        three things (an instruction override, data exfiltration, personal data) where NeMo&apos;s
        asks one yes-or-no question.
      </p>
      <p>
        In practice the judge rarely sits on the request path. By default it only runs inline when
        an enforcing rule relies on its answer; otherwise it runs after the response and its
        verdict is still recorded against the same trace.
      </p>

      <h2 id="deploy">Keeping it fast in production</h2>
      <ul>
        <li>
          <strong>Run the gateway beside the agent.</strong> Network is the largest number in any
          hosted guard&apos;s latency. Self-hosted, a check never leaves the machine.
        </li>
        <li>
          <strong>Choose the layer per agent.</strong> Deterministic checks cost single
          milliseconds; turn the classifier on where untrusted text reaches the agent.
        </li>
        <li>
          <strong>Keep the score cache on.</strong> System prompts, tool descriptions and retrieved
          chunks repeat, and a repeated text is scored once.
        </li>
        <li>
          <strong>Keep judges off the hot path</strong> unless a rule needs their answer before the
          action.
        </li>
      </ul>
      <p>
        Everything above, every recorded call and the scripts to rerun it are in{" "}
        <a href="https://github.com/architsharm/agentfox/tree/main/benchmarks/latency">
          benchmarks/latency
        </a>
        .
      </p>
    </>
  );
}

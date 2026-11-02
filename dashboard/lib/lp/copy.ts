/**
 * The words on each landing variant, kept to the minimum. Every number comes
 * from proof.ts and its cited benchmark.
 */

import type { VariantSlug } from "./variants";

export type Stat = { n: string; label: string; vs: string };

export type Copy = {
  h1: [string, string];
  tagline: string;
  scene: { eyebrow: string; title: string; sub: string };
  stats: Stat[];
  uses: { title: string; items: { title: string; line: string }[] };
};

export const COPY: Record<VariantSlug, Copy> = {
  runtime: {
    h1: ["Runtime guardrails,", "not just prompt injection"],
    tagline: "AgentFox checks every tool call before it runs.",
    scene: {
      eyebrow: "How it works",
      title: "Every call checked before it runs",
      sub: "Allowed, sent to a person, or blocked, with the reason logged.",
    },
    stats: [
      { n: "0 / 588", label: "AgentDojo attacks that ran", vs: "LLM Guard: 86" },
      { n: "0", label: "attacks ran with every detector off", vs: "The action is checked, not the wording" },
      { n: "16 ms", label: "per tool call, fully checked", vs: "LLM Guard: 72 ms" },
    ],
    uses: {
      title: "Built for agents that take action",
      items: [
        { title: "Payments and refunds", line: "Amounts stay inside the limits you set." },
        { title: "Databases", line: "No DELETE or UPDATE without a WHERE." },
        { title: "Email, tickets, CRM", line: "Only the tools the agent was granted." },
      ],
    },
  },
  latency: {
    h1: ["All your guardrails", "for the latency of one"],
    tagline: "Five checks in the time one injection scanner takes.",
    scene: {
      eyebrow: "How it works",
      title: "Checked in real time",
      sub: "AgentFox and an LLM check, on the same message, at measured speed.",
    },
    stats: [
      { n: "63 ms", label: "median for five checks", vs: "LLM Guard, injection only: 56 ms" },
      { n: "12×", label: "faster than an LLM check", vs: "NeMo Guardrails: 758 ms" },
      { n: "3 ms", label: "per tool-call check", vs: "Across 109 agent repos" },
    ],
    uses: {
      title: "Built for agents that answer live",
      items: [
        { title: "Voice agents", line: "No pause the caller hears." },
        { title: "Live chat", line: "Every message checked, no visible wait." },
        { title: "In-product copilots", line: "Inline checks instead of offline ones." },
      ],
    },
  },
  production: {
    h1: ["Guardrails that don't block", "your real customers"],
    tagline: "Fewer false blocks, and every new rule tested on past traffic first.",
    scene: {
      eyebrow: "How it works",
      title: "Customers get through. Attacks don't.",
      sub: "Real requests that look odd to a keyword filter go through.",
    },
    stats: [
      { n: "11.5%", label: "harmless look-alikes flagged", vs: "LLM Guard's model: 42.2%" },
      { n: "68%", label: "of real attacks caught", vs: "LLM Guard's model: 32%" },
      { n: "0", label: "of 339 normal tool outputs blocked", vs: "LLM Guard flagged 82" },
    ],
    uses: {
      title: "Built for assistants that serve customers",
      items: [
        { title: "Support at volume", line: "A false block is a customer who didn't get help." },
        { title: "Shopping and booking", line: "Unusual wording isn't an attack." },
        { title: "Guardrails stuck in log-only", line: "Replay rules on past traffic, then enforce." },
      ],
    },
  },
};

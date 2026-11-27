/**
 * The accepted papers, one record each. /research lists them and /research/<slug>
 * gives each its own page, because Google Scholar only reads `citation_*` tags on a
 * page that is about one paper.
 *
 * `abstract` is the text of the PDF in public/papers/, not the submission-system
 * abstract: the two drifted at camera-ready, and the page has to match the file it links.
 */
export type Paper = {
  slug: string;
  /** BibTeX key. */
  key: string;
  title: string;
  authors: string[];
  venue: string;
  host: string;
  when: string;
  year: number;
  abstract: string;
  link?: { href: string; label: string };
};

const AUTHORS = ["Archit Sharma", "Garima Mann"];

export const PAPERS: Paper[] = [
  {
    slug: "no-tier-wins-everywhere",
    key: "sharma2026notier",
    title:
      "No Tier Wins Everywhere: Benchmarking Rules, Classifiers, a Judgment Model and an LLM as Security Detectors for AI Agents",
    authors: AUTHORS,
    venue: "WAITI 2026",
    host: "ACSAC 2026 workshops",
    when: "7 December 2026, Los Angeles",
    year: 2026,
    abstract:
      "Guardrails for AI agents are usually evaluated one detector at a time, on one kind of decision. We compare five kinds of detector on identical rows across eight kinds of security decision: deterministic code, small open classifiers, a hosted judgment model, an LLM judge, and argument-provenance tracking. The corpus combines 21 labelled datasets, 19 of them external, with stored per-row decisions for every applicable detector, 175,816 labelled decisions in total. Code is exact on parsed structure, where the judgment model ranks almost perfectly (AUROC 0.993) but its default threshold produces 36.4% false positives. On injected agent actions, content-based detectors fail (the parser catches 0/45 attacker calls, the judgment model 12/45) and only provenance contains every attack, at a large cost in benign utility. On prompt injection, we cannot distinguish a local open-source classifier from the hosted judgment model on held-out data, although most of those held-out benign prompts are in the classifier's training data. On policy rules, the judgment model wins flat rules and the LLM wins rules that override each other; choosing the better of the two for every rule would reach only 89.0%. On agent trajectories, questions tuned on attacks miss most competence failures. The judgment model's best threshold ranges from 0.38 to 0.95 across decision kinds. We release per-row decisions (aggregates only for the hosted judgment model) and list the evaluation mistakes we made and fixed, each with the error it introduced.",
    link: { href: "https://github.com/architsharm/waiti2026-artifact", label: "Per-row decisions and scripts" },
  },
  {
    slug: "runtime-guardrail-latency",
    key: "sharma2026latency",
    title:
      "What a Runtime Guardrail Costs an Agent Pipeline: A Latency Case Study on Open-Source Agent Repositories",
    authors: AUTHORS,
    venue: "IEEE BigData 2026",
    host: "Trustworthy AI Pipelines workshop",
    when: "December 2026, Phoenix",
    year: 2026,
    abstract:
      "Runtime guardrails check the text an AI agent reads, the tools it calls and the replies it writes. Each check runs on the request path under a deadline, and a guardrail that fails open skips a detector that misses the deadline without raising an error. We measured the latency of an open-source runtime guardrail that we develop, on sessions that its own attack suite generated from 49 agent repositories (17,621 checks), then repeated the study after changes on 109 repositories (40,631 checks). Deterministic checks cost 3.5 ms at the median and 7.7 ms at p95 (engine time). The default layer, a prompt-injection classifier (plus a backstop model before the changes), raised this to 47/234 ms, and to 41/190 ms after the changes on regenerated sessions of the same 49 repositories. Run alone on the same texts, this classifier and three other open ones took 26 to 32 ms at the median. An inline hosted LLM judge cost about a second per check. With one gateway worker on SQLite, p95 at 16 parallel clients was 31.6 s before the changes and 500 ms after, but then a median of 69% of checks (12 to 94% over three rounds) skipped the classifier. We did not test the production configuration. Replaying the 458 skipped checks without a budget made 24 verdicts stricter on the primary classifier's own detections (53 with advisory backstop hits), flagging 14% of the skipped user messages and tool results. The harness, data and scripts will be released.",
  },
  {
    slug: "when-the-guardrail-breaks",
    key: "sharma2026breaks",
    title:
      "When the Guardrail Breaks: Failure Semantics of Open-Source Guardrails for LLM Agents and What They Mean for Control",
    authors: AUTHORS,
    venue: "IEEE BigData 2026",
    host: "Trustworthy and Aligned AI workshop",
    when: "December 2026, Phoenix",
    year: 2026,
    abstract:
      "A guardrail for an LLM agent decides whether a prompt, an output or a tool call may proceed. We ask what it does when its detector raises an error or times out. We coded the shipped defaults of 16 guardrail libraries, gateways, frameworks and agent hooks (open source, except Claude Code's hooks, coded from documentation) in 98 rows at pinned commits, with error and timeout coded separately. All coding was done by LLM agents and no human checked it. We confirmed 27 rows by fault injection; a second LLM-agent run recoded 19 random rows (Cohen's κ = 0.63, 95% interval 0.40 to 0.85), a measure of run-to-run consistency only. On a detector error, 7 systems raise to the caller, 3 block, 5 let the call proceed and 1 mixes both; of the open ones, one is an agent host's hook runner and one is the authors' guardrail. By component, fail-open defaults concentrate in agent hooks, gateways and hub integrations: 7 of 22 NeMo Guardrails integrations and 7 of 52 LiteLLM detector hooks allow on error. We also find unbounded detector paths in 9 systems, a timeout that sets the status code without bounding latency, input checks that run beside the tools they guard, and failed checks labelled as successes. In the authors' guardrail, a raising detector was allowed even under a closed fail mode; we found and fixed this during the study. We recommend declared fail modes, a three-valued verdict, timeouts that bound latency, and failures in the audit record.",
  },
];

export const paperPath = (slug: string) => `/research/${slug}`;
export const paperPdf = (slug: string) => `/papers/${slug}.pdf`;
export const getPaper = (slug: string) => PAPERS.find((p) => p.slug === slug);

/** "Sharma, Archit" for BibTeX, from "Archit Sharma". */
const lastFirst = (name: string) => name.replace(/^(.*) (\S+)$/, "$2, $1");

export function bibtex(p: Paper, url: string): string {
  return [
    `@inproceedings{${p.key},`,
    `  author    = {${p.authors.map(lastFirst).join(" and ")}},`,
    `  title     = {${p.title}},`,
    `  booktitle = {${p.venue}, ${p.host}},`,
    `  year      = {${p.year}},`,
    `  url       = {${url}},`,
    `}`,
  ].join("\n");
}

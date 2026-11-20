# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Engineering and security leads at companies running AI agents in production, mostly customer-facing assistants that call real tools (refunds, orders, account changes, email, data access). They evaluate on the public site first (benchmarks, playground, docs) and adopt self-serve from the CLI or one SDK line.

## Product Purpose
AgentFox is an open-source control plane for AI agents: it discovers every agent, tool and MCP server in a codebase, drafts least-privilege rules from the code, checks each tool call and where its arguments came from at runtime, lets a person approve risky actions, and exports signed evidence. Success is attacks stopped without blocking the real customers the agent is there to help.

## Positioning
Vision (confirmed 2026-11-20): "Agents act. You stay in control." The hero tagline "Guardrails that don't block your real customers" stays as the homepage H1, unchanged; the vision sits above or around it, never replaces it.
Control plane across discover, govern, protect, test and prove; never only tool-call containment. Differentiators: rules drafted from code, observe-first rollout (shadow and replay before enforcing), argument provenance holds, low false blocks on customer language, peer-reviewed results.

## Capabilities and Constraints
- Apache-2.0 core; enterprise source-available. Runs offline with no API key.
- Public header is minimal: one link (Research) + GitHub + theme toggle + Sign in + Docs.
- Every published number is bound to a result file in benchmarks/claims.yaml; numbers are never edited by hand.
- Benchmark pages stay deep; /live and /playground stay.

## Brand Commitments
- Name AgentFox, fox mark, brand crimson accent (--af-brand).
- Voice: plain, specific, no hype words, no em dashes in marketing prose, limits stated next to every claim.
- Examples stay generic (not one test scenario).

## Evidence on Hand
- Benchmarks: /benchmark (security), /benchmark/latency, /live (hourly attacks, unedited).
- Accepted papers: WAITI 2026 (ACSAC workshops), IEEE BigData 2026 x2; Cross-AI Symposium 2026 demo. Listed on /research.
- Absent, never fabricate: customer logos, testimonials, user counts, ratings.

## Product Principles
1. Don't block real users: precision over recall theatre.
2. Observe before enforce.
3. Prove it: every claim has a source, a limit and a rerun command.
4. Do the work for the engineer: inventory and rules come from the code.

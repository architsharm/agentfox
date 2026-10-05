import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { ChainMock } from "@/components/marketing/mocks";
import { GrantLimit } from "@/components/marketing/grant";
import {
  PillarGrid,
  DetectorPipeline,
  DiscoveryMock,
} from "@/components/marketing/visuals";

/**
 * The six pillars, and the five feature sections underneath them.
 *
 * The public page used to sell exactly one idea (a capability grant contains a tool
 * call) and hid the rest of the product behind it. These sections are the rest: the
 * detector stack, containment, discovery, evals and red-teaming, and the audit chain
 * with the compliance mapping on top of it.
 *
 * Presentational only. No state, no effects, no fetching, so every export here stays a
 * server component and the landing page keeps rendering with no client bundle.
 *
 * Image-led on purpose. Every section carries either a real product screenshot in the
 * `.mk-frame` chrome or a React visual built from the same tokens, and the prose around
 * it is capped at two sentences so the picture is what a reader actually takes in.
 *
 * Where every fact on this page came from, so a later editor can re-check rather than
 * guess:
 *
 *   - the six pillars and their questions .... README.md "The six pillars"
 *   - detector registrations ................. src/agentfox/detection/__init__.py
 *   - INJECTION.* entity types ............... src/agentfox/detection/detectors/injection.py
 *   - SECRET.* entity types .................. src/agentfox/detection/detectors/secrets.py
 *   - normalisation views .................... src/agentfox/detection/normalize.py
 *   - per-detector budget, degrade-not-skip .. src/agentfox/detection/pipeline.py
 *   - baseline / tool-containment rule ids ... src/agentfox/policies_data/*.yaml
 *   - capability.* and taint.* verdicts ...... src/agentfox/runtime/enforcement.py
 *   - the provenance ladder .................. src/agentfox/detection/taint.py, README "Commands"
 *   - impact tiers ........................... dashboard/app/glossary/page.tsx
 *   - static-only scanning, TS/JS pass ....... src/agentfox/discovery/repo.py
 *   - OpenAPI onboarding ..................... src/agentfox/discovery/openapi.py
 *   - local session scanning ................. src/agentfox/discovery/sessions.py
 *   - MCP hygiene finding types .............. src/agentfox/registry/service.py
 *   - scorer keys ............................ src/agentfox/evaluation/scorers.py
 *   - adaptive campaign scope ................ src/agentfox/evaluation/adaptive.py
 *   - chain digests and verify() ............. src/agentfox/prove/audit/chain.py
 *   - computed compliance status ............. src/agentfox/prove/compliance/status.py
 *   - control count and framework keys ....... src/agentfox/compliance_data/controls.yaml
 *   - every CLI command shown ................ README.md "Commands"
 *
 * Figures appear only where README.md or app/benchmark/page.tsx already publishes them,
 * and each one carries a source comment at the point of use.
 *
 * Only marketing.css classes and its --mk-* tokens are used. No colour is hardcoded, so
 * light and dark are both correct with no second palette.
 */

/* --- Shared furniture --------------------------------------------------- */

type Item = { label: string; body: ReactNode };

const BODY: CSSProperties = { margin: 0, fontSize: "var(--t-body)" };

/**
 * One half of a split row.
 *
 * `direction: ltr` is reset here because `Split` flips the container to place the
 * visual in the left column without moving it ahead of the heading in the DOM. See
 * the note on `Split`.
 */
function Half({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={className} style={{ direction: "ltr", minWidth: 0 }}>
      {children}
    </div>
  );
}

/**
 * The two-column feature row.
 *
 * `flip` puts the visual in the left column on desktop. It is done by reversing the
 * grid's inline direction rather than by reordering the children, because the columns
 * collapse to one below 900px and a section that opens with a picture and only then
 * says what the picture is of is worse on a phone than on a desktop. So the copy is
 * always first in the DOM, and each half resets `direction` for its own contents.
 */
function Split({
  flip = false,
  wide = false,
  children,
}: {
  flip?: boolean;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={wide ? "mk-split mk-split-wide" : "mk-split"}
      style={flip ? { direction: "rtl" } : undefined}
    >
      {children}
    </div>
  );
}

function Head({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  center?: boolean;
}) {
  return (
    <div className="mk-narrow mk-up">
      <span className="mk-eyebrow">{eyebrow}</span>
      <h2 className="mk-h2" style={{ marginTop: 14 }}>
        {title}
      </h2>
      {children ? (
        <p
          className="mk-body"
          style={{ marginTop: 14 }}
        >
          {children}
        </p>
      ) : null}
    </div>
  );
}

/** Short labelled items: the mono identifier the product actually emits, then one line. */
function Items({ items }: { items: Item[] }) {
  return (
    <div style={{ display: "grid", gap: 13, marginTop: 24 }}>
      {items.map((it) => (
        <div key={it.label} style={{ display: "grid", gap: 3 }}>
          <span className="mk-mono" style={{ color: "var(--mk-accent)", overflowWrap: "anywhere" }}>
            {it.label}
          </span>
          <span className="mk-body" style={{ fontSize: "var(--t-small)" }}>
            {it.body}
          </span>
        </div>
      ))}
    </div>
  );
}

/* --- 1. The six pillars -------------------------------------------------- */

/**
 * The overview. One grid, six cells, and a reader who gives this five seconds should
 * come away knowing the product covers six areas rather than one.
 */
export function Pillars() {
  return (
    <section id="pillars" className="mk-section">
      <div className="mk-wrap">
        <Head eyebrow="The platform" title="Six questions about your agents">
          What is running, what it can reach, what it is allowed to do, what it just did, whether that was tested, and whether you can show the record.
        </Head>

        <div className="mk-up mk-d2" style={{ marginTop: 44 }}>
          <PillarGrid />
        </div>

        <p className="mk-fine mk-up mk-d3" style={{ marginTop: 20 }}>
          The checks on the request itself are written up on{" "}
          <Link href="/how-it-works">how a tool call is handled</Link>.
        </p>
      </div>
    </section>
  );
}

/* --- 2. Runtime guardrails ----------------------------------------------- */

const GUARDRAIL_ITEMS: Item[] = [
  {
    // Rule ids from src/agentfox/policies_data/baseline.yaml.
    label: "injection.direct · injection.indirect",
    body: "Injection in a user message, a retrieved document or a tool result.",
  },
  {
    // Entity types from guardrails/detectors/secrets.py and detectors/pii.py.
    label: "secrets.block · pii.outbound_redact",
    body: "Keys and JWTs are refused; names and card numbers are masked or tokenised.",
  },
  {
    // guardrails/normalize.py: views, not one aggressive rewrite; offsets carried.
    label: "normalisation before detection",
    body: "Zero-width characters, homoglyphs, fullwidth text, base64 and percent-encoding are folded into views every detector reads.",
  },
  {
    // guardrails/pipeline.py: per-detector timeout, total budget, degrade not skip.
    label: "budget, then degrade rather than skip",
    body: "A detector over its budget drops to observe rather than being skipped.",
  },
];

/**
 * Pillar 3. The honest framing is load-bearing: this is the layer the product trusts
 * least, README.md publishes that, and the copy here must not read as a claim of
 * robustness. Containment is the section that follows for exactly that reason.
 */
export function Guardrails() {
  return (
    <section id="guardrails" className="mk-section">
      <div className="mk-wrap">
        <Head eyebrow="Area 3 · Runtime guardrails" title="Detectors read the text. A policy decides">
          Detectors read input, output, retrieved documents and tool results. Detection is
          the layer we trust least.
        </Head>
        <Split wide>
          <Half>
            <Items items={GUARDRAIL_ITEMS} />
            <div
              className="mk-card"
              style={{ marginTop: 26, background: "var(--mk-surface-2)" }}
            >
              <span className="mk-label">What this layer is worth</span>
              <p className="mk-body" style={{ ...BODY, marginTop: 8, fontSize: "var(--t-small)" }}>
                26.7% recall on the held-out injection split with the default detector, 66.7%
                with the opt-in classifier ensemble. An attacker who reads our verdict and retries
                gets 73% of what the default stack catches through within 50 attempts. A speed
                bump, never a defence.
              </p>
              <p style={{ marginTop: 10 }}>
                <Link href="/benchmark" className="mk-btn mk-btn-outline" style={{ padding: "8px 14px" }}>
                  The numbers, and where a competitor beats us
                </Link>
              </p>
            </div>
          </Half>
          <Half className="mk-up mk-d2">
            <DetectorPipeline />
          </Half>
        </Split>
      </div>
    </section>
  );
}

/* --- 3. Containment ------------------------------------------------------ */

const CONTAINMENT_ITEMS: Item[] = [
  {
    // src/agentfox/policies_data/tool-containment.yaml
    label: "taint.irreversible_tool",
    body: "An irreversible tool with arguments from untrusted content stops for a human.",
  },
  {
    label: "capability.denied",
    body: "No grant covers this tool and action. Anything not granted is refused.",
  },
  {
    label: "capability.constraint_violated",
    body: "The grant exists; the call exceeded a limit written into it.",
  },
  {
    label: "cascade.reaches_destructive",
    body: "A call that reaches a destructive tool through its declared trigger graph.",
  },
];

/**
 * Pillar 2, and the argument the whole product rests on: this is what is left when
 * detection has already failed. The two benchmark figures quoted are the ones measured
 * with every detector switched off, which is a total bypass rather than a simulated miss.
 */
export function Containment() {
  return (
    <section id="containment" className="mk-section mk-band">
      <div className="mk-wrap">
        <div className="mk-narrow">
          <span className="mk-eyebrow">Area 2 · Containment</span>
          <h2 className="mk-h2" style={{ marginTop: 12 }}>
            A convinced agent still needs permission
          </h2>
          <p className="mk-lede" style={{ marginTop: 14 }}>
            Each tool has an impact tier, each agent explicit grants, each argument its
            provenance. None of it reads the text that produced the call.
          </p>
        </div>

        {/* The measurement gets the full column. This is the case that defeats the
            obvious objection — "so don't give the agent the tool" — and it only
            works if the reader sees that the agent DOES hold the tool. */}
        <div className="mk-up mk-d2" style={{ marginTop: 32 }}>
          <GrantLimit />
        </div>

        <div className="mk-grid mk-grid-2" style={{ marginTop: 28, gap: 26 }}>
          <div style={{ display: "grid", gap: 10 }}>
            <span className="mk-label">Impact tier, declared per tool</span>
            <div className="mk-row" style={{ gap: 6 }}>
              {/* dashboard/app/glossary/page.tsx, "Impact tier". */}
              <span className="mk-chip mk-chip-go">read</span>
              <span className="mk-chip">write</span>
              <span className="mk-chip mk-chip-hold">high_impact</span>
              <span className="mk-chip mk-chip-stop">irreversible</span>
            </div>
            <span className="mk-label" style={{ marginTop: 6 }}>
              Provenance an argument can carry
            </span>
            <div className="mk-row" style={{ gap: 6 }}>
              {/* README.md "Commands": the --max-taint ladder, worst first at the right. */}
              <span className="mk-chip">none</span>
              <span className="mk-chip">user</span>
              <span className="mk-chip">retrieved</span>
              <span className="mk-chip">tool_result</span>
              <span className="mk-chip">subagent</span>
              <span className="mk-chip">memory</span>
            </div>
          </div>

          <div>
            <Items items={CONTAINMENT_ITEMS} />
          </div>
        </div>

        <p className="mk-fine" style={{ marginTop: 24 }}>
          Containment is only as good as the declarations behind it. A destructive tool
          declared <span className="mk-mono">read</span> is not contained.{" "}
          <Link href="/benchmark">What it measured, with detection switched off &rarr;</Link>
        </p>
      </div>
    </section>
  );
}


/* --- 4. Discovery -------------------------------------------------------- */

const DISCOVERY_ITEMS: Item[] = [
  {
    // README.md "Commands"; behaviour from src/agentfox/discovery/repo.py.
    label: "Committed code",
    body: "Reports what in a repository talks to a model, and which of it is ungoverned.",
  },
  {
    label: "An owner",
    body: "Shadow agents, drift and identity posture. Unregistered traffic raises a shadow_agent finding.",
  },
  {
    // src/agentfox/registry/service.py raises these types.
    label: "Tool servers",
    body: "MCP tool hygiene: tool_poisoning in a tool description, an unpinned_server, schema_drift since the last scan.",
  },
  {
    // src/agentfox/discovery/openapi.py and session_scan.py.
    label: "OpenAPI and local sessions",
    body: "Only the OpenAPI spec is fetched. Local sessions give metadata only, never a prompt or a tool call's arguments.",
  },
];

/**
 * Pillar 1. The claim that matters here is a negative one: this never imports or runs
 * the code it is pointed at, and a scan that understood none of the files says so
 * rather than reporting an absence of findings. Both are in discovery.py's own docstring.
 */
export function Discovery() {
  return (
    <section id="discovery" className="mk-section">
      <div className="mk-wrap">
        <Head
          eyebrow="Area 1 · Discovery and registry"
          title="Find the agents before you govern them"
        >
          It never imports or runs your code, and a scan that read no file it understands
          says exactly that instead of reporting clean.
        </Head>
        <Split wide>
          <Half>
            <Items items={DISCOVERY_ITEMS} />
            <p className="mk-fine" style={{ marginTop: 22 }}>
              The first look at a directory stays on the machine.{" "}
              <Link href="/docs/guides/scan-a-repo">The commands are in the docs.</Link>
            </p>
          </Half>
          <Half className="mk-up mk-d2">
            <DiscoveryMock />
          </Half>
        </Split>

      </div>
    </section>
  );
}

/* --- 5. Evaluation, audit and compliance --------------------------------- */

const ASSURANCE_ITEMS: Item[] = [
  {
    // README.md "Test before you trust"; scorer keys in evaluation/scorers.py.
    label: "A regression gate",
    body: "Scores a suite against its recorded baseline and exits 1 on a regression. Groundedness, safety and tool_trajectory are registered scorers.",
  },
  {
    // evaluation/adaptive.py is explicit that this is configuration regression
    // testing and a dishonest thing to call adversarial robustness. So is this line.
    label: "A red-team run",
    body: "Probes fired at your own agents' grants, then retried in mutated form. A posture delta, not a robustness certificate.",
  },
  {
    // audit/chain.py.
    label: "A check of the record",
    body: "Re-derives the hash chain and exits 1 if it is broken. There is no update or delete path for an audit entry.",
  },
  {
    // compliance/status.py, compliance_data/controls.yaml.
    label: "43 controls, seven frameworks",
    body: "Status is computed from execution data, not a form. A control whose evidence source produces nothing reads not_implemented.",
  },
];

/**
 * Pillars 4, 5 and 6 in one section.
 *
 * They were three, totalling 3,953px. They belong together and they belong short:
 * evaluation, the audit chain and the compliance mapping are the three things a
 * reader cannot judge from a marketing page, because judging them means running
 * them against their own traffic. The page's job here is to say the claims
 * precisely, carry the DRAFT caveat, and get out of the way.
 */
export function Assurance() {
  return (
    <section id="assurance" className="mk-section mk-band">
      <div className="mk-wrap">
        <Head
          eyebrow="Areas 4, 5 and 6"
          title="Test it, record it, and show the record to an auditor"
        >
          Every decision lands in a hash chain, and the compliance status above it is
          computed from that chain rather than from a questionnaire.
        </Head>
        <Split wide>
          <Half>
            <Items items={ASSURANCE_ITEMS} />
            <div
              className="mk-card"
              style={{ marginTop: 26 }}
            >
              <div className="mk-row" style={{ gap: 8 }}>
                <span className="mk-chip mk-chip-hold">Draft mappings</span>
              </div>
              <p className="mk-body" style={{ ...BODY, marginTop: 10, fontSize: "var(--t-small)" }}>
                Produced from framework texts by engineers, not reviewed by compliance counsel.
                Evidence packages label them DRAFT, UNVERIFIED, NOT LEGAL ADVICE.
              </p>
            </div>
          </Half>

          <Half className="mk-up mk-d2">
            <ChainMock />
          </Half>
        </Split>
      </div>
    </section>
  );
}

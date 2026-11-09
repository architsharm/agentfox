import type { CSSProperties } from "react";
import Link from "next/link";
import { WAITLIST_ANCHOR, WAITLIST_ERROR_ID, WaitlistForm } from "@/components/marketing/waitlist";

/*
 * The editions story for the public pages: what is free, what is paid, and what
 * does not exist yet.
 *
 * Server components only. No state, no effects, no fetching, no client directive,
 * so these render on the server and cost nothing at runtime. Only marketing.css
 * classes and its tokens are used; no colour is hardcoded.
 *
 * Every commercial claim below was checked against the repository before it was
 * written. The sources, so a later editor can re-check them rather than guess:
 *
 *   - open core Apache-2.0 ............ LICENSE (Apache License 2.0, full text),
 *                                       README.md "Licence" section
 *   - Enterprise source-available ..... ee/LICENSE (BSL 1.1: production use free
 *                                       for one workspace up to four agents;
 *                                       each version Apache-2.0 after three years)
 *   - no licence key .................. no billing, plan, price or licence-key
 *                                       code exists under src/agentfox/ or ee/.
 *   - runs offline, no API key ........ README.md lines 34-35, and
 *                                       src/agentfox/platform/providers/echo.py
 *   - no telemetry phoning home ....... no AgentFox-owned endpoint appears
 *                                       anywhere in src/agentfox/. The only
 *                                       outbound hosts in config.py are the
 *                                       model and tracing providers the operator
 *                                       configures themselves.
 *   - benchmarks reproducible ......... README.md "Benchmarks, reproducible by
 *                                       anyone", nine scripts under benchmarks/
 *   - stdlib-only verifier ............ ee/src/agentfox_ee/evidence/package.py
 *                                       VERIFIER_SCRIPT, written into every
 *                                       package as verify_chain.py
 *   - mappings ship labelled DRAFT .... ee/src/agentfox_ee/compliance/frameworks.py,
 *                                       ee/src/agentfox_ee/compliance/risk.py
 *   - cloud does not exist yet ........ README.md line 183: single-org
 *                                       multi-tenancy at the session, "not yet a
 *                                       managed multi-region offering", no live
 *                                       IdP/SSO
 *
 * Deliberately absent: prices, SLA numbers, customer counts, logos. None of them
 * exist, so none of them appear.
 */

const SUPPORT_EMAIL = "support@nometria.com";

const SUPPORTED_HREF =
  `mailto:${SUPPORT_EMAIL}` +
  "?subject=Supported%20self-hosted%20deployment";

const REPO_HREF = "https://github.com/architsharm/agentfox";

/* --- Shared furniture --------------------------------------------------- */

const COLUMN: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  minWidth: 0,
};

const ITEM_BODY: CSSProperties = {
  margin: "5px 0 0",
  fontSize: "var(--t-small)",
  lineHeight: 1.5,
};

const ACTION_FOOT: CSSProperties = {
  marginTop: "auto",
  paddingTop: 4,
  display: "grid",
  gap: 10,
  minWidth: 0,
};

/** One labelled line inside an edition column. */
function Item({ label, children }: { label: string; children: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <span className="mk-label">{label}</span>
      <p className="mk-body" style={ITEM_BODY}>
        {children}
      </p>
    </div>
  );
}

/* --- Editions ----------------------------------------------------------- */

export function Editions({
  notice,
  error,
}: {
  /** Set by dashboard/app/api/waitlist/route.ts after a form post. */
  notice?: string;
  error?: string;
} = {}) {
  return (
    <section id="editions" className="mk-section">
      <div className="mk-wrap">
        {/* For screen readers: the route titles below are h3s, under the page's h1. */}
        <h2 className="sr-only">Editions</h2>
        {/* Two routes, not three tiers.
            Three equally-weighted bordered cards look like a paid SaaS ladder,
            which is exactly wrong for a page where nothing is priced. There are
            really only two decisions a visitor makes here — run it yourself, or
            let us run it — and supported rollout is a conversation, not an
            edition. It is a strip underneath. */}
        <div className="ed-routes">
          <div className="ed-route mk-up mk-d1">
            <div className="ed-head">
              <h3 className="mk-h3">Run it yourself</h3>
              <span className="mk-chip mk-chip-go">Free forever</span>
            </div>
            <p className="mk-body">
              Apache-2.0, with no licence key and no limit on agents: enforcement, the detectors and
              the dashboard, running offline (the optional classifier is a one-time download). Compliance, evidence packages, monitoring and access
              checks are AgentFox Enterprise, source-available and free in production for up to four
              agents.{" "}
              <Link href="/docs/quickstart">Install guide</Link>.
            </p>
            <a
              className="mk-btn mk-btn-outline"
              href={REPO_HREF}
              target="_blank"
              rel="noreferrer"
            >
              Read the repository
            </a>
          </div>

          <div className="ed-route ed-route-hosted mk-up mk-d2">
            <div className="ed-head">
              <h3 className="mk-h3">Let us run it</h3>
              <span className="mk-chip mk-chip-accent">Free while in preview</span>
            </div>
            <p className="mk-body">
              AgentFox with Enterprise included, run by us. Sign in to get a workspace.
            </p>
            <ul className="ed-terms">
              <li>No card</li>
              <li>When paid plans arrive, your first 14 days on one are free</li>
              <li>We&apos;ll tell you before anything changes</li>
            </ul>
            <a className="mk-btn mk-btn-primary" href="/login">
              Start free
            </a>
          </div>
        </div>

        {/* Supported rollout: a service conversation, not a third tier. */}
        <div className="ed-support mk-up mk-d3">
          <p>
            <strong>Rolling out to production?</strong> We help with the rollout and prioritise
            your fixes. Not priced yet.
          </p>
          <a className="mk-btn mk-btn-outline" href={SUPPORTED_HREF}>
            Talk to us
          </a>
        </div>

        {/* The waitlist is not gone, it is pointed at the thing that is actually
            unknown. Nobody needs to queue for the product — they can sign in — but
            "tell me before you start charging" is a real request, and it is the one
            this form now collects. */}
        <div id={WAITLIST_ANCHOR} className="mk-notify mk-up mk-d4">
          {notice ? (
            <p className="wl-done" role="status">
              {notice}
            </p>
          ) : (
            <>
              <div>
                <h3 className="mk-h3">Tell me when pricing is announced</h3>
                <p className="mk-body">One email, before any paid plan exists.</p>
                {error ? (
                  <p className="wl-error" role="alert" id={WAITLIST_ERROR_ID}>
                    {error}
                  </p>
                ) : null}
              </div>
              <WaitlistForm invalid={Boolean(error)} />
            </>
          )}
        </div>
      </div>
    </section>
  );
}

/**
 * The open-source promise with a file next to each line, so a reader can check any
 * of the four rather than take them.
 */
export function OpenSourcePromise() {
  return (
    <section className="mk-section-tight">
      <div className="mk-wrap">
        <div className="mk-grid mk-grid-4 mk-up">
          {OSS_FACTS.map((f) => (
            <div
              key={f.label}
              className="mk-card"
              style={{ padding: 20, display: "grid", gap: 6, minWidth: 0 }}
            >
              <span className="mk-label">{f.label}</span>
              <p className="mk-body" style={{ margin: 0, fontSize: "var(--t-small)", lineHeight: 1.5 }}>
                {f.body}
              </p>
              <code
                className="mk-mono"
                style={{ color: "var(--mk-muted)", overflowWrap: "anywhere" }}
              >
                {f.where}
              </code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const OSS_FACTS: { label: string; body: string; where: string }[] = [
  {
    label: "Apache-2.0",
    body: "The full Apache License 2.0, no added terms. It stays that way.",
    where: "LICENSE",
  },
  {
    label: "Offline by default",
    body: "No API key and nothing leaves the machine. The core install ships no model weights; the injection classifier is an optional download.",
    where: "agentfox admin detectors pull",
  },
  {
    label: "No telemetry",
    body: "Nothing calls an AgentFox server. Outbound hosts are the ones you configure.",
    where: "src/agentfox/core/config.py",
  },
  {
    label: "Reproducible",
    body: "Every published figure has a script that regenerates it.",
    where: "benchmarks/",
  },
];

/* --- WhyOpen ------------------------------------------------------------ */

import type { Metadata } from "next";
import Link from "next/link";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { publicPageMetadata, REPO_URL } from "@/lib/site";

export const dynamic = "force-dynamic";

/**
 * SECURITY.md is the authority on how to report and what counts. This page points at
 * it and does not restate the process, because two copies of a disclosure process
 * drift and the copy a researcher finds first is then the wrong one.
 *
 * The rest of the page is the part SECURITY.md does not cover: which security
 * properties the product actually has, each with the file that implements it, and an
 * unhedged statement of what has never been done.
 */
export const metadata: Metadata = publicPageMetadata({
  title: "Security and vulnerability disclosure",
  description:
    "How to report a vulnerability, what is in scope, the properties that hold in code, and what has never been audited or tested by anyone else.",
  path: "/security",
});

const SECURITY_MD = `${REPO_URL}/blob/main/SECURITY.md`;
const ADVISORIES = `${REPO_URL}/security/advisories/new`;
const SRC = `${REPO_URL}/blob/main`;

/** See the note on the same helper in app/privacy/page.tsx: the wrap rule is what
 *  keeps a 44-character unbroken file path from scrolling a 375px screen sideways. */
function Ref({ children }: { children: React.ReactNode }) {
  return (
    <p
      className="mk-mono"
      style={{ color: "var(--mk-muted)", margin: "10px 0 0", overflowWrap: "anywhere" }}
    >
      {children}
    </p>
  );
}

export default function Security() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <span className="mk-eyebrow">Security</span>
              <h1 className="mk-h1" style={{ margin: "18px 0 0" }}>
                Security and <em>disclosure</em></h1>
              <p className="mk-lede" style={{ marginTop: 20 }}>
                How to report a vulnerability, what the code enforces, and what nobody
                outside this project has checked.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Reporting a vulnerability</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The process lives in{" "}
                <a href={SECURITY_MD} target="_blank" rel="noreferrer">
                  SECURITY.md
                </a>{" "}
                in the repository. That file is the authority and this page is not a second
                copy of it: read it before you report, and if this page and that file ever
                disagree, that file is right.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The short version, so you know where you are going: not a public issue.
                Use{" "}
                <a href={ADVISORIES} target="_blank" rel="noreferrer">
                  GitHub&rsquo;s private vulnerability reporting
                </a>{" "}
                on the repository&rsquo;s Security tab, which opens an advisory only the
                maintainers can see. A failing request, a policy file or a short script is
                worth more than a description of one.
              </p>
              <p className="mk-fine" style={{ marginTop: 14 }}>
                SECURITY.md also states the acknowledgement expectation and asks you to say
                whether you plan to publish. Both are there rather than here for the same
                reason.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band mk-reveal">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Scope</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Summarised from SECURITY.md, which is the version that governs.
              </p>

              <div className="mk-grid mk-grid-2" style={{ marginTop: 20 }}>
                <div className="mk-card">
                  <span className="mk-chip mk-chip-go">In scope</span>
                  <p className="mk-body" style={{ margin: "12px 0 0", fontSize: "var(--t-body)" }}>
                    This project&rsquo;s own code: the enforcement path, the policy engine,
                    the audit chain and its verifier, the gateway and its authentication,
                    the tenant isolation in{" "}
                    <span className="mk-mono">src/agentfox/tenancy.py</span>, and the
                    public playground on this deployment.
                  </p>
                  <p className="mk-body" style={{ margin: "12px 0 0", fontSize: "var(--t-body)" }}>
                    Concretely, a vulnerability is: getting an action through that the
                    declarations should have refused, reading or writing another
                    tenant&rsquo;s data, forging or breaking the audit chain without the
                    verifier noticing, escalating a token&rsquo;s permissions, or making the
                    control plane fail open without recording it.
                  </p>
                </div>
                <div className="mk-card">
                  <span className="mk-chip mk-chip-hold">Out of scope</span>
                  <p className="mk-body" style={{ margin: "12px 0 0", fontSize: "var(--t-body)" }}>
                    Two things, both excluded because the project already says so in public
                    and measures them rather than hiding them.
                  </p>
                  <p className="mk-body" style={{ margin: "12px 0 0", fontSize: "var(--t-body)" }}>
                    A prompt injection that a detector misses. Detection here is a speed
                    bump, not a defence, held-out recall is published in the README, and an
                    adaptive attacker gets most caught attacks through eventually.
                  </p>
                  <p className="mk-body" style={{ margin: "12px 0 0", fontSize: "var(--t-body)" }}>
                    An attack that gets through when the declarations are wrong. Containment
                    is only as good as the tool declarations and capability grants behind
                    it. A tool declared read-only that moves money is not contained, and the
                    product says so.
                  </p>
                </div>
              </div>

              <p className="mk-body" style={{ marginTop: 20 }}>
                On the hosted playground specifically, the{" "}
                <Link href="/terms">terms</Link> draw the same line from the other
                direction: attacking the sandboxed agent is the entire point, attacking the
                infrastructure it runs on is not.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-reveal">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Properties you can check in the source</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Three, each with the file that implements it. These are claims about code,
                which means they are falsifiable, which is the only kind worth making.
              </p>

              <h3 className="mk-h3" style={{ marginTop: 34 }}>
                1. Tenant isolation is a property of the session, not of each query
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                The obvious implementation, adding a tenant clause to every query, holds
                until the first person writes a new one and forgets, and the failure mode of
                forgetting is a silent cross-tenant leak that no test catches because the
                test wrote both rows itself. So the filter is attached at the session: a
                hook adds a tenant predicate to every ORM statement, which means a query
                whose author has never heard of the tenancy module is filtered anyway.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Two things make it hold rather than merely exist. With no tenant bound,
                queries resolve to the deployment&rsquo;s configured organisation rather
                than to everything, so a gateway bug that forgets to bind shows a user an
                empty screen instead of another company&rsquo;s data. And a model that
                escapes the filter raises at import time, so the mistake cannot reach a
                running system.
              </p>
              <Ref>
                <a href={`${SRC}/src/agentfox/tenancy.py`} target="_blank" rel="noreferrer">
                  src/agentfox/tenancy.py
                </a>
                :15-24, 35-38; src/agentfox/models.py:1669-1688
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The playground rides on exactly this. A sandbox is a tenant whose{" "}
                <span className="mk-mono">org_id</span> is its own id, so one visitor is
                separated from another by the same mechanism that separates two paying
                customers, with no playground-specific filter for anyone to forget.
              </p>
              <Ref>src/agentfox/gateway/playground_sessions.py:8-13</Ref>

              <h3 className="mk-h3" style={{ marginTop: 34 }}>
                2. The audit log is a hash chain, and the verifier is a pure function
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                Immutable in most products means nobody built a DELETE endpoint. Here each
                entry&rsquo;s digest covers its sequence number, timestamp, action, payload
                digest and the previous entry&rsquo;s digest, with periodic checkpoints
                signed by a key held outside the application database.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The verifier detects mutation, deletion, insertion, reordering and
                checkpoint forgery, and it runs over exported rows with no database access
                and no shared state. That last part is what makes it worth anything: a third
                party can run it against an evidence package without access to our systems,
                so you do not have to take our word for the result. There is also no update
                or delete path for an audit entry anywhere in the codebase.
              </p>
              <Ref>
                <a href={`${SRC}/src/agentfox/audit/chain.py`} target="_blank" rel="noreferrer">
                  src/agentfox/audit/chain.py
                </a>
                :1-20, 56-64, 298-312
              </Ref>

              <h3 className="mk-h3" style={{ marginTop: 34 }}>
                3. Four controls cannot be configured to fail open
              </h3>
              <p className="mk-body" style={{ marginTop: 10 }}>
                A control that fails open silently is indistinguishable from a working one:
                the same traffic flows, the same 200s come back, and the dashboard is green
                because the detector that would have raised the finding is the one that is
                down. This codebase&rsquo;s position is that fail-open is legitimate and has
                to be visible, bounded, and impossible for some controls.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                These four are the impossible ones. Their failure mode is a disclosure
                rather than an outage, so declaring one of them open raises in the
                constructor, not as a warning at runtime, because a setting that can be
                changed under pressure at three in the morning is not a guarantee.
              </p>
              <div className="mk-row" style={{ marginTop: 16 }}>
                <span className="mk-chip mk-chip-accent">tenant_isolation</span>
                <span className="mk-chip mk-chip-accent">entitlement_filter</span>
                <span className="mk-chip mk-chip-accent">data_access_scope</span>
                <span className="mk-chip mk-chip-accent">audit_chain</span>
              </div>
              <Ref>
                <a
                  href={`${SRC}/src/agentfox/availability.py`}
                  target="_blank"
                  rel="noreferrer"
                >
                  src/agentfox/availability.py
                </a>
                :18-30, 55-64, 87-95
              </Ref>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Everything else can fail open, and the default detector fail mode is open.
                When it happens, the request that ran without a control writes a degradation
                record, and open converts to closed after a declared time or share of
                traffic, because a control that has been open for an hour is not degraded,
                it is absent.
              </p>
              <Ref>src/agentfox/config.py:148-149; src/agentfox/availability.py:21-26</Ref>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band mk-reveal">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <span className="mk-eyebrow">Maturity</span>
              <h2 className="mk-h2" style={{ marginTop: 16 }}>
                Nobody outside this project has checked any of it
              </h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                  There has been no third-party security audit. There is no SOC 2 report,
                  Type I or Type II. There has been no penetration test by anyone. There is
                  no ISO 27001 certification and no paid bug bounty. None of those things
                  have happened, and it would be easy to imply otherwise with a badge and a
                  vague sentence.
                </p>
                <p className="mk-body" style={{ marginTop: 14 }}>
                  What exists instead: the source, the tests, a verifier you can run yourself
                  against exported evidence, and published numbers for the detection layer
                  including the ones that are unflattering. That is a weaker assurance than an
                  audit and it is a different kind of thing, not a substitute. If you are
                  evaluating this for something that matters, read the code, run the
                  verifier, and price in that it has not been reviewed by anyone but its
                  maintainer.
                </p>
              <p className="mk-body" style={{ marginTop: 22 }}>
                The playground has a stated limit worth knowing before you test it: its rate
                limiter is per process, so on a serverless deployment it bounds one
                instance&rsquo;s share of abuse and does not bound a client spread across
                instances. The sandbox lifetime and the concurrent-sandbox cap are what
                actually bound the cost, and both are deployment-wide. That is written down
                in the module rather than implied.
              </p>
              <Ref>src/agentfox/gateway/playground_sessions.py:371-379</Ref>
              <p className="mk-fine" style={{ marginTop: 26 }}>
                Also here: <Link href="/privacy">privacy</Link>,{" "}
                <Link href="/terms">terms</Link>, <Link href="/legal">legal</Link>.
              </p>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}

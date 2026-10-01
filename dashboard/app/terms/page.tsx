import type { Metadata } from "next";
import Link from "next/link";
import { MarketingNav } from "@/components/marketing/nav";
import { Footer } from "@/components/marketing/sections";
import { publicPageMetadata, REPO_URL, SUPPORT_EMAIL } from "@/lib/site";

export const dynamic = "force-dynamic";

/**
 * Terms for the hosted service at this domain, and only that.
 *
 * The single most important paragraph is the one that says these terms do not touch
 * the Apache-2.0 grant in LICENSE. An open-source project that quietly narrows its
 * own licence in a terms page has taken back the thing people came for, and the
 * ordering here is deliberate: that clause is above everything else.
 */
export const metadata: Metadata = publicPageMetadata({
  title: "Terms of service",
  description:
    "Terms for the hosted AgentFox service: as-is, no SLA, a shared playground that gets reset, and nothing that narrows the Apache-2.0 licence.",
  path: "/terms",
});

const LICENCE_URL = `${REPO_URL}/blob/main/LICENSE`;

/** A governing-law clause nobody has chosen yet reads as a placeholder, not a fact. */
const GOVERNING_LAW = "[jurisdiction to be set by the maintainer]";

export default function Terms() {
  return (
    <div className="mk">
      <MarketingNav />
      <main>
        <section className="mk-section mk-page-hero mk-ink-act">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <span className="mk-eyebrow">Terms</span>
              <h1 className="mk-h1" style={{ margin: "18px 0 0" }}>
                Terms of service</h1>
              <p className="mk-lede" style={{ marginTop: 20 }}>
                These cover the hosted playground and dashboard. They do not narrow
                the Apache-2.0 licence.
              </p>
              <p className="mk-fine" style={{ marginTop: 16 }}>
                Last updated 24 September 2026.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <div className="mk-card mk-card-raised">
                <span className="mk-eyebrow">Read this first</span>
                <h2 className="mk-h2" style={{ marginTop: 16 }}>
                  Nothing here narrows the licence</h2>
                <p className="mk-body" style={{ marginTop: 14 }}>
                  The AgentFox software is licensed under the{" "}
                  <a href={LICENCE_URL} target="_blank" rel="noreferrer">
                    Apache License 2.0
                  </a>
                  , in the <span className="mk-mono">LICENSE</span> file at the root of the
                  repository. That licence is the whole of your rights to the software:
                  to use it, copy it, modify it, run it commercially, and distribute your
                  changes, on its own terms and subject only to its own conditions.
                </p>
                <p className="mk-body" style={{ marginTop: 14 }}>
                  No sentence on this page restricts, conditions or withdraws any right
                  Apache-2.0 grants you, and none is intended to. If anything here appears
                  to conflict with the licence where the licence applies, the licence wins
                  and the conflicting sentence should be treated as an error and reported.
                  These terms reach only the hosted service: the machines, the shared
                  database and the demonstration environment we operate. Take the software
                  and run it yourself and you owe us no agreement at all.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Provided as-is</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The hosted service is provided as-is and as-available, with no warranty of
                any kind, express or implied, including any implied warranty of
                merchantability, fitness for a particular purpose, or non-infringement. To
                the fullest extent the law allows, the maintainer is not liable for any
                direct, indirect, incidental, special, consequential or exemplary damages
                arising out of your use of the hosted service, including lost profits, lost
                data or business interruption.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                There is no service level agreement. There is no uptime commitment, no
                support commitment on this tier, no response time and no credit for an
                outage. This is a demonstration operated by one person.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Do not use the hosted service to govern production agents, and do not rely
                on anything it stores as your record of anything. It is here so you can see
                the product work before you decide to run it. Running it yourself is the
                supported way to use AgentFox for real, and it costs nothing.
              </p>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>
                The playground is shared and temporary
              </h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Your playground sandbox is isolated from everyone else&rsquo;s, but it runs
                on shared infrastructure with a deliberately short life. It is deleted
                after thirty minutes of inactivity, and it can be deleted sooner when the
                deployment is at its concurrent-sandbox cap. The whole playground can be
                reset, changed or removed at any time without notice.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Two consequences worth stating plainly. Nothing in a sandbox is durable, so
                do not put anything in one that you would mind losing in the next half
                hour. And the sandbox id in your URL is the only credential protecting it,
                so anyone you send the link to can read it.
              </p>
              <p className="mk-fine" style={{ marginTop: 14 }}>
                The timings and the cap, and the code that enforces them, are described on
                the <Link href="/privacy">privacy page</Link>.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Acceptable use</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                This is a security product, so the usual template wording would be actively
                misleading. The line is between the target and the infrastructure.
              </p>

              <div className="mk-grid mk-grid-2" style={{ marginTop: 20 }}>
                <div className="mk-card">
                  <span className="mk-chip mk-chip-go">Encouraged</span>
                  <p className="mk-body" style={{ margin: "12px 0 0", fontSize: "var(--t-body)" }}>
                    Attack the sandboxed agent as hard as you like. Prompt injection,
                    indirect injection through the document you are given to edit,
                    multi-turn payload splitting, obfuscation, jailbreaks, attempts to make
                    it call a tool it was never granted: all of that is what the playground
                    is for. Finding a way through is the point, and if you find one, we
                    want the report.
                  </p>
                </div>
                <div className="mk-card">
                  <span className="mk-chip mk-chip-stop">Not allowed</span>
                  <p className="mk-body" style={{ margin: "12px 0 0", fontSize: "var(--t-body)" }}>
                    Attacking the infrastructure rather than the target. Do not attempt to
                    reach another tenant&rsquo;s or another visitor&rsquo;s data, guess or
                    enumerate sandbox ids, escalate a token&rsquo;s permissions, break out
                    of the sandbox into the host or the database, or run denial of service,
                    volumetric load or automated scanning against this deployment.
                  </p>
                </div>
              </div>

              <p className="mk-body" style={{ marginTop: 20 }}>
                Also not allowed, and this one is not a technical boundary but a
                straightforward one: do not use the hosted service as a staging post for an
                attack on anyone else, and do not use it to generate, store or route
                content that is unlawful where you are or where it lands. Do not upload
                other people&rsquo;s personal data, credentials or confidential material
                into a playground sandbox. It is a public demonstration, not a vault, and
                you have no reason to need to.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                If you think you have found a way through the infrastructure boundary
                rather than the sandbox one, stop, and report it. Reporting it is the
                supported path, and it is described on the{" "}
                <Link href="/security">security page</Link>. Testing only far enough to
                confirm a finding, and then stopping, is welcome. Continuing past that
                point is not.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Accounts and sandboxes that breach any of this can be suspended or removed
                without notice. Rate limits apply to the playground and are not a challenge
                to be routed around.
              </p>
            </div>
          </div>
        </section>

        <section className="mk-section mk-band">
          <div className="mk-wrap">
            <div className="mk-narrow">
              <h2 className="mk-h2">Accounts</h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                Signing in with GitHub creates an account and an organisation you own. You
                are responsible for what happens under it and for the repositories you
                choose to connect. Connect a repository only if you are entitled to, and
                revoke the authorisation in your GitHub settings when you are done: that
                takes effect at GitHub&rsquo;s end immediately.
              </p>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>
                Changes, and ending the service
              </h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                The hosted service can be changed, restricted, suspended or discontinued at
                any time, for any reason, with or without notice, in whole or for any one
                account. These terms can change too; the date at the top is when they last
                did, and continuing to use the site after a change is how you accept it.
                Material changes will be noted in the repository, which has a public
                history you can read rather than a notice you have to trust.
              </p>
              <p className="mk-body" style={{ marginTop: 14 }}>
                None of this can take the software away from you. If the hosted service is
                switched off tomorrow, the Apache-2.0 grant is unaffected and the
                repository is still there.
              </p>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>
                Governing law
              </h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                These terms are governed by the laws of {GOVERNING_LAW}, and the courts of{" "}
                {GOVERNING_LAW} have exclusive jurisdiction over any dispute arising from
                them.
              </p>
              <p className="mk-fine" style={{ marginTop: 12 }}>
                That placeholder is real and unfilled. It is left visible rather than
                guessed at, because naming a jurisdiction we have not chosen would be the
                sort of decorative accuracy this project exists to avoid.
              </p>

              <h2 className="mk-h2" style={{ marginTop: 48 }}>
                Contact
              </h2>
              <p className="mk-body" style={{ marginTop: 14 }}>
                <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>. Security reports
                go somewhere else, and the route is on the{" "}
                <Link href="/security">security page</Link>.
              </p>
              <p className="mk-fine" style={{ marginTop: 26 }}>
                Also here: <Link href="/privacy">privacy</Link>,{" "}
                <Link href="/security">security</Link>, <Link href="/legal">legal</Link>.
              </p>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}

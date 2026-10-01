import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Audit trail for agent decisions",
  description:
    "Every time a call is allowed, and every time it is blocked. You can check the export without our code.",
  path: "/evidence",
});

const RECORD = [
  { field: "agent + identity", what: "Who acted, and on whose behalf." },
  { field: "surface", what: "Where the content entered or left." },
  { field: "provenance", what: "Where each argument came from, per argument." },
  { field: "rules_fired", what: "Which rules matched, and what each decided." },
  { field: "degraded", what: "Any detector that ran out of budget on this call." },
  { field: "policy version", what: "The exact rule set in force at that moment." },
  { field: "effective_verdict", what: "What would have happened, when running in observe." },
  { field: "prev_hash", what: "The link that makes a later deletion visible." },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Audit trail"
      title={["An audit trail", "you can check"]}
      lede="Every time a call is allowed, and every time it is blocked. The export includes a verifier that does not use our code."
      docs="/docs/evidence"
      challenge={
        <p>
          If the only proof a control ran is a row in a database the vendor also
          controls, an auditor has to take the vendor&rsquo;s word for it.
        </p>
      }
      feature={{
        title: "What one decision record holds",
        lede: "A verdict and a timestamp are not enough to reconstruct a decision a year later.",
        body: (
          <div className="rec-grid mk-stagger">
            {RECORD.map((r) => (
              <div key={r.field} className="rec">
                <code>{r.field}</code>
                <p>{r.what}</p>
              </div>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "One record per decision, with what decided it",
          body: (
            <p>
              Not just the verdict: the agent, the identity behind it, the surface, where
              each argument came from, which rules fired, which detectors were degraded,
              and the policy version in force at that moment. Reconstructing a decision
              later needs all of it.
            </p>
          ),
        },
        {
          title: "Chained, so a deletion is visible",
          body: (
            <p>
              Each record carries the hash of the one before it. Altering or removing an
              entry breaks the chain from that point on, which turns quiet tampering into
              a loud verification failure.
            </p>
          ),
        },
        {
          title: "Export a package that travels",
          body: (
            <p>
              An evidence package is the records, the policy that produced them, and the
              versions of everything that took part, bundled for a date range and a scope.
            </p>
          ),
        },
        {
          title: "Verified by a script that does not import us",
          body: (
            <p>
              The package ships with a standard-library-only verifier. An auditor runs it
              on their own machine against the bundle, and it recomputes the chain without
              any of our code in the room. That is the difference between evidence and a
              claim.
            </p>
          ),
        },
        {
          title: "Changes to the policy are recorded too",
          body: (
            <p>
              Operator actions — a policy switched to observe, an agent un-quarantined —
              go into their own chain. A control plane that recorded everything except
              changes to itself would be recording the wrong thing.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What the chain does not prove",
        body: (
          <p>
            A hash chain proves the record has not been altered since it was written. It
            does not prove the record was true when written, and anyone who can write to
            the database before a decision is recorded is inside the boundary. There is no
            external timestamping authority and no third party has audited any of this —{" "}
            <a href="/security">/security</a> says so at more length.
          </p>
        ) }}
      related={["/frameworks", "/runtime", "/discovery"]}
    />
  );
}

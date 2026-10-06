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
      lede="Every allow and every block. The export includes a verifier that does not use our code."
      docs="/docs/guides/audit-evidence"
      challenge={
        <p>If the only proof is a row in the vendor&rsquo;s database, the auditor has to take their word for it.</p>
      }
      feature={{
        title: "What one decision record holds",
        lede: "A verdict and a timestamp are not enough a year later.",
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
          title: "Each record points at the one before it",
          body: <p>Change or delete an entry and the chain breaks from there. That is the check.</p>,
        },
        {
          title: "The verifier does not import our code",
          body: <p>It ships in the export. An auditor runs it on their own machine.</p>,
        },
        {
          title: "Changes to the policy are recorded too",
          body: <p>Switching a pack to observe, or taking an agent out of quarantine, goes in its own chain.</p>,
        },
      ]}
      gaps={{
        title: "What the chain does not prove",
        body: (
          <p>
            It proves the record was not changed after it was written. It does not prove
            the record was true when it was written.{" "}
            <a href="/security">Security</a> says what else has not been checked.
          </p>
        ) }}
      related={["/frameworks", "/runtime", "/discovery"]}
    />
  );
}

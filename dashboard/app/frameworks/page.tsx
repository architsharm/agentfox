import type { Metadata } from "next";

import { CapabilityPage } from "@/components/marketing/capability";
import { publicPageMetadata } from "@/lib/site";

export const metadata: Metadata = publicPageMetadata({
  title: "Compliance: EU AI Act, NIST, OWASP, ATLAS",
  description:
    "EU AI Act, ISO 42001, NIST, OWASP and MITRE ATLAS. 43 controls, scored from what the agent did, not from a form.",
  path: "/frameworks",
});

/**
 * Counted from `compliance_data/controls.yaml` rather than typed. The four
 * at 43 are the frameworks every control maps to; the three below it are
 * threat catalogues, which cover the attack surface rather than the
 * management system, so a lower number is the right number and not a gap.
 */
const FRAMEWORKS = [
  { key: "eu-ai-act", name: "EU AI Act", n: 43, what: "High-risk obligations, including Art. 12 logging and Art. 14 oversight" },
  { key: "iso-42001", name: "ISO/IEC 42001", n: 43, what: "The AI management system standard" },
  { key: "nist-ai-rmf", name: "NIST AI RMF", n: 43, what: "Govern, map, measure, manage" },
  { key: "soc2", name: "SOC 2", n: 43, what: "The trust services criteria an auditor already knows" },
  { key: "owasp-llm", name: "OWASP LLM Top 10", n: 22, what: "The attack catalogue for language models" },
  { key: "owasp-agentic", name: "OWASP Agentic", n: 19, what: "Threats specific to agents that act" },
  { key: "mitre-atlas", name: "MITRE ATLAS", n: 9, what: "Adversary tactics against ML systems" },
] as const;

export default function Page() {
  return (
    <CapabilityPage
      kicker="Compliance"
      title={["EU AI Act, NIST,", "OWASP and ATLAS"]}
      lede="43 controls. You meet one because of what the agent did, not because someone filled in a form."
      docs="/docs/compliance"
      challenge={
        <p>
          AI compliance is usually a document describing controls someone believes are
          in place. Nobody notices the gap between the document and the running system
          until there is an incident.
        </p>
      }
      feature={{
        title: "Seven frameworks, 43 controls",
        lede: "One control set mapped across all of them, so you evidence each control once.",
        body: (
          <div className="fw-grid mk-stagger">
            {FRAMEWORKS.map((f) => (
              <div key={f.key} className="fw">
                <div className="fw-head">
                  <b>{f.name}</b>
                  <span>{f.n}</span>
                </div>
                <span className="fw-bar" aria-hidden>
                  <i style={{ width: `${(f.n / 43) * 100}%` }} />
                </span>
                <p>{f.what}</p>
              </div>
            ))}
          </div>
        ) }}
      steps={[
        {
          title: "Seven frameworks, one control set",
          body: (
            <p>
              EU AI Act, ISO 42001, NIST AI RMF, SOC 2, OWASP LLM Top 10, OWASP Agentic
              and MITRE ATLAS. 43 controls, each mapped to the others, so a control
              satisfied for one framework is not re-evidenced by hand for the next.
            </p>
          ),
        },
        {
          title: "Status computed, not asserted",
          body: (
            <p>
              A control&rsquo;s standing comes from telemetry — did the rule exist, did
              it fire, was the detector degraded, is the chain intact. Nobody ticks a box,
              which also means nobody can tick a box.
            </p>
          ),
        },
        {
          title: "A pack for high-risk systems",
          body: (
            <p>
              The EU AI Act pack is policy, not prose: human oversight under Article 14,
              logging under Article 12 and the rest expressed as rules that fire on real
              traffic and land in the same record as everything else.
            </p>
          ),
        },
        {
          title: "Export it and let someone else check",
          body: (
            <p>
              Compliance output is an evidence package like any other — verifiable with a
              script that does not import our code. A framework mapping nobody can check
              independently is a mapping nobody should accept.
            </p>
          ),
        },
      ]}
      gaps={{
        title: "What this is not",
        body: (
          <p>
            It is not a certification, and nothing here has been reviewed by an auditor,
            a notified body or a regulator. A mapping is our reading of a framework, and
            a reading can be wrong. Treat it as a head start on the evidence an assessor
            will ask for, not as the assessment.
          </p>
        ) }}
      related={["/evidence", "/runtime", "/product"]}
    />
  );
}

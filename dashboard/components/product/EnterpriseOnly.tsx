import Link from "next/link";
import type { Feature } from "@/lib/product/edition";

const WHAT: Record<Feature, { title: string; text: string }> = {
  compliance: {
    title: "Compliance is part of AgentFox Enterprise",
    text: "Control status against EU AI Act, ISO 42001, SOC 2 and NIST AI RMF, computed from your traffic, with reviews, sign-off, a risk register and the board view.",
  },
  evidence: {
    title: "Evidence packages are part of AgentFox Enterprise",
    text: "A signed package an auditor can verify without you: decisions, findings and control status for a period, with its own verifier. The audit log and its chain check stay here.",
  },
  monitoring: {
    title: "Monitoring is part of AgentFox Enterprise",
    text: "Re-check connected repositories, MCP servers and APIs on a schedule and on every push, and get Slack alerts when something new appears.",
  },
  access_checks: {
    title: "Access checks are part of AgentFox Enterprise",
    text: "Ask your own access control (an RBAC service, OPA or Cedar) about the person an agent acts for, before the tool call runs.",
  },
};

/** What a page would show, and where it comes from, when this deployment does not have it. */
export function EnterpriseOnly({ feature }: { feature: Feature }) {
  const w = WHAT[feature];
  return (
    <div className="k-card">
      <div className="k-card-body">
        <h3 style={{ marginTop: 0 }}>{w.title}</h3>
        <p className="muted">{w.text}</p>
        <p className="muted small">
          It is included on AgentFox Cloud. To self-host it, install the enterprise package (`ee/` in the repository,
          source-available) alongside the open core.
        </p>
        <div className="k-pills" style={{ gap: 8 }}>
          <a className="k-btn" href="https://github.com/architsharm/agentfox/tree/main/ee" target="_blank" rel="noreferrer">
            About AgentFox Enterprise
          </a>
          <Link className="k-btn-ghost" href="/app">
            Back to Home
          </Link>
        </div>
      </div>
    </div>
  );
}

import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, apiErrorProps } from "@/lib/api";
import { ApiDown, InfoTip, InventoryStrip, Panel, Stat, ts } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";
import { Explainer } from "@/components/Explainer";
import { Modal } from "@/components/Modal";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Agents",
  "The register of every AI agent in this workspace.",
);

export const dynamic = "force-dynamic";

export default async function Agents({
  searchParams,
}: {
  searchParams: Promise<{ review_error?: string }>;
}) {
  const { review_error } = await searchParams;
  let agents: any, shadow: any;
  try {
    [agents, shadow] = await Promise.all([
      api("/api/agents"),
      api("/api/discovery/shadow"),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Agents</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const inv = agents.inventory;
  const drafts = agents.agents.filter((a: any) => a.status === "draft");

  // A repo scan registers one "agent" per directory with governable code in it,
  // including test suites and utility scripts — those aren't things that talk to
  // customers, and listing them next to real production agents with no distinction
  // makes it impossible to tell which of N rows is the one that actually matters.
  const looksLikeTestOrScript = (slug: string) => /(^|-)(tests?|specs?|scripts?|examples?|demo|fixtures?)($|-)/i.test(slug);
  const realAgents = agents.agents.filter((a: any) => !looksLikeTestOrScript(a.slug));
  const testLikeAgents = agents.agents.filter((a: any) => looksLikeTestOrScript(a.slug));

  return (
    <>
      <PageHeader
        title="Agent registry"
        sub="Every agent, its owner and risk tier, and the models and tools it actually uses — derived from traces, not from a form."
        action={<RegisterAgentModal idPrefix="header" />}
      />

      {/* One row, not two.
 
          This was a .cards grid holding the two problem numbers, above a separate
          InventoryStrip holding the other four — so a page with one unregistered
          agent showed two enormous tiles stretched across the full 1010px (the
          grid is auto-fit, and two items share the whole width between them) and
          then a second, denser row of statistics directly underneath. Two
          treatments of the same kind of thing, stacked.
 
          The tile treatment was earning its loudness on the Overview, where
          nothing else says "look at this". Here the "Unregistered agents" table
          is immediately below and does exactly that, so the tiles were shouting a
          heading that the next element already carries. One strip, with tone on
          the two entries that are problems, and the section below does the rest. */}
      <InventoryStrip
        items={[
          { n: inv.agents, label: "agents", href: "/app/agents" },
          { n: inv.registered, label: "registered", href: "/app/agents" },
          {
            n: inv.shadow,
            label: "unregistered",
            href: "#unregistered",
            ...(inv.shadow ? { tone: "bad" as const } : {}),
          },
          {
            n: inv.unowned,
            label: "without an owner",
            href: "/app/agents",
            ...(inv.unowned ? { tone: "warn" as const } : {}),
          },
          { n: inv.tools, label: "tools", href: "#tools" },
          { n: inv.lineage_edges, label: "lineage edges", href: "/app/traces" },
        ]}
      />

      {review_error && <div className="error">{review_error}</div>}

      {drafts.length > 0 && (
        <>
          <h2>Pending review</h2>
          <Panel
            title="Proposed by a repo scan"
            note="inert until approved"
          >
            <table>
              <thead>
                <tr>
                  <th>agent</th>
                  <th>purpose</th>
                  <th>framework</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((a: any) => (
                  <tr key={a.id}>
                    <td className="mono">{a.slug}</td>
                    <td className="small wrap muted" style={{ maxWidth: 360 }}>
                      {a.purpose || "—"}
                    </td>
                    <td className="small muted">{a.framework || "—"}</td>
                    <td>
                      <div className="review-actions">
                        <form action={`/api/agents/${a.id}/approve`} method="POST">
                          <button type="submit" className="btn-approve">
                            Approve
                          </button>
                        </form>
                        <form action={`/api/agents/${a.id}/reject`} method="POST">
                          <button type="submit" className="btn-reject">
                            Reject
                          </button>
                        </form>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}

      {shadow.shadow_agents.length > 0 && (
        <>
          <h2 id="unregistered">Unregistered agents</h2>
          <Panel
            title="Observed but never registered"
            note="detected from traffic, not from a form"
          >
            <table>
              <thead>
                <tr>
                  <th>agent</th>
                  <th>environment</th>
                  <th className="num">calls</th>
                  <th>models</th>
                  <th>framework</th>
                  <th>first seen</th>
                </tr>
              </thead>
              <tbody>
                {shadow.shadow_agents.map((s: any) => (
                  <tr key={s.slug}>
                    <td className="mono">{s.slug}</td>
                    <td className="small">{s.environment}</td>
                    <td className="num">{s.calls}</td>
                    <td className="small muted">{s.models.join(", ") || "—"}</td>
                    <td className="small muted">{s.framework || "—"}</td>
                    <td className="small muted">{ts(s.first_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}

      <h2>All agents</h2>
      {realAgents.length === 0 ? (
        // Muted text and no way forward was the whole state a new workspace got
        // here. Both routes into the registry belong in it, because which one
        // applies depends on where the agent lives, not on which is preferred.
        <div className="hero empty" style={{ marginBottom: 8 }}>
          <div className="hero-title">
            {agents.agents.length === 0
              ? "No agents registered yet"
              : "Nothing here looks like a production agent yet"}
          </div>
          <p>
            {agents.agents.length === 0
              ? "The list of agents you are accountable for."
              : "Everything found so far looks like tests, scripts or examples — listed further down."}
          </p>
          <p className="small muted">
            Two ways in.{" "}
            <InfoTip text="Connecting a repository finds the agents already in your code and proposes them for review. Registering by hand is for an agent that does not live in a repo you can connect." />
          </p>
          <div className="row" style={{ marginTop: 14 }}>
            <Link href="/app/start?tab=connect" className="btn-scan">
              Connect a repo
            </Link>
            <RegisterAgentModal idPrefix="empty" />
          </div>
        </div>
      ) : (
        <div className="panel scroll-x">
          <table>
            <thead>
              <tr>
                <th>agent</th>
                <th>purpose</th>
                <th>owner</th>
                <th>env</th>
                <th>risk</th>
                <th>framework</th>
                <th>
                  last seen
                  <InfoTip text="Timestamp of the most recent traced call from this agent. '—' means no traffic has been recorded for it yet — not that something is broken." />
                </th>
              </tr>
            </thead>
            <tbody>
              {realAgents.map((a: any) => (
                <tr key={a.id}>
                  <td>
                    <Link href={`/app/agents/${a.slug}`}>{a.name || a.slug}</Link>
                    {a.name && <div className="mono small muted">{a.slug}</div>}
                    {a.status === "shadow" && <div><span className="tag bad">unregistered</span></div>}
                    {a.status === "draft" && <div><span className="tag warn">draft</span></div>}
                    {a.is_seed && (
                      <div>
                        <span className="tag" title="Created by `agentfox admin seed` for demo purposes — not a real registration.">
                          sample data
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="small wrap muted" style={{ maxWidth: 320 }}>
                    {a.purpose || "—"}
                  </td>
                  <td className="small">
                    {a.owner_email || (
                      <Link href={`/app/agents/${a.slug}`} className="tag warn">
                        unowned — assign
                      </Link>
                    )}
                  </td>
                  <td className="small">{a.environment}</td>
                  <td>
                    <span className={`tag ${a.risk_tier === "high" || a.risk_tier === "prohibited" ? "bad" : ""}`}>
                      {a.risk_tier}
                    </span>
                  </td>
                  <td className="small muted">{a.framework || "—"}</td>
                  <td className="small muted">{ts(a.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {testLikeAgents.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary className="small muted" style={{ cursor: "pointer" }}>
            {testLikeAgents.length} more that look like tests, scripts or examples
          </summary>
          <div className="panel scroll-x" style={{ marginTop: 10 }}>
            <table>
              <thead>
                <tr><th>agent</th><th>owner</th><th>env</th><th>framework</th><th>last seen</th></tr>
              </thead>
              <tbody>
                {testLikeAgents.map((a: any) => (
                  <tr key={a.id}>
                    <td><Link href={`/app/agents/${a.slug}`} className="mono small">{a.slug}</Link></td>
                    <td className="small muted">{a.owner_email || "unowned"}</td>
                    <td className="small muted">{a.environment}</td>
                    <td className="small muted">{a.framework || "—"}</td>
                    <td className="small muted">{ts(a.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      <CapabilityGrants />
    </>
  );
}

/**
 * Half of containment ships working, is used on every governed tool call, and has
 * no screen anywhere in the dashboard. A reader of this page can see which tools an
 * agent *uses* and has no way to learn that what it is *allowed* to use is a
 * separate, declared thing they can narrow.
 */
function CapabilityGrants() {
  return (
    <>
      {/* Was a heading, three paragraphs in a callout, a seven-row command table
          and a closing note — roughly 300 words of mechanism, permanently open, at
          the foot of a page somebody opened to look at their agents. The claim is
          the part that has to be visible; the mechanism is the part you read once.
          So the claim stays and the rest is behind the button. */}
      <h2 id="tools">What an agent is allowed to do</h2>
      <p className="sub">
        The table above is what these agents have been <em>seen</em> calling. What
        they are <em>permitted</em> to call is a separate declaration — a capability
        grant — and it is default deny: an agent with no grant for a tool cannot call
        it at all. Grants are made from the command line; there is no screen for them
        yet.
      </p>
      <Explainer label="How capability grants work" title="Capability grants">
        <p>
          A grant says this agent may call this tool, and on what terms: which
          actions, limits on the values in the arguments, a ceiling on how untrusted
          those arguments may be, whether the call needs a human approval first, and
          a date the grant expires.
        </p>
        <p>
          This is one half of whether an action runs. The other half is the{" "}
          <Link href="/app/glossary#impact-tier">impact tier</Link> on the tool
          itself — how much damage it can do. Together they are the reason a prompt
          injection can succeed at convincing the model and still not get the action
          executed.
        </p>
        <p>
          <strong>A grant contains only what has been declared.</strong> A tool
          declared <span className="mono">read</span> that in fact deletes records is
          not contained by any of this, and a grant is not evidence that a tool
          behaves as described.
        </p>

        <h4>Commands</h4>
        <div className="panel scroll-x">
          <table>
            <thead>
              <tr><th>to do this</th><th>command</th></tr>
            </thead>
            <tbody>
              <tr>
                <td className="small">Let an agent call a tool</td>
                <td className="mono small">agentfox permit grant AGENT TOOL</td>
              </tr>
              <tr>
                <td className="small">Cap what the arguments may say</td>
                <td className="mono small">--limit amount:lte=500 --action refund,lookup</td>
              </tr>
              <tr>
                <td className="small">Refuse arguments from something untrusted</td>
                <td className="mono small">--max-taint user</td>
              </tr>
              <tr>
                <td className="small">Send the call to a human first</td>
                <td className="mono small">--requires-approval</td>
              </tr>
              <tr>
                <td className="small">Make the grant expire on its own</td>
                <td className="mono small">--expires-in-days 30</td>
              </tr>
              <tr>
                <td className="small">See what an agent currently holds</td>
                <td className="mono small">agentfox permit list AGENT</td>
              </tr>
              <tr>
                <td className="small">Take one back</td>
                <td className="mono small">agentfox permit revoke CAPABILITY_ID</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          Granting writes <span className="mono">capability.granted</span> to the
          audit chain — evidence on the{" "}
          <Link href="/app/compliance?tab=evidence">Compliance page</Link>. A call
          sent for sign-off arrives in{" "}
          <Link href="/app/approvals">Approvals</Link>. Over HTTP:{" "}
          <span className="mono">POST /api/identities/{"{id}"}/capabilities</span>.
        </p>
      </Explainer>

    </>
  );
}

const fieldStyle = {
  width: "100%",
  padding: "5px 9px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel-2)",
  color: "var(--text)",
  fontSize: 13,
  fontFamily: "inherit",
} as const;

/**
 * Rendered twice — once in the page header, once inside the no-agents empty
 * state — so every input id is prefixed. Two copies of the same form on one page
 * with the same ids would leave each `htmlFor` pointing at whichever input the
 * browser saw first, which is the bug the labels were added to fix.
 */
function RegisterAgentModal({ idPrefix }: { idPrefix: string }) {
  const id = (field: string) => `${idPrefix}-register-agent-${field}`;
  return (
    <Modal
      trigger="+ Register an agent manually"
      triggerClassName="btn-primary"
      title="Register an agent manually"
    >
      <p className="small muted" style={{ marginTop: 0, marginBottom: 12 }}>
        For an agent outside a scanned repo —{" "}
        <Link href="/app/start?tab=connect">Connect</Link> is the repo-scan path.
      </p>
      <form action="/api/agents" method="POST" className="stack">
        <div>
          <label htmlFor={id("slug")} className="small muted" style={{ display: "block", marginBottom: 4 }}>Slug (unique, lowercase)</label>
          <input id={id("slug")} type="text" name="slug" required placeholder="e.g. billing-support" style={fieldStyle} />
        </div>
        <div>
          <label htmlFor={id("name")} className="small muted" style={{ display: "block", marginBottom: 4 }}>Name</label>
          <input id={id("name")} type="text" name="name" placeholder="e.g. Billing Support Agent" style={fieldStyle} />
        </div>
        <div>
          <label htmlFor={id("purpose")} className="small muted" style={{ display: "block", marginBottom: 4 }}>Purpose</label>
          <input id={id("purpose")} type="text" name="purpose" placeholder="e.g. answers billing questions from account history" style={fieldStyle} />
        </div>
        <div className="row" style={{ gap: 12 }}>
          <div style={{ flex: 1 }}>
            <label htmlFor={id("owner")} className="small muted" style={{ display: "block", marginBottom: 4 }}>Owner email</label>
            <input id={id("owner")} type="email" name="owner_email" placeholder="owner@company.com" style={fieldStyle} />
          </div>
          <div style={{ flex: 1 }}>
            <label htmlFor={id("risk")} className="small muted" style={{ display: "block", marginBottom: 4 }}>Risk tier</label>
            <select id={id("risk")} name="risk_tier" defaultValue="limited" style={fieldStyle}>
              <option value="minimal">minimal</option>
              <option value="limited">limited</option>
              <option value="high">high</option>
              <option value="prohibited">prohibited</option>
            </select>
          </div>
        </div>
        <div>
          <button type="submit" className="btn-primary">Register agent</button>
        </div>
      </form>
    </Modal>
  );
}

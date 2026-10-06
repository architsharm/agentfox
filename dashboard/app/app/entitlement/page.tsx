import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, apiErrorProps } from "@/lib/api";
import { ApiDown, Empty, InfoTip, Panel, Stat } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";
import { Modal } from "@/components/Modal";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata(
  "Access control",
  "What each agent was granted, and what it is therefore allowed to call.",
);

export const dynamic = "force-dynamic";

const CLASS_OPTIONS: { value: string; label: string }[] = [
  { value: "pii_sensitive", label: "Sensitive personal data" },
  { value: "mnpi", label: "Insider financial information" },
  { value: "legal_hold", label: "Under legal hold" },
  { value: "blackout", label: "Blackout-period restricted" },
  { value: "insider", label: "Insider-only" },
];

const inputStyle = {
  width: "100%",
  padding: "6px 9px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel-2)",
  color: "var(--text)",
  fontSize: 13,
  fontFamily: "inherit",
} as const;

/**
 * P10 — the highest commercial-value gap, and the reason Copilot-class rollouts stall.
 *
 * The number this page exists for is over-permission: how much more the agent can
 * reach than its callers are entitled to. It is meaningful before any entitlement
 * model exists, which is the argument for looking at it first.
 */
export default async function Entitlement() {
  let report: any, principals: any, grants: any;
  try {
    [report, principals, grants] = await Promise.all([
      api("/api/entitlement/over-permission"),
      api("/api/entitlement/principals"),
      api("/api/entitlement/grants"),
    ]);
  } catch (e: any) {
    return (
      <>
        <h1>Access Control</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const ratio = report.over_permission;

  return (
    <>
      <PageHeader title="Access control" sub="Whether a shared agent identity actually stops one person seeing another’s data." />

      {report.requests === 0 ? (
        <div className="hero empty">
          <div className="hero-title">Nobody is being checked yet</div>
          <p>{report.note}</p>
          <p className="small muted">
            Add people and teams below with what they are cleared to see.{" "}
            <InfoTip text="This page fills in as real requests get checked against them." />
          </p>
        </div>
      ) : (
        <>
          <div className="cards">
            <Stat
              n={`${(ratio * 100).toFixed(1)}%`}
              label="held back for not being cleared to see it"
              tone={ratio > 0.2 ? "bad" : ratio ? "warn" : "ok"}
              hint="Not an error rate — this is how much of what the agent could technically reach, it correctly did NOT show someone because they weren't cleared for it. A high number with few people/grants set up below usually means nobody's configured entitlement yet, not that something's broken."
            />
            <Stat n={report.requests} label={`checks run, last ${report.window_days} days`} />
            <Stat n={report.principals} label="different people this was checked for" />
            <Stat
              n={report.candidates}
              label="pieces of content evaluated"
              hint="Every retrieved chunk of information that was checked against someone's entitlement, across every request in the window."
            />
          </div>

          <h2>Why content was withheld</h2>
          <div className="panel">
            {/* Checks ran and withheld nothing is a real, good answer — and it is
                not the same picture as two column headers over no rows. */}
            {Object.keys(report.reasons || {}).length === 0 ? (
              <Empty>
                Nothing was withheld in this window.{" "}
                <InfoTip text="Every piece of content the agent retrieved, the person asking was cleared to see." />
              </Empty>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>reason</th>
                    <th>chunks</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.reasons).map(([reason, count]: [string, any]) => (
                    <tr key={reason}>
                      <td className="mono">{reason.replace(/_/g, " ")}</td>
                      <td className="mono small">{count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* Both "add" forms were permanently open panels — four fields and a
          submit for a person, two fields and five checkboxes for a grant — and
          together they filled roughly 60% of a page whose actual content was one
          caller and one grant. Registering a principal is something you do once
          in a while, not something the page should be posed for. Same Modal
          pattern the Sources page already uses for "+ Add a source". */}
      <div className="section-head">
        <h2>Callers</h2>
        <Modal trigger="+ Add a person or group" triggerClassName="btn-primary" title="Add a person or group">
        <form action="/api/entitlement/principals" method="POST" className="body stack">
          <div>
            <label htmlFor="ent-principal-subject" className="small muted" style={{ display: "block", marginBottom: 4 }}>
              Email or team name
            </label>
            <input type="text" id="ent-principal-subject" name="subject" required placeholder="alice@yourcompany.com" style={inputStyle} />
          </div>
          <div>
            <label htmlFor="ent-principal-display" className="small muted" style={{ display: "block", marginBottom: 4 }}>
              Display name (optional)
            </label>
            <input type="text" id="ent-principal-display" name="display" placeholder="Alice from Support" style={inputStyle} />
          </div>
          <div>
            <label htmlFor="ent-principal-groups" className="small muted" style={{ display: "block", marginBottom: 4 }}>
              Teams they belong to (comma-separated)
            </label>
            <input type="text" id="ent-principal-groups" name="groups" placeholder="support-team, all-staff" style={inputStyle} />
          </div>
          <div>
            <label htmlFor="ent-principal-clearances" className="small muted" style={{ display: "block", marginBottom: 4 }}>
              Sensitive categories they're cleared to see (comma-separated, leave blank if none)
            </label>
            <input type="text" id="ent-principal-clearances" name="clearances" placeholder="pii_sensitive" style={inputStyle} />
          </div>
          <div>
            <button type="submit" className="btn-primary">Add person or group</button>
          </div>
        </form>
        </Modal>
      </div>
      <div className="panel">
        {principals.principals?.length ? (
          <table>
            <thead>
              <tr>
                <th>subject</th>
                <th>groups</th>
                <th>clearances</th>
                <th>residency</th>
              </tr>
            </thead>
            <tbody>
              {principals.principals.map((p: any) => (
                <tr key={p.subject} id={`principal-${encodeURIComponent(p.subject)}`}>
                  <td className="mono small">{p.subject}</td>
                  <td className="small">{p.groups?.join(", ") || <span className="muted">—</span>}</td>
                  <td className="small">
                    {p.clearances?.length ? (
                      p.clearances.map((c: string) => (
                        <span key={c} className="tag warn">
                          {c}
                        </span>
                      ))
                    ) : (
                      <span className="muted">none</span>
                    )}
                  </td>
                  <td className="small muted">{p.residency || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>
            No principals registered.{" "}
            <InfoTip text="Until one is, the agent answers with no idea who is asking." />
          </Empty>
        )}
      </div>

      <div className="section-head">
        <h2>
          Grants
          <InfoTip text="A resource here is the same identifier space as a source's key on the Verified sources page — that page tells you whether the resource itself is trustworthy; this one tells you who's allowed to see it." />
        </h2>
        <Modal trigger="+ Add a grant" triggerClassName="btn-primary" title="Add a grant — who can see which source">
        <form action="/api/entitlement/grants" method="POST" className="body stack">
          <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <label htmlFor="ent-grant-resource" className="small muted" style={{ display: "block", marginBottom: 4 }}>
                Which source can they see?
              </label>
              <input type="text" id="ent-grant-resource" name="resource" required placeholder="price-book" style={inputStyle} />
            </div>
            <div style={{ flex: 1, minWidth: 200 }}>
              <label htmlFor="ent-grant-principal" className="small muted" style={{ display: "block", marginBottom: 4 }}>
                Person or team (must match a name above)
              </label>
              <input type="text" id="ent-grant-principal" name="principal" required placeholder="support-team" style={inputStyle} />
            </div>
          </div>
          <div>
            <label htmlFor="ent-grant-kind" className="small muted" style={{ display: "block", marginBottom: 4 }}>
              That is
            </label>
            <select id="ent-grant-kind" name="principal_kind" defaultValue="auto" style={inputStyle}>
              <option value="auto">worked out from the name (an email is a person)</option>
              <option value="subject">one person</option>
              <option value="group">a team everyone in it gets</option>
            </select>
          </div>
          {/* A <label> pointing at nothing does not name these five checkboxes;
              a fieldset's legend does, so each one is read as "insider-only,
              within sensitive categories" rather than as a loose checkbox. */}
          <fieldset style={{ border: "none", padding: 0, margin: 0, minWidth: 0 }}>
            <legend className="small muted" style={{ padding: 0, marginBottom: 4 }}>
              Sensitive categories this grant covers{" "}
              <InfoTip text="Only needed if the source contains sensitive data, and they still need a matching clearance above." />
            </legend>
            <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
              {CLASS_OPTIONS.map((c) => (
                <label key={c.value} className="small" style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <input type="checkbox" name="classes" value={c.value} />
                  {c.label}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <button type="submit" className="btn-primary">Add grant</button>
          </div>
        </form>
        </Modal>
      </div>
      <p className="sub">
        Default-deny: a resource with no grant is invisible. Names match source keys on{" "}
        <Link href="/app/sources">Verified sources</Link>.{" "}
        <InfoTip text="A grant does not open a restricted class — that needs a matching clearance." />
      </p>
      <div className="panel">
        {grants.grants?.length ? (
          <table>
            <thead>
              <tr>
                <th>resource</th>
                <th>principal</th>
                <th>classes</th>
                <th>purposes</th>
              </tr>
            </thead>
            <tbody>
              {grants.grants.map((g: any) => (
                <tr key={g.id}>
                  <td className="mono small">{g.resource}</td>
                  <td className="small">
                    <Link href={`#principal-${encodeURIComponent(g.principal)}`}>{g.principal}</Link>
                    <span className="tag">{g.principal_kind}</span>
                  </td>
                  <td className="small">
                    {g.classes?.map((c: string) => (
                      <span key={c} className="tag warn">
                        {c}
                      </span>
                    )) || <span className="muted">—</span>}
                  </td>
                  <td className="small muted">{g.purposes?.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No grants. Every resource is invisible to every caller.</Empty>
        )}
      </div>

    </>
  );
}

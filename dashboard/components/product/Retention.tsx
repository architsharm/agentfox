import { Card, Empty, Pill, ago } from "@/components/kit";
import { ts } from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  delete: "Deleted",
  redact: "Content redacted",
  locked: "Never purged",
  unenforced: "Not enforced",
};

/** A retention period in words. */
export function days(n?: number | null): string {
  if (n === null || n === undefined) return "Kept indefinitely";
  if (n % 365 === 0) return `${n / 365} year${n === 365 ? "" : "s"}`;
  return `${n} day${n === 1 ? "" : "s"}`;
}

export function purgeSummary(result: any): string {
  if (!result) return "—";
  if (result.skipped) {
    return result.skipped === "no policy" ? "Kept" : result.skipped === "legal hold" ? "Held" : "—";
  }
  let deleted = 0;
  let redacted = 0;
  for (const [k, v] of Object.entries(result)) {
    if (typeof v !== "number") continue;
    if (k.endsWith("_deleted")) deleted += v;
    if (k.endsWith("_redacted")) redacted += v;
  }
  if (!deleted && !redacted) return "Nothing due";
  return [deleted ? `${deleted} deleted` : "", redacted ? `${redacted} redacted` : ""].filter(Boolean).join(", ");
}

/**
 * How long each class of recorded data is kept, changed here and enforced by a
 * daily purge. The audit log is shown, locked: it is never purged.
 */
export function Retention({ retention }: { retention: any }) {
  const last = retention.last_run;
  const activeHolds = retention.legal_holds.filter((h: any) => !h.released_at);
  return (
    <>
      <h2>Retention</h2>
      <p className="sub">
        How long each kind of data is kept. A daily purge deletes or redacts what is
        older. Active legal holds stop it.
      </p>

      <Card
        flush
        title="Data classes"
        action={
          <form action="/api/retention/purge" method="POST" className="row" style={{ gap: 10 }}>
            <span className="small muted">
              Last purge {last ? `${ago(last.started_at)} by ${last.requested_by || "schedule"}` : "never"}
              {" · "}
              Next {retention.next_run ? (retention.next_run === "due" ? "on the next cron run" : ts(retention.next_run)) : "not scheduled"}
            </span>
            <button type="submit" className="k-btn">Run purge now</button>
          </form>
        }
      >
        <table className="k-table">
          <thead>
            <tr>
              <th>Data</th>
              <th className="tight">Kept for</th>
              <th className="tight">After that</th>
              <th className="tight">Last purge</th>
              <th className="tight"></th>
            </tr>
          </thead>
          <tbody>
            {retention.classes.map((c: any) => (
              <tr key={c.data_class}>
                <td>
                  <span className="k-name">{c.label}</span>
                  <span className="sub">{c.covers}</span>
                </td>
                <td className="tight">
                  {c.action === "locked" ? "Life of the workspace" : days(c.retain_days)}
                </td>
                <td className="tight">
                  <Pill tone={c.action === "locked" ? "ok" : c.retain_days ? "info" : "outline"}>
                    {c.action === "locked" || c.retain_days ? ACTION_LABEL[c.action] : "Nothing"}
                  </Pill>
                </td>
                <td className="tight muted">{purgeSummary(c.last_result)}</td>
                <td className="tight">
                  {c.action === "delete" || c.action === "redact" ? (
                    <details>
                      <summary className="small">Change</summary>
                      <form
                        action={`/api/retention/${encodeURIComponent(c.data_class)}`}
                        method="POST"
                        className="k-limits-form"
                        style={{ marginTop: 8 }}
                      >
                        <div className="k-limits-row">
                          <input
                            className="k-input"
                            type="number"
                            name="retain_days"
                            min={1}
                            max={3650}
                            required
                            defaultValue={c.retain_days ?? c.default_days ?? 365}
                            aria-label="Days to keep"
                          />
                          <span className="small muted">days</span>
                        </div>
                        <input
                          className="k-input"
                          name="reason"
                          required
                          placeholder="Reason, kept on the audit log"
                          aria-label="Reason"
                        />
                        <button type="submit" className="k-btn-primary">Save</button>
                      </form>
                    </details>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <h2>Legal holds</h2>
      <p className="sub">
        A hold preserves data the purge would otherwise remove. A hold with no agents
        stops the purge entirely.
      </p>

      <Card title="Place a hold">
        <form action="/api/legal-holds" method="POST" className="k-form">
          <div className="k-field">
            <label htmlFor="lh-agents">Agents</label>
            <input id="lh-agents" className="k-input" type="text" name="agents" placeholder="All agents, or: support-triage, refund-bot" />
          </div>
          <div className="k-field">
            <label htmlFor="lh-reason">Reason</label>
            <input id="lh-reason" className="k-input" type="text" name="reason" required placeholder="Litigation hold, case 4471" />
          </div>
          <div className="k-field">
            <span />
            <div><button type="submit" className="k-btn-primary">Place hold</button></div>
          </div>
        </form>
      </Card>

      <Card flush title={`Holds${activeHolds.length ? ` (${activeHolds.length} active)` : ""}`}>
        {retention.legal_holds.length === 0 ? (
          <Empty>No legal holds placed.</Empty>
        ) : (
          <table className="k-table">
            <thead>
              <tr><th className="tight">Placed</th><th>By</th><th>Agents</th><th>Reason</th><th className="tight">Status</th></tr>
            </thead>
            <tbody>
              {retention.legal_holds.map((h: any) => (
                <tr key={h.id}>
                  <td className="tight muted">{ts(h.placed_at)}</td>
                  <td className="muted">{h.placed_by}</td>
                  <td className="muted">{(h.scope?.agents || ["All"]).join(", ")}</td>
                  <td>{h.reason}</td>
                  <td className="tight">
                    <Pill tone={h.released_at ? "outline" : "warn"}>
                      {h.released_at ? `Released ${ts(h.released_at)}` : "Active"}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}


import { Empty, ObsTable, n } from "@/components/product/observe/parts";

type Row = { key: string; requests: number; allowed: number; held: number; blocked: number; masked: number; errors: number; cost_usd?: number };

/** Traffic cut one way (by tool, by model): how much, and what AgentFox did with it. */
export function Breakdown({ rows, label, cost, empty }: { rows: Row[]; label: string; cost?: boolean; empty: string }) {
  const max = Math.max(1, ...rows.map((r) => r.requests));
  return (
    <ObsTable
      head={[label, "Calls", "", "Allowed", "Held", "Blocked", "Masked", "Errors", ...(cost ? ["Cost"] : [])]}
      empty={!rows.length && <Empty>{empty}</Empty>}
    >
      {rows.map((r) => (
        <tr key={r.key}>
          <td className="mono">{r.key}</td>
          <td className="mono">{n(r.requests)}</td>
          <td className="obs-bar-cell">
            <span className="obs-bar" aria-hidden>
              <i className="ok" style={{ width: `${(r.allowed / max) * 100}%` }} />
              <i className="warn" style={{ width: `${(r.held / max) * 100}%` }} />
              <i className="bad" style={{ width: `${(r.blocked / max) * 100}%` }} />
            </span>
          </td>
          <td className="mono">{n(r.allowed)}</td>
          <td className={`mono${r.held ? " obs-warn" : " muted"}`}>{n(r.held)}</td>
          <td className={`mono${r.blocked ? " obs-bad" : " muted"}`}>{n(r.blocked)}</td>
          <td className="mono muted">{n(r.masked)}</td>
          <td className={`mono${r.errors ? " obs-bad" : " muted"}`}>{n(r.errors)}</td>
          {cost && <td className="mono">${(r.cost_usd ?? 0).toFixed(2)}</td>}
        </tr>
      ))}
    </ObsTable>
  );
}

import type { ReactNode } from "react";
import { Meta, Pill, ago } from "@/components/kit";
import { ruleTitle } from "@/lib/product/vocab";
import { checksLabel, doesLabel, simulationSummary, type LibraryContents, type LibraryRule } from "@/lib/product/libraries";

/** What the drawer and a library's page show for one library. */
export type LibraryView = {
  id: string;
  title: string;
  description: string;
  rules: number;
  /** Which agents it is on, said in a line ("support-agent, billing-agent"). */
  on: string;
  mode: "watching" | "blocking" | null;
  contents: LibraryContents | null;
  /** The starter rules come from the applied rules, not a shipped library. */
  ruleRows?: LibraryRule[];
  /** Said above the actions: why a library can't be limited to the project, say. */
  note?: string;
  /** Shown under the rules: the business rules in Your rules, each with its own switch. */
  extra?: ReactNode;
  project: string | null;
  actions: ReactNode;
};

/**
 * One library, in full: what it covers, where it is on and in which mode, its actions
 * (the card's, the same buttons), every rule it holds (what each checks and does),
 * and what its last simulation found. The body of the drawer a library card opens,
 * and of /app/policies/<library>.
 */
export function LibraryDetail({ v }: { v: LibraryView }) {
  const rows = v.ruleRows ?? v.contents?.rules ?? [];
  const sim = v.contents?.simulation;
  return (
    <div className="lib-detail">
      <p className="lib-detail-text">{v.description}</p>
      <Meta
        items={[
          ["Rules", String(v.rules)],
          ["On", v.on],
          ["Mode", v.mode ? <Pill tone={v.mode === "blocking" ? "brand" : "warn"}>{v.mode === "blocking" ? "Blocking" : "Watching"}</Pill> : "—"],
        ]}
      />
      {v.note && <p className="lib-detail-note">{v.note}</p>}
      <div className="lib-actions lib-detail-actions">{v.actions}</div>

      {rows.length > 0 ? (
        <table className="k-table lib-rules">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Checks</th>
              <th>{v.mode === "watching" ? "Would do" : "Does"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>
                  <span className="k-name">{r.description ? r.description : ruleTitle(r.id)}</span>
                  {r.detail && <span className="sub">{r.detail}</span>}
                </td>
                <td className="muted">{checksLabel(r)}</td>
                <td className="tight">
                  <Pill tone={r.effect === "block" ? "bad" : r.effect === "escalate" ? "held" : r.effect === "allow" ? "neutral" : "info"}>{doesLabel(r.effect)}</Pill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : v.id === "custom" ? (
        <p className="muted">No rules yet. Add one and it lands here, watching.</p>
      ) : (
        <p className="muted">Its rules could not be listed.</p>
      )}
      {v.extra}

      {v.contents?.scoped && (
        <p className="lib-detail-sim">
          <b>Simulation: </b>
          {sim
            ? `${simulationSummary(sim)}${sim.at ? ` Run ${ago(sim.at)}.` : ""}`
            : v.mode
              ? `Not simulated on ${v.project ?? "these agents"} yet. Simulate replays recent traffic as if it blocked; it is what lets Start blocking through.`
              : "Apply it first: a simulation replays recent traffic against the copies it makes."}
        </p>
      )}
    </div>
  );
}

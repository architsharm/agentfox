import type { ReactNode } from "react";
import { Meta, Pill, ago } from "@/components/kit";
import { ruleTitle } from "@/lib/product/vocab";
import { businessRuleName, inlineMarkdown, splitControls } from "@/lib/product/policyWords";
import { checksLabel, doesLabel, simulationSummary, wouldDoLabel, type LibraryContents, type LibraryRule } from "@/lib/product/libraries";

/** What the drawer and a library's page show for one library. */
export type LibraryView = {
  id: string;
  title: string;
  description: string;
  rules: number;
  /** Which agents it is on, said in a line ("support-agent, billing-agent"). */
  on: string;
  /** `mixed`: Your rules, when some of its rules block and others only watch. */
  mode: "watching" | "blocking" | "mixed" | null;
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
/** A rule's docstring with its *emphasis* and `code` rendered, not shown as marks. */
function Markdown({ text }: { text: string }) {
  return (
    <>
      {inlineMarkdown(text).map((p, i) =>
        p.kind === "em" ? <em key={i}>{p.text}</em> : p.kind === "strong" ? <strong key={i}>{p.text}</strong> : p.kind === "code" ? <code key={i}>{p.text}</code> : <span key={i}>{p.text}</span>,
      )}
    </>
  );
}

/**
 * One rule's name: its title, never its id. A business rule (it has bands) is named
 * as a person would; a rule whose description is its title shows no details.
 */
function RuleName({ r }: { r: LibraryRule }) {
  const title = r.detail ? businessRuleName({ key: r.id, name: r.description, tool: r.tool }) : ruleTitle(r.id, r.description);
  const { text, controls } = splitControls(r.description || "");
  const more = text && text !== title && !r.detail;
  return (
    <>
      <span className="k-name">{title}</span>
      {r.detail && <span className="sub">{r.detail}</span>}
      {more || controls.length ? (
        <details className="lib-rule-more">
          <summary>Details</summary>
          {more ? (
            <p>
              <Markdown text={text} />
            </p>
          ) : null}
          {controls.length ? <div className="lib-rule-controls">Controls: {controls.join(", ")}</div> : null}
        </details>
      ) : null}
    </>
  );
}

const DOES_TONE = (effect: string) => (effect === "block" ? "bad" : effect === "escalate" ? "held" : effect === "allow" ? "neutral" : "info");

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
          ["Mode", v.mode ? <Pill tone={v.mode === "blocking" ? "brand" : "outline"}>{v.mode === "blocking" ? "Blocking" : v.mode === "mixed" ? "Some blocking, some watching" : "Watching"}</Pill> : "—"],
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
              <th>{v.mode === "blocking" ? "Does" : "Would do"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>
                  <RuleName r={r} />
                </td>
                <td className="muted">{checksLabel(r)}</td>
                <td className="tight">
                  {/* Watching: what it would do, quiet; red and amber are for what acts now. */}
                  {v.mode === "blocking" ? (
                    <Pill tone={DOES_TONE(r.effect)}>{doesLabel(r.effect)}</Pill>
                  ) : (
                    <Pill tone="outline">{wouldDoLabel(r.effect)}</Pill>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : v.id === "custom" ? (
        // Business rules are listed below; "no rules yet" above them read as a contradiction.
        v.extra ? null : <p className="muted">No rules yet. Add one and it lands here, watching.</p>
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

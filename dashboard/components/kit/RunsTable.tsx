import Link from "next/link";
import { Dot, Empty, OutcomePill, Pill, ago } from "@/components/kit";
import { SURFACES, WOULD, outcomeOf, ruleTitle } from "@/lib/product/vocab";

/** Runs as a list: when, which agent, what it was doing, what happened and why. */
export function RunsTable({ runs, showAgent = true }: { runs: any[]; showAgent?: boolean }) {
  if (!runs.length) return <Empty>No runs match.</Empty>;
  return (
    <table className="k-table">
      <thead>
        <tr>
          <th className="tight">When</th>
          {showAgent && <th>Agent</th>}
          <th>What</th>
          <th className="tight">Outcome</th>
          <th>Why</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((t) => {
          const rules: string[] = t.rules || [];
          const what =
            t.intent ||
            (t.tools?.length ? t.tools.join(", ") : null) ||
            (t.surfaces || []).map((x: string) => SURFACES[x] || x).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i).join(" · ") ||
            "Model call";
          return (
            <tr key={t.id}>
              <td className="tight muted" title={t.started_at}>
                {t.status === "error" && <Dot tone="bad" />} {ago(t.started_at)}
              </td>
              {showAgent && (
                <td>
                  {t.agent ? (
                    <Link href={`/app/agents/${encodeURIComponent(t.agent)}`}>{t.agent}</Link>
                  ) : (
                    <span className="k-muted">—</span>
                  )}
                </td>
              )}
              <td>
                <Link className="k-name" href={`/app/traces/${t.id}`}>
                  {what}
                </Link>
              </td>
              <td className="tight">
                <span className="k-pills">
                  <OutcomePill outcome={outcomeOf(t.verdict)} />
                  {t.would_verdict && outcomeOf(t.verdict) === "allowed" && (
                    <Pill tone="outline" title="The rule is only watching. Enforced, this run would have been stopped.">
                      {WOULD[t.would_verdict]}
                    </Pill>
                  )}
                </span>
              </td>
              <td className="muted">
                {rules.length ? (
                  <>
                    {ruleTitle(rules[0])}
                    {rules.length > 1 && <span className="k-muted"> +{rules.length - 1}</span>}
                  </>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

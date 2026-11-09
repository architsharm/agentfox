import Link from "next/link";
import { Dot, Empty, OutcomePill, Pill, ago } from "@/components/kit";
import { SURFACES, WOULD, outcomeOf, ruleTitle } from "@/lib/product/vocab";
import { approvalOutcome } from "@/lib/product/approvals";
import { agentName } from "@/lib/product/names";
import { runSteps, runWhat } from "@/lib/product/runWhat";

/** Runs as a list: when, which agent, what it was doing, what happened and why. */
export function RunsTable({
  runs,
  showAgent = true,
  names = new Map(),
}: {
  runs: any[];
  showAgent?: boolean;
  /** slug → display name (lib/product/names.ts). */
  names?: Map<string, string>;
}) {
  if (!runs.length) return <Empty>No runs match.</Empty>;
  return (
    <table className="k-table k-row-link">
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
          // What the person asked reads better than the developer's task label.
          const what = runWhat(t, SURFACES, names);
          const steps = runSteps(t, names);
          return (
            <tr key={t.id}>
              <td className="tight muted" title={t.started_at}>
                {t.status === "error" && <Dot tone="bad" />} {ago(t.started_at)}
              </td>
              {showAgent && (
                <td>
                  {t.agent ? (
                    <Link href={`/app/projects/${encodeURIComponent(t.agent)}`}>{agentName(names, t.agent)}</Link>
                  ) : (
                    <span className="k-muted">—</span>
                  )}
                </td>
              )}
              <td>
                <Link className="k-name" href={`/app/traces/${t.id}`}>
                  {what}
                </Link>
                {steps && (
                  <span className="sub" title="The model calls, tool calls and checks in this turn">
                    {steps}
                  </span>
                )}
              </td>
              <td className="tight">
                <span className="k-pills">
                  {t.checks === 0 ? (
                    <Pill tone="outline" title="This run reached AgentFox as telemetry only; no check ran on it.">
                      Not checked
                    </Pill>
                  ) : (
                    <OutcomePill outcome={outcomeOf(t.verdict)} />
                  )}
                  {outcomeOf(t.verdict) === "held" && approvalOutcome({ status: t.approval_status }) && (
                    <Pill tone={approvalOutcome({ status: t.approval_status })!.tone}>{approvalOutcome({ status: t.approval_status })!.label}</Pill>
                  )}
                  {t.would_verdict && outcomeOf(t.verdict) === "allowed" && (
                    <Pill tone="outline" title="The rule is watching. Blocking, it would have stopped this run.">
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

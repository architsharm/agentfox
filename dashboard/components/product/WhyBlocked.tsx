import Link from "next/link";

/**
 * Why one decision went the way it did, in the order the person asking needs it.
 *
 * This is the screen a platform engineer lands on. They did not come looking for a
 * governance product — they met a block in a log line, they have a decision id, and
 * they want to know three things in this order: what decided it, what to do about
 * it, and how to say it was wrong. Everything else on this page is for somebody
 * else and can wait below the fold.
 *
 * The page already had the raw material — rules fired, detector runs, spans, scores
 * — and left the reader to do the join themselves: which of five detections was the
 * one that mattered, and which of the four detectors to argue with. The live HTTP
 * response had answered exactly that, in one sentence, and then thrown it away.
 * `explain_recorded` rebuilds it from what was stored.
 *
 * Deliberately not a summary of the whole trace: a trace can hold several decisions,
 * and an input that escalated and an output that blocked are two different answers.
 * One of these renders per decision.
 */

type Match = {
  detector: string | null;
  entity_type: string | null;
  span: (number | null)[];
  score: number | null;
  owasp_id?: string | null;
  decisive: boolean;
};

export type RecordedExplanation = {
  summary: string;
  rule: { rule_id?: string; effect?: string; reason?: string; mode?: string } | null;
  matches: Match[];
  remedy: string;
  dispute: { payload: { decision_id?: string; detector_key?: string; entity_type?: string } };
};

export function WhyBlocked({
  explanation,
  decision,
  returnTo,
}: {
  explanation?: RecordedExplanation | null;
  decision: { id: string; surface: string; verdict: string; mode: string };
  returnTo: string;
}) {
  if (!explanation || (!explanation.summary && explanation.matches.length === 0)) return null;

  const decisive = explanation.matches.find((m) => m.decisive);
  const others = explanation.matches.filter((m) => !m.decisive);
  const observed = decision.mode === "observe";

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="head">
        <span>Why — {decision.surface}</span>
        <span className="small muted mono">{decision.id}</span>
      </div>
      <div className="body">
        {observed && (
          <p className="small muted" style={{ marginTop: 0 }}>
            This rule is in <span className="mono">observe</span> mode, so nothing was
            stopped. What follows is what <em>would</em> have happened had it been
            enforcing.
          </p>
        )}

        <p style={{ marginTop: observed ? 0 : undefined }}>
          <strong>{explanation.summary}</strong>
        </p>

        {explanation.rule?.reason && (
          <p className="small muted">{explanation.rule.reason}</p>
        )}

        {decisive && (
          <table className="rt-table small">
            <tbody>
              <tr>
                <th>Decided by</th>
                <td>
                  <span className="mono">{decisive.detector}</span> found{" "}
                  <span className="mono">{decisive.entity_type}</span> at offset{" "}
                  <span className="mono">
                    {decisive.span[0]}–{decisive.span[1]}
                  </span>{" "}
                  scoring <span className="mono">{(decisive.score ?? 0).toFixed(2)}</span>
                  {decisive.owasp_id && (
                    <>
                      {" "}
                      · <span className="mono">{decisive.owasp_id}</span>
                    </>
                  )}
                </td>
              </tr>
              {others.length > 0 && (
                <tr>
                  {/* Shown but not blamed. An engineer who sees only the decisive
                      match cannot tell whether the others were considered, and the
                      previous version of this page listed all of them as equals,
                      which is how the wrong one gets argued with. */}
                  <th>Also matched</th>
                  <td className="muted">
                    {others.map((m, i) => (
                      <span key={i}>
                        {i > 0 && ", "}
                        <span className="mono">{m.entity_type}</span> (
                        {(m.score ?? 0).toFixed(2)})
                      </span>
                    ))}
                    <div className="small">Not what decided this one.</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        {explanation.remedy && (
          <>
            <h4 className="small">What to do</h4>
            <p className="small">{explanation.remedy}</p>
          </>
        )}

        {/* The cheapest response to a false positive has to be filing one. If it is
            more expensive than switching the detector off, the detector gets
            switched off, and that is the failure mode this whole surface exists to
            prevent. */}
        <form method="post" action="/api/guardrails/feedback">
          <input type="hidden" name="return_to" value={returnTo} />
          <input type="hidden" name="decision_id" value={decision.id} />
          <input type="hidden" name="label" value="false_positive" />
          {explanation.dispute?.payload?.detector_key && (
            <input
              type="hidden"
              name="detector_key"
              value={explanation.dispute.payload.detector_key}
            />
          )}
          {explanation.dispute?.payload?.entity_type && (
            <input
              type="hidden"
              name="entity_type"
              value={explanation.dispute.payload.entity_type}
            />
          )}
          <label className="small">
            Disagree?{" "}
            <input
              type="text"
              name="note"
              placeholder="why this was wrong"
              style={{ width: 280 }}
            />
          </label>{" "}
          <button type="submit" className="btn">
            File as a false positive
          </button>
        </form>
        <p className="small muted">
          Filed against this decision and the detector that decided it. It feeds
          precision reporting and the threshold recommendations on{" "}
          <Link href="/app/policies?tab=advanced&sec=tuning">Detectors &amp; tuning</Link> — it does not
          change anything on its own.
        </p>
      </div>
    </div>
  );
}

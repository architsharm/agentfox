"use client";

import { useState } from "react";
import { InfoTip } from "@/components/ui";

type Health = {
  stable: { decisions: number; block_rate: number | null };
  candidate: { decisions: number; block_rate: number | null };
  block_rate_delta: number | null;
  ready: boolean;
};

type Canary = {
  id: string;
  status: "rolling" | "rolled_back" | "completed";
  percent: number;
  step_index: number;
  steps: number[];
  stable_version: number | null;
  candidate_version: number | null;
  max_block_rate_delta: number;
  min_sample: number;
  started_by: string | null;
  started_at: string | null;
  completed_at: string | null;
  rollback_reason: string;
  health?: Health;
};

const inputStyle: React.CSSProperties = {
  padding: "5px 9px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel-2)",
  color: "var(--text)",
  fontSize: "var(--t-small)",
  fontFamily: "inherit",
};

function pct(n: number | null): string {
  return n === null ? "—" : `${(n * 100).toFixed(1)}%`;
}

export function CanaryPanel({
  policyKey,
  initialCanary,
  latestVersion,
}: {
  policyKey: string;
  initialCanary: Canary | null;
  latestVersion: number;
}) {
  const [canary, setCanary] = useState(initialCanary);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [candidateVersion, setCandidateVersion] = useState(String(latestVersion));

  async function call(path: string, body?: unknown) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/policies/${policyKey}/canary${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(json.detail || "request failed");
        return;
      }
      setCanary(json);
    } finally {
      setBusy(false);
    }
  }

  const isRolling = canary?.status === "rolling";

  return (
    <div className="panel body stack">
      {!canary || !isRolling ? (
        <>
          {canary && (
            <p className="small muted" style={{ margin: 0 }}>
              {canary.status === "completed" ? (
                <>
                  Last canary <strong>completed</strong> — v{canary.candidate_version} is now the
                  stable version.
                </>
              ) : (
                <>
                  Last canary <strong>rolled back</strong>
                  {canary.rollback_reason && <> — {canary.rollback_reason}</>}
                </>
              )}
            </p>
          )}
          <p className="small muted" style={{ margin: 0 }}>
            Roll a version out to a percentage of traffic and let it earn its way to 100% —{" "}
            <InfoTip text="The candidate's block rate is compared against the stable version's. Once both have enough traffic, calling 'check health' either advances to the next step, or rolls back automatically if the candidate blocks meaningfully more than stable does." />
          </p>
          <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <label className="small muted" htmlFor="canary-candidate">version</label>
            <input
              id="canary-candidate"
              type="number"
              min={1}
              value={candidateVersion}
              onChange={(e) => setCandidateVersion(e.target.value)}
              style={{ ...inputStyle, width: 80 }}
            />
            <button
              type="button"
              className="btn-scan"
              disabled={busy}
              onClick={() => call("/start", { candidate_version: Number(candidateVersion) })}
            >
              Start canary rollout
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span className="tag warn">rolling</span>
            <span className="small">
              v{canary.candidate_version} at <strong>{canary.percent}%</strong> of traffic
              (step {canary.step_index + 1} of {canary.steps.length}) against stable v
              {canary.stable_version}
            </span>
          </div>

          {canary.health && (
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th className="num">decisions</th>
                  <th className="num">block rate</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="small muted">stable (v{canary.stable_version})</td>
                  <td className="num mono small">{canary.health.stable.decisions}</td>
                  <td className="num mono small">{pct(canary.health.stable.block_rate)}</td>
                </tr>
                <tr>
                  <td className="small muted">candidate (v{canary.candidate_version})</td>
                  <td className="num mono small">{canary.health.candidate.decisions}</td>
                  <td className="num mono small">{pct(canary.health.candidate.block_rate)}</td>
                </tr>
              </tbody>
            </table>
          )}

          <p className="small muted" style={{ margin: 0 }}>
            {canary.health && !canary.health.ready
              ? `Waiting for at least ${canary.min_sample} decisions on each side before the health gate can decide anything.`
              : `Rolls back automatically if the candidate's block rate exceeds stable's by more than ${(canary.max_block_rate_delta * 100).toFixed(0)} points.`}
          </p>

          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn-scan" disabled={busy} onClick={() => call("/advance")}>
              Check health &amp; advance
            </button>
            <button type="button" className="btn-reject" disabled={busy} onClick={() => call("/rollback")}>
              Roll back now
            </button>
          </div>
        </>
      )}

      {error && <div className="error">{error}</div>}
    </div>
  );
}

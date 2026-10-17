"use client";

import Link from "next/link";
import { useState } from "react";
import { detectorName } from "@/lib/product/vocab";
import {
  LEVEL_LABEL,
  changedCount,
  checkGroups,
  levelsFor,
  lockedReason,
  type CheckFeature,
  type Features,
  type Level,
  type ProtectionFeature,
} from "@/lib/product/features";

const WHERE: Record<string, string> = { input: "messages", output: "replies", tools: "tool calls", context: "documents" };

async function send(url: string, method: string, body?: unknown): Promise<{ ok: boolean; data: any }> {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { ok: res.ok, data: await res.json().catch(() => ({})) };
}

function errorOf(data: any, fallback: string): string {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d.message === "string") return d.message;
  return fallback;
}

/**
 * The workspace's switches, or one project's. With a project, each row says whether
 * it inherits the workspace's value or changed it, and a change can be undone with
 * Reset; a lower level the workspace has not opened to projects is shown but locked,
 * with the reason, rather than offered and refused.
 */
export function FeaturesEditor({ initial, canOpen = true }: { initial: Features; canOpen?: boolean }) {
  const [f, setF] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ key: string; text: string } | null>(null);
  const project = f.agent;
  const slug = project ? encodeURIComponent(project) : "";

  const run = async (key: string, url: string, method: string, body?: unknown) => {
    setBusy(key);
    setError(null);
    const r = await send(url, method, body);
    setBusy(null);
    if (!r.ok) return setError({ key, text: errorOf(r.data, "Could not save this.") });
    setF(r.data as Features);
  };

  const setProtection = (p: ProtectionFeature, level: Level) =>
    run(`p:${p.key}`, `/api/features/protections/${encodeURIComponent(p.key)}`, "POST", { level, agent: project || "" });
  const openProtection = (p: ProtectionFeature, open: boolean) =>
    run(`p:${p.key}`, `/api/features/protections/${encodeURIComponent(p.key)}`, "POST", { open_to_projects: open });
  const resetProtection = (p: ProtectionFeature) =>
    run(`p:${p.key}`, `/api/agents/${slug}/features/protections/${encodeURIComponent(p.key)}`, "DELETE");
  const setCheck = (c: CheckFeature, enabled: boolean) =>
    run(`c:${c.key}`, `/api/features/checks/${encodeURIComponent(c.key)}`, "POST", { enabled, agent: project || "" });
  const resetCheck = (c: CheckFeature) => run(`c:${c.key}`, `/api/agents/${slug}/features/checks/${encodeURIComponent(c.key)}`, "DELETE");

  const changed = project ? changedCount(f) : 0;
  const groups = checkGroups(f.checks);

  return (
    <div className="ft">
      {project && (
        <p className="ft-intro">
          Everything here starts as the workspace sets it.{" "}
          {changed ? <strong>{changed} changed for this project.</strong> : "Nothing changed for this project yet."}{" "}
          <Link href="/app/features">Workspace features</Link>
        </p>
      )}

      <section className="k-card ft-card">
        <header className="ft-head">
          <h3>Protections</h3>
          <span className="k-muted">
            {project ? "Stricter is always allowed. Lower only where the workspace allows it." : "What every project gets unless it changes it."}
          </span>
        </header>
        <ul className="ft-list">
          {f.protections.map((p) => {
            const value = p.project ?? p.workspace;
            const inherited = project && p.project === null;
            const mode = project && p.project !== null ? p.project_mode : p.workspace_mode;
            return (
              <li key={p.key} className={`ft-row${inherited ? " ft-inherited" : ""}`}>
                <div className="ft-name">
                  <strong>{p.title}</strong>
                  <span className="ft-sub">
                    {!p.available ? (
                      `Needs the ${p.pack} pack`
                    ) : project ? (
                      inherited ? (
                        <>Inherited from the workspace</>
                      ) : (
                        <>
                          Changed here · workspace is {LEVEL_LABEL[p.workspace].toLowerCase()}
                          {p.effective !== p.project && " (the workspace's still applies)"}
                        </>
                      )
                    ) : (
                      <>{p.pack}</>
                    )}
                    {mode && value !== "off" && <span className={`ft-mode ft-mode-${mode}`}>{mode}</span>}
                    {project && p.available && levelsFor(p).some((l) => lockedReason(p, l)) && (
                      <span className="ft-lock" title={lockedReason(p, "off") || undefined}>
                        lower levels locked by the workspace
                      </span>
                    )}
                  </span>
                </div>
                <div className="ft-control">
                  <div className="k-seg" role="group" aria-label={p.title}>
                    {levelsFor(p).map((l) => {
                      const locked = project ? lockedReason(p, l) : null;
                      return (
                        <button
                          key={l}
                          type="button"
                          disabled={busy === `p:${p.key}` || !p.available || Boolean(locked)}
                          title={locked || undefined}
                          className={value === l ? "active" : ""}
                          aria-pressed={value === l}
                          onClick={() => value !== l && setProtection(p, l)}
                        >
                          {LEVEL_LABEL[l]}
                        </button>
                      );
                    })}
                  </div>
                  {project && p.project !== null && (
                    <button type="button" className="ft-reset" disabled={busy === `p:${p.key}`} onClick={() => resetProtection(p)}>
                      Reset
                    </button>
                  )}
                  {!project && !p.protected && p.installed && canOpen && (
                    <label className="k-check ft-open" title="Let a project switch this off or make it less sensitive for itself">
                      <input type="checkbox" checked={p.open_to_projects} disabled={busy === `p:${p.key}`} onChange={(e) => openProtection(p, e.target.checked)} />
                      Projects may lower
                    </label>
                  )}
                  {!project && p.protected && <span className="ft-sub" title="Cannot be lowered per project">Locked</span>}
                </div>
                {error?.key === `p:${p.key}` && <p className="k-act-error ft-error" role="alert">{error.text}</p>}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="k-card ft-card">
        <header className="ft-head">
          <h3>Checks</h3>
          <span className="k-muted">
            {project ? "Switch a check on or off for this project only, either way." : "The detectors that run on every project's traffic."}
          </span>
        </header>
        {groups.map((g) => {
          const installed = g.checks.filter((c) => c.installed);
          const missing = g.checks.filter((c) => !c.installed);
          return (
            <div key={g.key} className="ft-group">
              <h4>{g.title}</h4>
              <ul className="ft-list">
                {installed.map((c) => (
                  <CheckRow key={c.key} c={c} project={project} busy={busy === `c:${c.key}`} error={error?.key === `c:${c.key}` ? error.text : null} onSet={setCheck} onReset={resetCheck} />
                ))}
              </ul>
              {missing.length > 0 && (
                <details className="ft-missing">
                  <summary>{missing.length} not installed</summary>
                  <ul className="ft-list">
                    {missing.map((c) => (
                      <CheckRow key={c.key} c={c} project={project} busy={false} error={null} onSet={setCheck} onReset={resetCheck} />
                    ))}
                  </ul>
                  <Link href="/app/policies?tab=advanced">How to install checks</Link>
                </details>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}

function CheckRow({
  c,
  project,
  busy,
  error,
  onSet,
  onReset,
}: {
  c: CheckFeature;
  project: string | null;
  busy: boolean;
  error: string | null;
  onSet: (c: CheckFeature, on: boolean) => void;
  onReset: (c: CheckFeature) => void;
}) {
  const value = project ? c.effective : c.workspace;
  const inherited = project && c.project === null;
  const name = c.label || detectorName(c.key);
  return (
    <li className={`ft-row${inherited ? " ft-inherited" : ""}`}>
      <div className="ft-name">
        <strong>{name}</strong>
        <span className="ft-sub">
          {c.where.map((w) => WHERE[w] || w).join(", ")}
          {c.always_on ? " · always on" : ""}
          {project && !c.always_on && c.installed ? (inherited ? " · inherited" : ` · changed here, workspace is ${c.workspace ? "on" : "off"}`) : ""}
        </span>
      </div>
      <div className="ft-control">
        <div className="k-seg" role="group" aria-label={name}>
          {[true, false].map((on) => {
            const disabled = busy || (!c.installed && on) || (c.always_on && !on);
            return (
              <button key={String(on)} type="button" disabled={disabled} className={value === on ? "active" : ""} aria-pressed={value === on} onClick={() => value !== on && onSet(c, on)}>
                {on ? "On" : "Off"}
              </button>
            );
          })}
        </div>
        {project && c.project !== null && (
          <button type="button" className="ft-reset" disabled={busy} onClick={() => onReset(c)}>
            Reset
          </button>
        )}
      </div>
      {error && <p className="k-act-error ft-error" role="alert">{error}</p>}
    </li>
  );
}

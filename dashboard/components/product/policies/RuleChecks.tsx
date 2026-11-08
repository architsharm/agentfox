"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, X } from "lucide-react";

import { CHECK_KIND, checkIdle, checkName, type CheckInfo } from "@/lib/product/checks";

async function send(url: string, body: unknown): Promise<{ ok: boolean; data: any }> {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { ok: res.ok, data: await res.json().catch(() => ({})) };
}

/**
 * The checks that feed a rule. With an agent: the ones on for it, with × to turn
 * one off and "+ add" to turn on another (a check is on or off for the whole agent,
 * so every rule it feeds gets it). Without: every check that can feed it.
 */
export function RuleChecks({ checks, on, agent }: { checks: CheckInfo[]; on: string[]; agent?: string }) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Without an agent: every check that can feed the rule, the ones that run first and
  // the rest marked ("off", "model not downloaded") so none reads as protection that
  // isn't running.
  const idle = (d: CheckInfo) => checkIdle(agent ? { ...d, enabled: true } : d);
  const enabled = (agent ? checks.filter((d) => on.includes(d.key)) : checks).slice().sort((a, b) => Number(Boolean(idle(a))) - Number(Boolean(idle(b))));
  const rest = agent ? checks.filter((d) => !on.includes(d.key)) : [];
  const running = enabled.filter((d) => !idle(d)).length;

  const set = async (key: string, value: boolean) => {
    setBusy(true);
    setError("");
    const r = await send(`/api/features/checks/${encodeURIComponent(key)}`, { enabled: value, agent, reason: "Set from the rule page" });
    setBusy(false);
    if (!r.ok) return setError(r.data?.detail || r.data?.error || "Could not change this check.");
    setAdding(false);
    router.refresh();
  };

  return (
    <div className="gm-rule-checks">
      {enabled.length ? (
        enabled.map((d) => (
          <span
            key={d.key}
            className={`gm-chip gm-chip-${d.source}${idle(d) ? " gm-chip-idle" : ""}`}
            title={idle(d) ? `${checkName(d)}: ${d.unavailable || idle(d)}` : agent ? `${checkName(d)}: on for ${agent}` : checkName(d)}
          >
            <b>{CHECK_KIND[d.source] ?? ""}</b> {checkName(d)}
            {idle(d) ? <span className="gm-chip-why"> · {idle(d)}</span> : null}
            {agent ? (
              <button type="button" disabled={busy} onClick={() => set(d.key, false)} aria-label={`Turn off ${checkName(d)} for ${agent}`}>
                <X size={11} aria-hidden />
              </button>
            ) : null}
          </span>
        ))
      ) : (
        <span className="gm-chip gm-chip-none">No check on: this rule can&apos;t fire</span>
      )}
      {enabled.length > 0 && running === 0 ? <span className="gm-chip gm-chip-none">None of these runs here: this rule can&apos;t fire</span> : null}
      {rest.length ? (
        <span className="gm-rule-add">
          <button type="button" className="gm-chip gm-chip-add" onClick={() => setAdding((v) => !v)} aria-label="Add a check to this rule">
            <Plus size={11} aria-hidden /> add
          </button>
          {adding ? (
            <div className="at-lib" role="dialog" aria-label="Add a check">
              <ul>
                {rest.map((d) => (
                  <li key={d.key}>
                    {d.available ? (
                      <button type="button" disabled={busy} onClick={() => set(d.key, true)}>
                        <span>
                          <strong>{checkName(d)}</strong>
                        </span>
                        <span className="at-lib-n">{CHECK_KIND[d.source] ?? ""}</span>
                      </button>
                    ) : (
                      <Link href="/app/policies?tab=checks" className="gm-lib-install">
                        <span>
                          <strong>{checkName(d)}</strong>
                        </span>
                        <span className="at-lib-n">Install</span>
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </span>
      ) : null}
      {error && <span className="k-act-error" role="alert">{error}</span>}
    </div>
  );
}

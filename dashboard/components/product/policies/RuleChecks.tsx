"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, X } from "lucide-react";

import { CHECK_KIND, checkName, type CheckInfo } from "@/lib/product/checks";

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
  const enabled = agent ? checks.filter((d) => on.includes(d.key)) : checks;
  const rest = agent ? checks.filter((d) => !on.includes(d.key)) : [];

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
          <span key={d.key} className={`gm-chip gm-chip-${d.source}`} title={agent ? `${checkName(d)}: on for ${agent}` : checkName(d)}>
            <b>{CHECK_KIND[d.source] ?? ""}</b> {checkName(d)}
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

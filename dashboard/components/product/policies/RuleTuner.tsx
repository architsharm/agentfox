"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";
import type { RulePack } from "@/lib/product/rules";
import { ACTION_CHOICES, SENSITIVITY, sensitivityOf } from "@/lib/product/vocab";

type Change = { effect?: string; enabled?: boolean; message?: string; on_block?: string; min_score?: number };

type Preview = {
  pack: string;
  version: number;
  mode: string | null;
  label: string;
  tests: null | { passed: number; failed: number; results: { id: string; sample: string; fires: boolean; passed: boolean }[] };
  simulation: null | {
    replayed: number;
    counts: { newly_blocked: number; newly_allowed: number; newly_escalated: number };
    recommendation?: string;
  };
};

/**
 * Change what one rule does: pick an action or switch it off, see what that would
 * have done to the last week of traffic, then apply. Nothing changes in force until
 * Apply — the change is saved as a new version of the rule's pack first.
 * `exact`: the rule matches exact words or patterns, so sensitivity means nothing.
 */
export function RuleTuner({ ruleId, packs, exact = false }: { ruleId: string; packs: RulePack[]; exact?: boolean }) {
  const router = useRouter();
  const [pack, setPack] = useState(packs[0]?.key || "");
  const current = packs.find((p) => p.key === pack) || packs[0];
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState(current?.message || "");

  if (!current) return <div className="k-empty">This rule is not in any installed pack.</div>;

  const propose = async (change: Change, label: string) => {
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const out = await callJson(`/api/policies/${encodeURIComponent(current.key)}/rules/${encodeURIComponent(ruleId)}`, "POST", change);
      setPreview({ pack: current.key, version: out.version, mode: out.mode, label, simulation: out.simulation, tests: out.tests });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      await callJson(`/api/policies/${encodeURIComponent(preview.pack)}/mode`, "POST", { mode: preview.mode || "observe", version: preview.version });
      setPreview(null);
      router.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const s = preview?.simulation;
  return (
    <div className="k-form">
      {packs.length > 1 && (
        <div className="k-field">
          <label>Pack</label>
          <select className="k-select" value={pack} onChange={(e) => {
              setPack(e.target.value);
              setMessage(packs.find((p) => p.key === e.target.value)?.message || "");
            }} style={{ width: 260 }}>
            {packs.map((p) => (
              <option key={p.key} value={p.key}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="k-field">
        <label>When it fires</label>
        <div className="k-seg" role="group" aria-label="Action">
          {ACTION_CHOICES.map((a) => {
            const active = current.enabled && (current.effect === a.effect || (a.effect === "redact" && ["mask", "tokenize"].includes(current.effect)));
            return (
              <button key={a.effect} disabled={busy} className={active ? "active" : ""} onClick={() => !active && propose({ effect: a.effect, enabled: true }, a.label)}>
                {a.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="k-field">
        <label>Rule</label>
        <div className="k-seg" role="group" aria-label="On or off">
          <button disabled={busy} className={current.enabled ? "active" : ""} onClick={() => !current.enabled && propose({ enabled: true }, "On")}>
            On
          </button>
          <button disabled={busy} className={!current.enabled ? "active" : ""} onClick={() => current.enabled && propose({ enabled: false }, "Off")}>
            Off
          </button>
        </div>
      </div>

      {current.minScore !== null && !exact && (
        <div className="k-field">
          <label>Sensitivity</label>
          <div className="k-seg" role="group" aria-label="Sensitivity">
            {SENSITIVITY.map((lvl) => {
              const active = sensitivityOf(current.minScore) === lvl.key;
              return (
                <button key={lvl.key} disabled={busy} className={active ? "active" : ""} onClick={() => !active && propose({ min_score: lvl.minScore }, `${lvl.label} sensitivity`)}>
                  {lvl.label}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {current.effect === "block" && (
        <div className="k-field">
          <label>On a blocked answer</label>
          <div className="k-seg" role="group" aria-label="On a blocked answer">
            <button disabled={busy} className={current.onBlock !== "reask" ? "active" : ""} onClick={() => current.onBlock === "reask" && propose({ on_block: "refuse" }, "Refuse")}>
              Refuse
            </button>
            <button disabled={busy} className={current.onBlock === "reask" ? "active" : ""} onClick={() => current.onBlock !== "reask" && propose({ on_block: "reask" }, "Ask the model to fix it")}>
              Ask the model to fix it
            </button>
          </div>
        </div>
      )}
      {["block", "escalate"].includes(current.effect) && (
        <div className="k-field">
          <label>Message to the user</label>
          <div className="k-pills" style={{ gap: 8 }}>
            <input
              className="k-input"
              style={{ flex: 1, minWidth: 240 }}
              maxLength={500}
              placeholder="Sorry, I can't help with that."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <button className="k-btn" disabled={busy || message === current.message} onClick={() => propose({ message }, "New message")}>
              Save
            </button>
          </div>
        </div>
      )}

      {busy && !preview && <div className="k-muted">Checking against the last 7 days…</div>}
      {error && <div className="error">{error}</div>}

      {preview && (
        <div className="k-preview">
          <div className="k-preview-head">
            <strong>{preview.label}</strong>
            <span className="k-muted"> · replayed {s?.replayed ?? 0} requests from the last 7 days</span>
          </div>
          <div className="k-preview-nums">
            <span><strong>{s?.counts.newly_blocked ?? 0}</strong> newly blocked</span>
            <span><strong>{s?.counts.newly_escalated ?? 0}</strong> newly held</span>
            <span><strong>{s?.counts.newly_allowed ?? 0}</strong> newly allowed</span>
          </div>
          {preview.tests && preview.tests.passed + preview.tests.failed > 0 && (
            <div className="k-form" style={{ gap: 4 }}>
              <span className={`k-pill ${preview.tests.failed ? "k-pill-bad" : "k-pill-ok"}`} style={{ alignSelf: "flex-start" }}>
                Tests: {preview.tests.passed} of {preview.tests.passed + preview.tests.failed} pass
              </span>
              {preview.tests.results
                .filter((t) => !t.passed)
                .map((t) => (
                  <span key={t.id} className="k-muted">
                    {t.fires ? "No longer catches" : "Now catches"} “{t.sample}”
                  </span>
                ))}
            </div>
          )}
          {current.mode !== "enforce" && <div className="k-muted">This pack is watching, so nothing will be blocked yet.</div>}
          <div className="k-pills" style={{ gap: 8 }}>
            <button className="k-btn-primary" disabled={busy} onClick={apply}>
              Apply
            </button>
            <button className="k-btn-ghost" disabled={busy} onClick={() => setPreview(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

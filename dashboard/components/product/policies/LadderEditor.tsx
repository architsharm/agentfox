"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

type Band = { upto: number | null; outcome: string; approver_role?: string | null; reason?: string };

const OUTCOMES = [
  { key: "allow", label: "Allow" },
  { key: "verify", label: "Check first" },
  { key: "escalate", label: "Ask a person" },
  { key: "block", label: "Block" },
];

/**
 * An approval limit, edited as what it is: bands of an amount, each with what
 * happens. "Up to 100 → allow, up to 1000 → a manager approves, above → block."
 */
export function LadderEditor({ rule, tools }: { rule: any; tools: string[] }) {
  const router = useRouter();
  const def = rule.definition || {};
  const [name, setName] = useState<string>(def.name || rule.key);
  const [tool, setTool] = useState<string>(def.tool || "");
  const [field, setField] = useState<string>(String(def.field || def.field_path || "arguments.amount").replace(/^arguments\./, ""));
  const [bands, setBands] = useState<Band[]>((def.bands || []).map((b: any) => ({ upto: b.upto ?? null, outcome: b.outcome, approver_role: b.approver_role || "", reason: b.reason || "" })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const set = (i: number, patch: Partial<Band>) => {
    setSaved(false);
    setBands(bands.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      const ordered = [...bands].sort((a, b) => (a.upto ?? Infinity) - (b.upto ?? Infinity));
      await callJson(`/api/business/rules/${encodeURIComponent(rule.key)}`, "PUT", {
        definition: {
          ...def,
          name,
          tool,
          field: `arguments.${field.replace(/^arguments\./, "")}`,
          bands: ordered.map((b) => ({
            ...(b.upto === null ? {} : { upto: b.upto }),
            outcome: b.outcome,
            ...(b.outcome === "escalate" && b.approver_role ? { approver_role: b.approver_role } : {}),
            ...(b.reason ? { reason: b.reason } : {}),
          })),
        },
      });
      setSaved(true);
      router.refresh();
    });

  const remove = () =>
    run(async () => {
      if (!window.confirm(`Delete "${name}"? Calls it held go through unchecked.`)) return;
      await callJson(`/api/business/rules/${encodeURIComponent(rule.key)}`, "DELETE");
      router.push("/app/policies");
    });

  const unit = def.unit === "USD" ? "$" : "";
  return (
    <div className="k-form">
      <div className="k-field">
        <label htmlFor="ld-name">Name</label>
        <input id="ld-name" className="k-input" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
        <div className="k-field" style={{ flex: 1, minWidth: 200 }}>
          <label htmlFor="ld-tool">Tool</label>
          <select id="ld-tool" className="k-select" value={tool} onChange={(e) => setTool(e.target.value)}>
            {[tool, ...tools.filter((t) => t !== tool)].filter(Boolean).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="k-field" style={{ flex: 1, minWidth: 160 }}>
          <label htmlFor="ld-field">Amount argument</label>
          <input id="ld-field" className="k-input k-mono" value={field} onChange={(e) => setField(e.target.value)} />
        </div>
      </div>

      <table className="k-table">
        <thead>
          <tr>
            <th>Up to</th>
            <th>What happens</th>
            <th>Who approves</th>
            <th className="tight" />
          </tr>
        </thead>
        <tbody>
          {bands.map((b, i) => (
            <tr key={i}>
              <td className="tight">
                {b.upto === null ? (
                  <span className="k-muted">Anything above</span>
                ) : (
                  <span className="k-pills" style={{ gap: 4 }}>
                    {unit}
                    <input
                      className="k-input"
                      style={{ width: 110 }}
                      type="number"
                      min={0}
                      value={b.upto}
                      onChange={(e) => set(i, { upto: e.target.value === "" ? 0 : Number(e.target.value) })}
                      aria-label={`Band ${i + 1} upper limit`}
                    />
                  </span>
                )}
              </td>
              <td>
                <div className="k-seg" role="group" aria-label={`Band ${i + 1} outcome`}>
                  {OUTCOMES.map((o) => (
                    <button key={o.key} className={b.outcome === o.key ? "active" : ""} onClick={() => set(i, { outcome: o.key })}>
                      {o.label}
                    </button>
                  ))}
                </div>
              </td>
              <td>
                {b.outcome === "escalate" ? (
                  <input className="k-input" style={{ width: 150 }} value={b.approver_role || ""} placeholder="manager" onChange={(e) => set(i, { approver_role: e.target.value })} aria-label={`Band ${i + 1} approver`} />
                ) : (
                  <span className="k-muted">—</span>
                )}
              </td>
              <td className="tight">
                {bands.length > 1 && (
                  <button className="k-btn-ghost" onClick={() => setBands(bands.filter((_, j) => j !== i))} aria-label={`Remove band ${i + 1}`}>
                    Remove
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        <button
          className="k-btn-ghost"
          onClick={() => {
            const capped = bands.filter((b) => b.upto !== null);
            const top = capped.length ? Math.max(...capped.map((b) => b.upto as number)) : 0;
            const open = bands.find((b) => b.upto === null);
            setBands([...capped, { upto: top ? top * 2 : 100, outcome: "escalate", approver_role: "manager" }, ...(open ? [open] : [])]);
          }}
        >
          Add a band
        </button>
      </div>

      {error && <div className="error">{error}</div>}
      <div className="k-pills" style={{ gap: 8 }}>
        <button className="k-btn-primary" disabled={busy || !tool || !field} onClick={save}>
          {busy ? "Saving…" : "Save changes"}
        </button>
        {saved && <span className="k-pill k-pill-ok">Saved</span>}
        <button className="k-btn-danger" disabled={busy} onClick={remove}>
          Delete
        </button>
      </div>
    </div>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";
import { IMPACT, TRUST } from "@/lib/product/vocab";

type Cap = {
  id: string;
  tool_key: string;
  requires_approval: boolean;
  max_taint: string;
  constraints: Record<string, any>;
  tool: { name: string; impact: string } | null;
  usage: { calls: number; blocked: number; held: number; last_used: string | null };
};

type Tool = { key: string; name: string; impact: string };

const OPS: { op: string; label: string }[] = [
  { op: "lte", label: "≤" },
  { op: "lt", label: "<" },
  { op: "gte", label: "≥" },
  { op: "gt", label: ">" },
  { op: "eq", label: "=" },
  { op: "in", label: "is one of" },
  { op: "not_in", label: "is not" },
  { op: "contains", label: "contains" },
];

function opLabel(op: string) {
  return OPS.find((o) => o.op === op)?.label || op;
}

function limitsText(c: Record<string, any>): string[] {
  const out: string[] = [];
  for (const [arg, spec] of Object.entries(c || {})) {
    if (spec && typeof spec === "object" && !Array.isArray(spec)) {
      for (const [op, v] of Object.entries(spec)) out.push(`${arg} ${opLabel(op)} ${Array.isArray(v) ? v.join(", ") : v}`);
    } else out.push(`${arg} = ${spec}`);
  }
  return out;
}

function impactTone(impact?: string) {
  return impact === "irreversible" ? "bad" : impact === "high_impact" ? "held" : impact === "write" ? "warn" : "neutral";
}

function ago(iso: string | null) {
  if (!iso) return "never";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/**
 * What an agent can do, editable in place. One row per tool; every change saves
 * immediately. Tools the agent tried and was refused are listed underneath with a
 * one-click grant, which is how most permissions get set: from what the agent
 * actually needed.
 */
export function AccessEditor({
  slug,
  capabilities,
  tried,
  tools,
  unused,
  prefill,
}: {
  slug: string;
  capabilities: Cap[];
  tried: { tool_key: string; count: number; last: string | null }[];
  tools: Tool[];
  unused: string[];
  prefill?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string>("");
  const [adding, setAdding] = useState(prefill || "");
  const granted = new Set(capabilities.map((c) => c.tool_key));
  const base = `/api/agents/${encodeURIComponent(slug)}/access`;

  const save = async (key: string, body: any) => {
    setBusy(key);
    setError("");
    try {
      await callJson(base, "POST", body);
      router.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };
  const remove = async (c: Cap) => {
    if (!window.confirm(`Remove ${c.tool?.name || c.tool_key}? The agent will be refused this tool.`)) return;
    setBusy(c.tool_key);
    try {
      await callJson(`${base}/${encodeURIComponent(c.id)}`, "DELETE");
      router.refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };
  const payload = (c: Cap, patch: Partial<Cap>) => ({
    tool_key: c.tool_key,
    requires_approval: patch.requires_approval ?? c.requires_approval,
    max_taint: patch.max_taint ?? c.max_taint,
    constraints: patch.constraints ?? c.constraints,
  });

  return (
    <>
      {error && <div className="error">{error}</div>}
      <section className="k-card">
        <div className="k-card-head">
          <h3>Tools</h3>
          <div className="k-card-action">
            <select className="k-select" value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="Tool to add">
              <option value="">Add a tool…</option>
              {tools
                .filter((t) => !granted.has(t.key))
                .map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.name || t.key}
                  </option>
                ))}
              {adding && !tools.some((t) => t.key === adding) && !granted.has(adding) && <option value={adding}>{adding}</option>}
            </select>
            {adding && (
              <button
                className="k-btn-primary"
                disabled={busy === adding}
                onClick={async () => {
                  await save(adding, { tool_key: adding, requires_approval: false, max_taint: "user", constraints: {} });
                  setAdding("");
                }}
              >
                Allow
              </button>
            )}
          </div>
        </div>
        <div className="k-card-body" style={{ padding: "8px 0 0", overflowX: "auto" }}>
          {capabilities.length === 0 ? (
            <div className="k-empty">No tools allowed. Every tool call is refused.</div>
          ) : (
            <table className="k-table">
              <thead>
                <tr>
                  <th style={{ paddingLeft: 16 }}>Tool</th>
                  <th className="tight">Risk</th>
                  <th className="tight">Permission</th>
                  <th>Limits</th>
                  <th className="tight">Accepts values from</th>
                  <th className="num">Calls</th>
                  <th className="tight">Last used</th>
                  <th className="tight" style={{ paddingRight: 16 }} />
                </tr>
              </thead>
              <tbody>
                {capabilities.map((c) => (
                  <tr key={c.id} style={{ opacity: busy === c.tool_key ? 0.5 : 1 }}>
                    <td style={{ paddingLeft: 16 }}>
                      <span className="k-name">
                        {c.tool?.name || (c.tool_key.endsWith(".*") ? `All ${c.tool_key.slice(0, -2)} tools` : c.tool_key)}
                      </span>
                      <span className="sub k-mono">{c.tool_key}</span>
                    </td>
                    <td className="tight">
                      <span className={`k-pill k-pill-${impactTone(c.tool?.impact)}`}>
                        {IMPACT[c.tool?.impact || ""] || (c.tool_key.includes("*") ? "Mixed" : "Not declared")}
                      </span>
                    </td>
                    <td className="tight">
                      <div className="k-seg" role="group" aria-label="Permission">
                        <button className={!c.requires_approval ? "active" : ""} onClick={() => c.requires_approval && save(c.tool_key, payload(c, { requires_approval: false }))}>
                          Allowed
                        </button>
                        <button className={c.requires_approval ? "active" : ""} onClick={() => !c.requires_approval && save(c.tool_key, payload(c, { requires_approval: true }))}>
                          Ask first
                        </button>
                      </div>
                    </td>
                    <td>
                      {editing === c.id ? (
                        <LimitsForm
                          initial={c.constraints}
                          onCancel={() => setEditing("")}
                          onSave={async (constraints) => {
                            await save(c.tool_key, payload(c, { constraints }));
                            setEditing("");
                          }}
                        />
                      ) : (
                        <button className="k-limits" onClick={() => setEditing(c.id)}>
                          {limitsText(c.constraints).length ? (
                            limitsText(c.constraints).map((l) => (
                              <span key={l} className="k-pill k-pill-outline">
                                {l}
                              </span>
                            ))
                          ) : (
                            <span className="k-muted">No limits · add</span>
                          )}
                        </button>
                      )}
                    </td>
                    <td className="tight">
                      <select
                        className="k-select"
                        value={c.max_taint}
                        aria-label="Accepts values from"
                        onChange={(e) => save(c.tool_key, payload(c, { max_taint: e.target.value }))}
                      >
                        {TRUST.map((t) => (
                          <option key={t.key} value={t.key}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="num">
                      {c.usage.calls}
                      {(c.usage.blocked > 0 || c.usage.held > 0) && (
                        <span className="sub">
                          {c.usage.blocked} blocked · {c.usage.held} held
                        </span>
                      )}
                    </td>
                    <td className="tight muted">
                      {unused.includes(c.id) ? <span className="k-pill k-pill-outline">Unused</span> : ago(c.usage.last_used)}
                    </td>
                    <td className="tight" style={{ paddingRight: 16 }}>
                      <button className="k-btn-ghost" onClick={() => remove(c)} aria-label={`Remove ${c.tool_key}`}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {tried.length > 0 && (
        <section className="k-card">
          <div className="k-card-head">
            <h3>Tried but not allowed</h3>
          </div>
          <div className="k-card-body" style={{ padding: "4px 0 0" }}>
            <ul className="k-list">
              {tried.map((t) => (
                <li key={t.tool_key}>
                  <div className="k-list-main">
                    <span className="k-mono">{t.tool_key}</span>
                    <span className="muted">
                      Refused {t.count}× · last {ago(t.last)}
                    </span>
                  </div>
                  <div className="k-list-end">
                    <button className="k-btn" disabled={busy === t.tool_key} onClick={() => save(t.tool_key, { tool_key: t.tool_key, requires_approval: true, max_taint: "user", constraints: {} })}>
                      Allow with approval
                    </button>
                    <button className="k-btn-primary" disabled={busy === t.tool_key} onClick={() => save(t.tool_key, { tool_key: t.tool_key, requires_approval: false, max_taint: "user", constraints: {} })}>
                      Allow
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </>
  );
}

function LimitsForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: Record<string, any>;
  onSave: (c: Record<string, any>) => void;
  onCancel: () => void;
}) {
  const rows0: { arg: string; op: string; value: string }[] = [];
  for (const [arg, spec] of Object.entries(initial || {})) {
    if (spec && typeof spec === "object" && !Array.isArray(spec)) {
      for (const [op, v] of Object.entries(spec)) rows0.push({ arg, op, value: Array.isArray(v) ? v.join(", ") : String(v) });
    } else rows0.push({ arg, op: "eq", value: String(spec) });
  }
  const [rows, setRows] = useState(rows0.length ? rows0 : [{ arg: "", op: "lte", value: "" }]);
  const set = (i: number, patch: Partial<(typeof rows)[number]>) => setRows(rows.map((r, j) => (i === j ? { ...r, ...patch } : r)));
  const build = () => {
    const out: Record<string, any> = {};
    for (const r of rows) {
      if (!r.arg.trim() || r.value.trim() === "") continue;
      const list = r.op === "in" || r.op === "not_in";
      const raw = list ? r.value.split(",").map((v) => v.trim()).filter(Boolean) : r.value.trim();
      const value = !list && ["lt", "lte", "gt", "gte"].includes(r.op) && !Number.isNaN(Number(raw)) ? Number(raw) : raw;
      out[r.arg.trim()] = { ...(out[r.arg.trim()] || {}), [r.op]: value };
    }
    return out;
  };
  return (
    <div className="k-limits-form">
      {rows.map((r, i) => (
        <div key={i} className="k-limits-row">
          <input className="k-input" placeholder="argument" value={r.arg} onChange={(e) => set(i, { arg: e.target.value })} aria-label="Argument" />
          <select className="k-select" value={r.op} onChange={(e) => set(i, { op: e.target.value })} aria-label="Operator">
            {OPS.map((o) => (
              <option key={o.op} value={o.op}>
                {o.label}
              </option>
            ))}
          </select>
          <input className="k-input" placeholder="value" value={r.value} onChange={(e) => set(i, { value: e.target.value })} aria-label="Value" />
          <button className="k-btn-ghost" onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label="Remove limit">
            ×
          </button>
        </div>
      ))}
      <div className="k-limits-row">
        <button className="k-btn-ghost" onClick={() => setRows([...rows, { arg: "", op: "lte", value: "" }])}>
          + Limit
        </button>
        <span style={{ flex: 1 }} />
        <button className="k-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button className="k-btn-primary" onClick={() => onSave(build())}>
          Save
        </button>
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { callJson } from "@/components/kit/Act";

/**
 * The fields of a value check: where to look, which value, how to compare it, and
 * against what. "When a refund's amount is more than 500", "Only ship to US or EU".
 */
export type Condition = {
  surface: string;
  tool: string;
  field: string;
  measure: string;
  operator: string;
  value: string;
};

export type ConditionSpec = {
  surface: string;
  tool?: string | null;
  field?: string;
  measure?: string;
  operator: string;
  value?: number | string | (number | string)[] | null;
};

export const WHERE: { key: string; label: string }[] = [
  { key: "tool_args", label: "Tool call" },
  { key: "tool_result", label: "Tool result" },
  { key: "output", label: "Reply" },
  { key: "input", label: "User message" },
];

export const OPERATORS: { key: string; label: string; numeric?: boolean; list?: boolean; none?: boolean }[] = [
  { key: "gt", label: "is more than", numeric: true },
  { key: "gte", label: "is at least", numeric: true },
  { key: "lt", label: "is less than", numeric: true },
  { key: "lte", label: "is at most", numeric: true },
  { key: "eq", label: "is" },
  { key: "ne", label: "is not" },
  { key: "in", label: "is one of", list: true },
  { key: "not_in", label: "is not one of", list: true },
  { key: "contains", label: "contains" },
  { key: "not_contains", label: "does not contain" },
  { key: "matches", label: "matches pattern" },
  { key: "exists", label: "is present", none: true },
  { key: "missing", label: "is missing", none: true },
];

const MEASURES = [
  { key: "value", label: "Its value" },
  { key: "length", label: "Its length" },
  { key: "number", label: "The first number in it" },
];

const isTool = (surface: string) => surface === "tool_args" || surface === "tool_result";
const opOf = (key: string) => OPERATORS.find((o) => o.key === key) || OPERATORS[0];

export function blankCondition(operator?: string): Condition {
  return { surface: "tool_args", tool: "", field: "", measure: "value", operator: OPERATORS.some((o) => o.key === operator) ? operator! : "gt", value: "" };
}

export function conditionFrom(spec?: ConditionSpec | null): Condition {
  if (!spec) return blankCondition();
  const v = spec.value;
  return {
    surface: spec.surface || "tool_args",
    tool: spec.tool || "",
    field: spec.field || "",
    measure: spec.measure || "value",
    operator: spec.operator || "gt",
    value: Array.isArray(v) ? v.join(", ") : v === null || v === undefined ? "" : String(v),
  };
}

export function conditionSpec(c: Condition): ConditionSpec {
  const op = opOf(c.operator);
  const value = op.none
    ? null
    : op.list
      ? c.value
          .split(/\n|,/)
          .map((x) => x.trim())
          .filter(Boolean)
      : c.value.trim();
  return {
    surface: c.surface,
    tool: isTool(c.surface) ? c.tool.trim() || null : null,
    field: c.field.trim(),
    measure: c.measure,
    operator: c.operator,
    value,
  };
}

export function conditionReady(c: Condition): boolean {
  const op = opOf(c.operator);
  if (op.none) return Boolean(c.field.trim());
  // A whole tool call is JSON text: only a text comparison means anything without a field.
  if (isTool(c.surface) && !c.field.trim() && (c.measure !== "value" || !["contains", "not_contains", "matches"].includes(c.operator))) return false;
  return Boolean(c.value.trim());
}

/** Masking rewrites a span of text, so it is offered for replies and user messages. */
export const canMask = (c: Condition) => !isTool(c.surface);

function noun(tool: string): string {
  const parts = tool.split(".").filter((p) => p && p !== "*" && !p.includes("*"));
  return (parts[parts.length - 1] || "").replace(/[_-]+/g, " ");
}

const ACTION_WORDS: Record<string, string> = { block: "block it", escalate: "ask a person", redact: "mask it", allow: "log it" };

/** One line of plain English: "When a refund's amount is more than 500, ask a person". */
export function describeCondition(c: Condition, effect?: string): string {
  const field = c.field.trim();
  let subject: string;
  if (isTool(c.surface)) {
    const n = noun(c.tool.trim());
    const base = c.surface === "tool_args" ? (n ? `a ${n}` : "a tool call") : n ? `a ${n} result` : "a tool result";
    subject = field ? `${base}'s ${field}` : base;
  } else {
    const base = c.surface === "output" ? "the reply" : "the user's message";
    subject = field ? `${base}'s ${field}` : base;
  }
  if (c.measure === "length") subject = `the length of ${subject}`;
  if (c.measure === "number") subject = `the first number in ${subject}`;
  const op = opOf(c.operator);
  const value = op.none ? "" : op.list ? c.value.split(/\n|,/).map((x) => x.trim()).filter(Boolean).join(", ") : c.operator === "matches" ? `/${c.value.trim()}/` : c.value.trim();
  const then = effect ? `, ${ACTION_WORDS[effect] || effect}` : "";
  return `When ${subject} ${op.label}${op.none ? "" : ` ${value && value !== "//" ? value : "…"}`}${then}`;
}

export function ConditionFields({ value, onChange }: { value: Condition; onChange: (c: Condition) => void }) {
  const [tools, setTools] = useState<string[]>([]);
  const [fields, setFields] = useState<string[]>([]);
  const set = (patch: Partial<Condition>) => onChange({ ...value, ...patch });
  const tool = isTool(value.surface);

  useEffect(() => {
    callJson("/api/tools", "GET")
      .then((d) => setTools((d.tools || []).map((t: any) => t.key).filter((k: string) => !k.startsWith("redteam."))))
      .catch(() => setTools([]));
  }, []);

  // The tool's known arguments, offered as fields. Nothing to offer for a glob.
  useEffect(() => {
    const t = value.tool.trim();
    if (!tool || !t || t.includes("*")) {
      setFields([]);
      return;
    }
    let live = true;
    callJson(`/api/custom-rules/fields?tool=${encodeURIComponent(t)}`, "GET")
      .then((d) => live && setFields(d.fields || []))
      .catch(() => live && setFields([]));
    return () => {
      live = false;
    };
  }, [tool, value.tool]);

  const ops = value.measure === "value" ? OPERATORS : OPERATORS.filter((o) => o.numeric || o.key === "eq" || o.key === "ne");
  const op = opOf(value.operator);

  const numberValue = op.numeric || value.measure !== "value";

  return (
    <>
      <div className="k-field">
        <label>Check</label>
        <div className="k-seg" role="group" aria-label="Where to check">
          {WHERE.map((w) => (
            <button key={w.key} className={value.surface === w.key ? "active" : ""} aria-pressed={value.surface === w.key} onClick={() => set({ surface: w.key })}>
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {tool && (
        <div className="k-field">
          <label htmlFor="cc-tool">Tool</label>
          <input id="cc-tool" className="k-input k-mono" list="cc-tools" value={value.tool} onChange={(e) => set({ tool: e.target.value })} placeholder="Any tool, or payments.*" />
          <datalist id="cc-tools">
            {tools.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </div>
      )}

      <div className="k-field">
        <label htmlFor="cc-field">{tool ? "Field" : "Field (optional)"}</label>
        <input
          id="cc-field"
          className="k-input k-mono"
          list="cc-fields"
          value={value.field}
          onChange={(e) => set({ field: e.target.value })}
          placeholder={tool ? "amount, refund.total, items.*.price" : "Empty means the whole text"}
        />
        <datalist id="cc-fields">
          {fields.map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>
      </div>

      <div className="k-field">
        <label htmlFor="cc-op">Rule</label>
        <div className="k-pills" style={{ gap: 8, flexWrap: "wrap" }}>
          <select
            className="k-select"
            aria-label="What to compare"
            value={value.measure}
            onChange={(e) => {
              const measure = e.target.value;
              const keep = measure === "value" || opOf(value.operator).numeric || ["eq", "ne"].includes(value.operator);
              set({ measure, operator: keep ? value.operator : "gt" });
            }}
          >
            {MEASURES.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
          <select id="cc-op" className="k-select" value={value.operator} onChange={(e) => set({ operator: e.target.value })}>
            {ops.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
          {!op.none && (
            <input
              className={`k-input${op.key === "matches" ? " k-mono" : ""}`}
              style={{ flex: 1, minWidth: 160 }}
              aria-label={op.list ? "Values, comma separated" : numberValue ? "Number" : op.key === "matches" ? "Pattern" : "Value"}
              inputMode={numberValue ? "decimal" : undefined}
              value={value.value}
              onChange={(e) => set({ value: e.target.value })}
              placeholder={op.list ? "us, eu" : numberValue ? "500" : op.key === "matches" ? "@acme\\.com$" : "Value"}
            />
          )}
        </div>
      </div>
    </>
  );
}

"use client";

import { useEffect, useState } from "react";
import { callJson } from "@/components/kit/Act";

/**
 * Pick one of the registered validators (`/api/validators`) and fill in its settings.
 * The settings form is drawn from the validator's own schema, so a validator added
 * later, ours or a plug-in, needs no change here.
 */
export type ValidatorInfo = {
  name: string;
  label: string;
  description: string;
  entity_type: string;
  surfaces: string[];
  kind: "rule" | "model" | "judge";
  params_schema: Schema;
  models: string[];
  upstream: string | null;
  license: string;
  available: boolean;
  unavailable_reason: string;
};

type Schema = {
  properties?: Record<string, Prop>;
  required?: string[];
  $defs?: Record<string, Prop>;
};

type Prop = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  items?: Prop;
  anyOf?: Prop[];
  minimum?: number;
  maximum?: number;
  $ref?: string;
};

export type ValidatorValue = { name: string; params: Record<string, string | boolean> };

const KIND_LABEL: Record<ValidatorInfo["kind"], string> = {
  rule: "Rules",
  model: "Local models",
  judge: "LLM judges",
};

/** The concrete type of a property, looking through `X | None`. */
function shape(p: Prop): { type: string; nullable: boolean; enumValues?: unknown[]; item?: string } {
  const options = p.anyOf ?? [p];
  const nullable = options.some((o) => o.type === "null");
  const main = options.find((o) => o.type !== "null") ?? p;
  return {
    type: main.enum ? "enum" : main.type ?? "string",
    nullable,
    enumValues: main.enum,
    item: main.items?.type,
  };
}

const human = (key: string) => key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** The form's text values as the JSON the validator's schema expects. */
export function paramsFor(info: ValidatorInfo | undefined, raw: Record<string, string | boolean>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(info?.params_schema.properties ?? {})) {
    const value = raw[key];
    const s = shape(prop);
    if (value === undefined || value === "") continue;
    if (s.type === "boolean") out[key] = Boolean(value);
    else if (s.type === "array")
      out[key] = String(value)
        .split("\n")
        .map((x) => x.trim())
        .filter(Boolean)
        .map((x) => (s.item === "number" || s.item === "integer" ? Number(x) : x));
    else if (s.type === "number" || s.type === "integer") out[key] = Number(value);
    else if (s.type === "object") {
      try {
        out[key] = JSON.parse(String(value));
      } catch {
        out[key] = value;
      }
    } else out[key] = value;
  }
  return out;
}

/** Whether every required setting has a value. */
export function validatorReady(info: ValidatorInfo | undefined, raw: Record<string, string | boolean>): boolean {
  if (!info) return false;
  return (info.params_schema.required ?? []).every((k) => raw[k] !== undefined && String(raw[k]).trim() !== "");
}

/** Form values from saved settings, for editing a rule. */
export function rawFrom(params: Record<string, unknown> | undefined): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === null || v === undefined) continue;
    out[k] = typeof v === "boolean" ? v : Array.isArray(v) ? v.join("\n") : typeof v === "object" ? JSON.stringify(v) : String(v);
  }
  return out;
}

export function useValidators(): ValidatorInfo[] | null {
  const [list, setList] = useState<ValidatorInfo[] | null>(null);
  useEffect(() => {
    callJson("/api/validators", "GET")
      .then((d) => setList(d.validators || []))
      .catch(() => setList([]));
  }, []);
  return list;
}

export function ValidatorFields({
  validators,
  value,
  onChange,
}: {
  validators: ValidatorInfo[] | null;
  value: ValidatorValue;
  onChange: (v: ValidatorValue) => void;
}) {
  if (validators === null) return <p className="muted">Loading checks…</p>;
  if (!validators.length) return <p className="muted">No checks are registered on this server.</p>;
  const info = validators.find((v) => v.name === value.name);
  // What runs here first, by kind; what needs setup on this server last, so the list
  // a person scans is the list they can use.
  const groups: (readonly [string, ValidatorInfo[]])[] = [
    ...(["rule", "model", "judge"] as const).map((k) => [KIND_LABEL[k], validators.filter((v) => v.kind === k && v.available)] as const),
    ["Needs setup on this server", validators.filter((v) => !v.available)] as const,
  ];

  return (
    <>
      <div className="k-field">
        <label htmlFor="cr-validator">What to check</label>
        <select
          id="cr-validator"
          className="k-input"
          value={value.name}
          onChange={(e) => onChange({ name: e.target.value, params: {} })}
        >
          <option value="">Choose a check…</option>
          {groups.map(([label, items]) =>
            items.length ? (
              <optgroup key={label} label={label}>
                {items.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.label}
                  </option>
                ))}
              </optgroup>
            ) : null,
          )}
        </select>
      </div>

      {info && (
        <>
          {info.description && <p className="muted">{info.description}</p>}
          {!info.available && <div className="error">Can't run on this server: {info.unavailable_reason}</div>}
          {Object.entries(info.params_schema.properties ?? {}).map(([key, prop]) => {
            const s = shape(prop);
            const id = `cr-p-${key}`;
            // Pydantic titles every field ("Min Overlap Words"); the key in plain case reads better.
            const label = human(key);
            const required = (info.params_schema.required ?? []).includes(key);
            const set = (v: string | boolean) => onChange({ ...value, params: { ...value.params, [key]: v } });
            const current = value.params[key];
            const placeholder = prop.default !== undefined && prop.default !== null ? String(Array.isArray(prop.default) ? prop.default.join(", ") : prop.default) : "";
            if (s.type === "boolean")
              return (
                <label key={key} className="k-check">
                  <input type="checkbox" checked={current === undefined ? Boolean(prop.default) : Boolean(current)} onChange={(e) => set(e.target.checked)} /> {label}
                </label>
              );
            return (
              <div key={key} className="k-field">
                <label htmlFor={id}>
                  {label}
                  {s.type === "array" ? ", one per line" : ""}
                  {required ? "" : " (optional)"}
                </label>
                {s.type === "enum" ? (
                  <select id={id} className="k-input" value={String(current ?? prop.default ?? "")} onChange={(e) => set(e.target.value)}>
                    {(s.enumValues ?? []).map((o) => (
                      <option key={String(o)} value={String(o)}>
                        {String(o)}
                      </option>
                    ))}
                  </select>
                ) : s.type === "array" || s.type === "object" || (s.type === "string" && /prompt|document|text|source/.test(key)) ? (
                  <textarea id={id} className="k-input" rows={s.type === "array" ? 4 : 3} value={String(current ?? "")} placeholder={placeholder} onChange={(e) => set(e.target.value)} />
                ) : (
                  <input
                    id={id}
                    className="k-input"
                    type={s.type === "number" || s.type === "integer" ? "number" : "text"}
                    step={s.type === "integer" ? 1 : "any"}
                    value={String(current ?? "")}
                    placeholder={placeholder}
                    onChange={(e) => set(e.target.value)}
                  />
                )}
                {prop.description && <span className="muted">{prop.description}</span>}
              </div>
            );
          })}
          {info.upstream && (
            <p className="muted">
              Adapted from {info.upstream} ({info.license}).
              {info.models.length ? ` Uses ${info.models.join(", ")}.` : ""}
            </p>
          )}
        </>
      )}
    </>
  );
}

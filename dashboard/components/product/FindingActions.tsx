"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { callJson } from "@/components/kit/Act";

export type RemedyField = {
  name: string;
  label: string;
  kind: "text" | "email" | "select";
  required: boolean;
  options: { value: string; label: string }[];
  placeholder: string;
  default: string;
};

export type Remedy = {
  key: string;
  label: string;
  kind: "action" | "link";
  href?: string | null;
  fields: RemedyField[];
  confirm?: string;
  primary?: boolean;
  hint?: string;
  allowed?: boolean;
};

function Action({ findingId, remedy, onDone }: { findingId: string; remedy: Remedy; onDone: (msg: string) => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(remedy.fields.map((f) => [f.name, f.default || ""])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const missing = remedy.fields.some((f) => f.required && !values[f.name]?.trim());

  const run = async () => {
    if (remedy.confirm && !window.confirm(remedy.confirm)) return;
    setBusy(true);
    setError("");
    try {
      const r = await callJson(`/api/findings/${encodeURIComponent(findingId)}/remedies/${encodeURIComponent(remedy.key)}`, "POST", { inputs: values });
      onDone(r.resolved ? `${r.message} Issue resolved.` : r.message);
    } catch (e: any) {
      setError(e.message || "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li>
      <div className="k-list-main">
        <span>{remedy.hint || remedy.label}</span>
        {error && (
          <span className="k-act-error" role="alert">
            {error}
          </span>
        )}
      </div>
      <div className="k-list-end" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
        {remedy.fields.map((f) =>
          f.kind === "select" ? (
            <select key={f.name} className="k-select" value={values[f.name]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} aria-label={f.label}>
              {!f.default && <option value="">{f.label}</option>}
              {f.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : (
            <input
              key={f.name}
              className="k-input"
              type={f.kind === "email" ? "email" : "text"}
              value={values[f.name]}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
              placeholder={f.placeholder || f.label}
              aria-label={f.label}
              style={{ width: 220 }}
            />
          ),
        )}
        <button
          type="button"
          className={remedy.primary ? "k-btn-primary" : "k-btn"}
          disabled={busy || missing || remedy.allowed === false}
          onClick={run}
          title={remedy.allowed === false ? "Your role cannot do this" : undefined}
        >
          {busy ? "…" : remedy.label}
        </button>
      </div>
    </li>
  );
}

/**
 * What can be done about an issue, from the issue. Actions run on the platform and
 * are audited; the issue closes itself when the condition it is about has cleared.
 * Links go to where the fix is made.
 */
export function FindingActions({ findingId, remedies }: { findingId: string; remedies: Remedy[] }) {
  const router = useRouter();
  const [done, setDone] = useState("");
  const actions = remedies.filter((r) => r.kind === "action").sort((a, b) => Number(!!b.primary) - Number(!!a.primary));
  const links = remedies.filter((r) => r.kind === "link");
  return (
    <>
      {done && (
        <div className="note-panel" style={{ margin: "0 0 10px" }}>
          {done}
        </div>
      )}
      {actions.length > 0 && (
        <ul className="k-list" style={{ margin: "-4px -14px 0" }}>
          {actions.map((r) => (
            <Action
              key={r.key}
              findingId={findingId}
              remedy={r}
              onDone={(msg) => {
                setDone(msg);
                router.refresh();
              }}
            />
          ))}
        </ul>
      )}
      {links.length > 0 && (
        <div className="k-pills" style={{ gap: 8, marginTop: actions.length ? 12 : 0, flexWrap: "wrap" }}>
          {links.map((r) => (
            <Link key={r.key} href={r.href || "#"} className={actions.length || !r.primary ? "k-btn-ghost" : "k-btn"}>
              {r.label}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

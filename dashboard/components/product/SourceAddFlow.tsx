"use client";

import { useState } from "react";
import { TIER_OPTIONS, FRESHNESS_OPTIONS, inputStyle } from "@/lib/product/sourceOptions";
import { DatabaseFields, ApiFields } from "./ConnectionFields";

type SourceType = "register" | "database" | "api";

const TYPE_OPTIONS: { value: SourceType; label: string; blurb: string }[] = [
  {
    value: "register",
    label: "Just a name",
    blurb: "Register it now with a trust tier — connect it for real validation later.",
  },
  {
    value: "database",
    label: "Database",
    blurb: "PostgreSQL, MySQL, SQL Server, or SQLite — we fingerprint a table to detect drift.",
  },
  {
    value: "api",
    label: "API or knowledge base",
    blurb: "Confluence, SharePoint, Notion, or any authenticated REST endpoint.",
  },
];

/**
 * One flow, type first — replaces three parallel cards (register / connect a
 * database / connect an API) that made every visitor read three forms to figure
 * out which one applied to them. Picking a type here only changes which extra
 * fields appear below the name/tier fields every source needs; submit posts
 * once to /api/sources/add, which registers the source and (if a type other
 * than "just a name" was picked) attaches the connection in the same request.
 */
export function SourceAddFlow() {
  const [type, setType] = useState<SourceType>("register");

  return (
    <form action="/api/sources/add" method="POST" className="body stack">
      <input type="hidden" name="source_type" value={type} />

      <div>
        <label className="small muted" style={{ display: "block", marginBottom: 6 }}>
          What are you adding?
        </label>
        <div className="segmented" role="radiogroup">
          {TYPE_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              className={`segmented-option${type === o.value ? " active" : ""}`}
              aria-pressed={type === o.value}
              onClick={() => setType(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <p className="small muted" style={{ marginTop: 6, marginBottom: 0 }}>
          {TYPE_OPTIONS.find((o) => o.value === type)?.blurb}
        </p>
      </div>

      <div className="field-grid">
        <div>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Name this source (what your team calls it)
          </label>
          <input
            type="text"
            name="key"
            required
            placeholder="e.g. price-book, help-center-articles"
            style={inputStyle}
          />
        </div>

        <div>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            What kind of source is it?
          </label>
          <select name="tier" defaultValue="unverified" style={inputStyle}>
            {TIER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Who owns it? (email)
          </label>
          <input type="email" name="owner" placeholder="finance@yourcompany.com" style={inputStyle} />
        </div>

        <div>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            How often is it updated?
          </label>
          <select name="freshness_sla_hours" defaultValue="" style={inputStyle}>
            {FRESHNESS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {type === "database" && (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <DatabaseFields />
        </div>
      )}

      {type === "api" && (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <ApiFields />
        </div>
      )}

      <div>
        <button type="submit" className="btn-primary">
          {type === "register" ? "Add source" : "Add & connect source"}
        </button>
      </div>
    </form>
  );
}

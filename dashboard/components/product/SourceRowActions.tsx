"use client";

import { useEffect, useRef, useState } from "react";
import { TIER_OPTIONS, FRESHNESS_OPTIONS, inputStyle, sourceKind } from "@/lib/product/sourceOptions";
import { DatabaseFields, ApiFields } from "./ConnectionFields";

type Panel = "menu" | "edit" | "connect" | null;
type ConnectionType = "database" | "api";

/**
 * Replaces the old actions cell — a bare native `<details>/<summary>` for Edit
 * (which renders unstyled and forces the table row to grow in place) plus two
 * more buttons crammed into the same cell, wrapping unpredictably at narrow
 * widths. This is one "⋯" trigger; its popover swaps between a short menu, an
 * edit form, and a connect form, so the row itself never changes height.
 */
export function SourceRowActions({ source }: { source: any }) {
  const [panel, setPanel] = useState<Panel>(null);
  const [connectionType, setConnectionType] = useState<ConnectionType>("database");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!panel) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setPanel(null);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [panel]);

  // What this source IS decides what the menu may offer. See sourceKind's own
  // comment: two of the four actions are impossible for some rows, and the page
  // already says so in its column tooltips.
  const kind = sourceKind(source);
  const connected = kind === "connected";

  return (
    <div className="row-menu" ref={ref}>
      <button
        type="button"
        className="row-menu-trigger"
        aria-label={`Actions for ${source.key}`}
        aria-expanded={panel !== null}
        onClick={() => setPanel((p) => (p ? null : "menu"))}
      >
        ⋯
      </button>

      {panel === "menu" && (
        <div className="row-menu-popover" role="menu">
          <button type="button" className="row-menu-item" onClick={() => setPanel("edit")}>
            Edit details
          </button>
          {/* A plain http(s) key is fetched directly and has nothing to connect
              to, so this is offered only where it changes something: an opaque
              key that cannot be checked at all without one, or a re-point of an
              existing connection. */}
          {kind !== "url" && (
            <button type="button" className="row-menu-item" onClick={() => setPanel("connect")}>
              {connected ? "Reconnect" : "Connect a database or API"}
            </button>
          )}
          {/* Validation fetches the source and compares the content. With an
              opaque key and no connection there is nothing to fetch, so the
              button's only possible outcome is the failure the content-check
              column is already reporting. The reason is shown in its place —
              a disabled control that does not say why is its own small puzzle. */}
          {kind === "opaque" ? (
            <div className="row-menu-note">
              Can&rsquo;t be validated: the key is not a URL and no connection is
              registered. Connect one to make this checkable.
            </div>
          ) : (
            <form action="/api/sources/validate" method="POST">
              <input type="hidden" name="key" value={source.key} />
              <button type="submit" className="row-menu-item">
                Validate now
              </button>
            </form>
          )}
          <div className="row-menu-divider" />
          {!source.deprecated ? (
            <form action="/api/sources/deprecate" method="POST">
              <input type="hidden" name="key" value={source.key} />
              <button type="submit" className="row-menu-item bad">
                Deprecate
              </button>
            </form>
          ) : (
            <form action="/api/sources/delete" method="POST">
              <input type="hidden" name="key" value={source.key} />
              <button
                type="submit"
                className="row-menu-item bad"
                title="Permanently removes the record. Unlike deprecating, this drops the 'do not trust' signal — an answer grounded in it afterward looks unverified, not flagged"
              >
                Delete permanently
              </button>
            </form>
          )}
        </div>
      )}

      {panel === "edit" && (
        <div className="row-menu-popover row-menu-form">
          <div className="row-menu-form-title">Edit {source.key}</div>
          {/* What a source IS is not editable here and was not shown here either,
              so the form asked for a freshness SLA without saying whether anything
              could ever enforce it. One line, stating the kind, so the fields
              below are read in context. */}
          <div className="row-menu-kind">
            {kind === "url" && <>Fetched directly from its URL.</>}
            {kind === "connected" && (
              <>
                Reached through the registered{" "}
                {source.connection_kind === "database" ? "database" : "API"} connection.
              </>
            )}
            {kind === "opaque" && <>Not reachable — a name with no connection behind it.</>}
          </div>
          <form action="/api/sources" method="POST" className="stack">
            <input type="hidden" name="key" value={source.key} />
            <label className="small muted" style={{ display: "block" }}>
              Tier
              <select name="tier" defaultValue={source.tier} style={inputStyle}>
                {TIER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="small muted" style={{ display: "block" }}>
              Owner (email)
              <input type="email" name="owner" defaultValue={source.owner || ""} style={inputStyle} />
            </label>
            <label className="small muted" style={{ display: "block" }}>
              Domain / corpus
              <input type="text" name="domain" defaultValue={source.domain || ""} style={inputStyle} />
            </label>
            {/* A freshness SLA is a promise something checks. For an opaque key
                with no connection nothing can, so offering the field would be
                collecting a commitment this product cannot keep — it says what
                would make it enforceable instead. */}
            {kind === "opaque" ? (
              <div className="row-menu-note">
                A freshness SLA needs something that can re-read the source. Connect a
                database or API and this becomes available.
              </div>
            ) : (
              <label className="small muted" style={{ display: "block" }}>
                Freshness SLA
                <select
                  name="freshness_sla_hours"
                  defaultValue={source.freshness_sla_hours ? String(source.freshness_sla_hours) : ""}
                  style={inputStyle}
                >
                  {FRESHNESS_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {source.deprecated && (
              <label className="small muted" style={{ display: "block" }}>
                Status
                <select name="deprecated" defaultValue="true" style={inputStyle}>
                  <option value="true">Stay deprecated</option>
                  <option value="false">Un-deprecate — bring back into rotation</option>
                </select>
              </label>
            )}
            <div className="row" style={{ gap: 8 }}>
              <button type="submit" className="btn-primary" style={{ fontSize: "var(--t-micro)" }}>
                Save
              </button>
              <button type="button" className="btn-cancel" onClick={() => setPanel(null)}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {panel === "connect" && (
        <div className="row-menu-popover row-menu-form">
          <div className="row-menu-form-title">
            {connected ? "Reconnect" : "Connect"} {source.key}
          </div>
          <form action="/api/sources/connections" method="POST" className="stack">
            <input type="hidden" name="key" value={source.key} />
            <input type="hidden" name="kind" value={connectionType} />
            <div className="segmented" role="radiogroup" style={{ marginBottom: 2 }}>
              <button
                type="button"
                className={`segmented-option${connectionType === "database" ? " active" : ""}`}
                aria-pressed={connectionType === "database"}
                onClick={() => setConnectionType("database")}
              >
                Database
              </button>
              <button
                type="button"
                className={`segmented-option${connectionType === "api" ? " active" : ""}`}
                aria-pressed={connectionType === "api"}
                onClick={() => setConnectionType("api")}
              >
                API / knowledge base
              </button>
            </div>
            {connectionType === "database" ? <DatabaseFields /> : <ApiFields />}
            <div className="row" style={{ gap: 8 }}>
              <button type="submit" className="btn-primary" style={{ fontSize: "var(--t-micro)" }}>
                Connect
              </button>
              <button type="button" className="btn-cancel" onClick={() => setPanel(null)}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

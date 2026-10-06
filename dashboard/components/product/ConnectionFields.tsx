"use client";

import { inputStyle } from "@/lib/product/sourceOptions";

/** The fields a database connection needs — shared by the add-source flow and
 * the per-row "Connect" action so the two don't drift apart. */
export function DatabaseFields() {
  return (
    <div className="stack">
      <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 140 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Dialect
          </label>
          <select name="dialect" defaultValue="postgresql" style={inputStyle}>
            <option value="postgresql">PostgreSQL</option>
            <option value="mysql">MySQL</option>
            <option value="mssql">SQL Server</option>
            <option value="sqlite">SQLite</option>
          </select>
        </div>
        <div style={{ flex: 2, minWidth: 200 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Host
          </label>
          <input type="text" name="host" placeholder="db.internal.yourcompany.com" style={inputStyle} />
        </div>
        <div style={{ flex: 1, minWidth: 100 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Port
          </label>
          <input type="number" name="port" placeholder="5432" style={inputStyle} />
        </div>
      </div>
      <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 160 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Database name
          </label>
          <input type="text" name="database" style={inputStyle} />
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Username
          </label>
          <input type="text" name="username" style={inputStyle} />
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Password
          </label>
          <input type="password" name="credential" autoComplete="new-password" style={inputStyle} />
        </div>
      </div>
      <div>
        <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
          Table to fingerprint (optional — otherwise every table name is used)
        </label>
        <input type="text" name="check_table" placeholder="customers" style={inputStyle} />
      </div>
    </div>
  );
}

/** The fields an enterprise-API/knowledge-base connection needs. */
export function ApiFields() {
  return (
    <div className="stack">
      <div>
        <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
          API URL to check (a page, space, or search endpoint that returns its content)
        </label>
        <input
          type="url"
          name="base_url"
          required
          placeholder="https://yourteam.atlassian.net/wiki/rest/api/content/12345"
          style={inputStyle}
        />
      </div>
      <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 160 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Auth header name
          </label>
          <input type="text" name="auth_header" defaultValue="Authorization" style={inputStyle} />
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            Prefix (if any)
          </label>
          <input type="text" name="auth_prefix" defaultValue="Bearer " style={inputStyle} />
        </div>
        <div style={{ flex: 2, minWidth: 200 }}>
          <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
            API token
          </label>
          <input type="password" name="credential" autoComplete="new-password" style={inputStyle} />
        </div>
      </div>
    </div>
  );
}

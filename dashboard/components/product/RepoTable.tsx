"use client";

import { useMemo, useState } from "react";
import { ts } from "@/components/ui";

type Repo = {
  full_name: string;
  private: boolean;
  default_branch: string;
  description: string;
  updated_at: string;
  owner_type?: string;
  scanned?: boolean;
};

/**
 * A connected GitHub account can easily have 50-100+ repos, most of them not what
 * anyone came here to scan (forks, generator scaffolds, old experiments). A flat
 * table of all of them is a wall of noise, not a picker — this adds a client-side
 * filter so "find my repo" doesn't mean scrolling past ninety others.
 */
export function RepoTable({ repos }: { repos: Repo[] }) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return repos;
    return repos.filter(
      (r) =>
        r.full_name.toLowerCase().includes(q) ||
        (r.description || "").toLowerCase().includes(q),
    );
  }, [repos, query]);

  return (
    <>
      <div className="body" style={{ paddingBottom: 0 }}>
        <input
          type="text"
          placeholder={`Filter ${repos.length} repositories by name…`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{
            width: "100%",
            maxWidth: 360,
            padding: "6px 10px",
            borderRadius: 7,
            border: "1px solid var(--border)",
            background: "var(--panel-2)",
            color: "var(--text)",
            fontSize: "var(--t-small)",
            fontFamily: "inherit",
          }}
        />
      </div>
      {filtered.length === 0 ? (
        <div className="body muted small">No repositories match "{query}".</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Repository</th>
                <th>Account</th>
                <th>Branch</th>
                <th>Updated</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.full_name}>
                  <td>
                    <div>{r.full_name}</div>
                    {r.description && <div className="small muted">{r.description}</div>}
                  </td>
                  <td className="small">
                    <span className={`tag ${r.owner_type === "Organization" ? "ok" : ""}`}>
                      {r.owner_type === "Organization" ? "company account" : "personal account"}
                    </span>
                  </td>
                  <td className="mono small">{r.default_branch}</td>
                  <td className="small muted">{ts(r.updated_at)}</td>
                  <td className="small">
                    {r.scanned ? <span className="tag ok">already scanned</span> : <span className="muted">not scanned</span>}
                  </td>
                  <td>
                    <form action="/api/integrations/github/scan" method="POST">
                      <input type="hidden" name="repo_full_name" value={r.full_name} />
                      <input type="hidden" name="ref" value={r.default_branch} />
                      <button type="submit" className="btn-scan">
                        {r.scanned ? "Scan again" : "Scan"}
                      </button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query && (
        <div className="small muted" style={{ padding: "8px 16px" }}>
          {filtered.length} of {repos.length} repositories
        </div>
      )}
    </>
  );
}

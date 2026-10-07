"use client";

import { useEffect, useState } from "react";
import { Countdown } from "@/components/product/Countdown";

const inputStyle = {
  width: "100%",
  padding: "6px 9px",
  borderRadius: 6,
  border: "1px solid var(--border)",
  background: "var(--panel-2)",
  color: "var(--text)",
  fontSize: "var(--t-small)",
  fontFamily: "inherit",
} as const;

type TokenRow = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
};

export function TokenManager() {
  const [tokens, setTokens] = useState<TokenRow[] | null>(null);
  const [name, setName] = useState("");
  const [minted, setMinted] = useState<{ name: string; token: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    fetch("/api/tokens")
      .then((r) => r.json())
      .then((body) => setTokens(body.tokens || []))
      .catch(() => setError("Could not load tokens."));
  };

  useEffect(load, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name || "self-service" }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Failed to create token");
      setMinted({ name: body.name, token: body.token });
      setName("");
      load();
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: string) => {
    await fetch(`/api/tokens/${id}/revoke`, { method: "POST" });
    load();
  };

  return (
    <>
      {minted && (
        <div className="panel" style={{ marginBottom: 20, borderColor: "var(--ok)" }}>
          <div className="head">
            <span>Your new token — copy it now</span>
          </div>
          <div className="body">
            <p className="small muted" style={{ marginTop: 0 }}>
              This is shown once. It won&apos;t be shown again — if you lose it, revoke it
              and generate a new one.
            </p>
            <div
              className="mono small"
              style={{
                padding: "10px 12px",
                borderRadius: 6,
                background: "var(--panel-2)",
                border: "1px solid var(--border)",
                wordBreak: "break-all",
                userSelect: "all",
              }}
            >
              {minted.token}
            </div>
            <button
              type="button"
              className="btn-primary"
              style={{ marginTop: 10 }}
              onClick={() => navigator.clipboard.writeText(minted.token)}
            >
              Copy to clipboard
            </button>
          </div>
        </div>
      )}

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="head">
          <span>Generate a token</span>
        </div>
        <form onSubmit={create} className="body stack">
          <div>
            <label className="small muted" style={{ display: "block", marginBottom: 4 }}>
              Name (what it's for — e.g. "laptop CLI", "CI runner")
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-laptop"
              style={inputStyle}
            />
          </div>
          {error && <div className="error small">{error}</div>}
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "Generating…" : "Generate token"}
          </button>
        </form>
      </div>

      <div className="panel scroll-x">
        <table>
          <thead>
            <tr>
              <th>name</th>
              <th>prefix</th>
              <th>created</th>
              <th>expires</th>
              <th>status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(tokens || []).map((t) => (
              <tr key={t.id}>
                <td className="small">{t.name || "—"}</td>
                <td className="mono small muted">{t.key_prefix}…</td>
                <td className="small muted">{(t.created_at || "").slice(0, 10)}</td>
                <td>{t.revoked_at ? <span className="muted small">revoked</span> : <Countdown at={t.expires_at} fallback="never" />}</td>
                <td>
                  <span className={`tag ${t.revoked_at ? "bad" : "ok"}`}>
                    {t.revoked_at ? "revoked" : "active"}
                  </span>
                </td>
                <td>
                  {!t.revoked_at && (
                    <button
                      type="button"
                      className="btn-reject"
                      style={{ fontSize: "var(--t-micro)" }}
                      onClick={() => revoke(t.id)}
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {/* `tokens` is null until the fetch resolves, and the empty state only
                covered the loaded-but-empty case — so the first thing anyone saw on
                this tab was a header row over nothing, which reads as broken rather
                than as pending. Both states are covered now, and both say which one
                they are. */}
            {!tokens && (
              <tr>
                <td colSpan={6} className="tbl-note">
                  Loading&hellip;
                </td>
              </tr>
            )}
            {tokens && tokens.length === 0 && (
              <tr>
                <td colSpan={6} className="tbl-note">
                  No tokens yet. Generate one above to use the CLI or the SDK.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

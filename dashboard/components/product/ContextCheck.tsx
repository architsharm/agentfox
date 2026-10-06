"use client";

import { useState } from "react";

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

/**
 * P14 — a dry run against pasted or re-fetched text, same spirit as Sources'
 * "Assess" flow: the ingestion/chunk quality gate existed with a real backend and
 * no way for anyone to actually use it. Paste one document to check for corrupt
 * extraction, or paste chunks (one per line, blank line to separate) to check for
 * boundaries that cut a claim in half.
 */
export function ContextCheck() {
  const [mode, setMode] = useState<"document" | "chunks">("document");
  const [text, setText] = useState("");
  const [chunksText, setChunksText] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const body =
        mode === "document"
          ? { text }
          : { chunks: chunksText.split(/\n\s*\n/).map((c) => c.trim()).filter(Boolean) };
      const res = await fetch("/api/sources/context-check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setResult({ ok: res.ok, ...(await res.json()) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="row" style={{ gap: 8 }}>
        <button
          type="button"
          className={mode === "document" ? "btn-primary" : "btn-scan"}
          onClick={() => setMode("document")}
        >
          Check one document
        </button>
        <button
          type="button"
          className={mode === "chunks" ? "btn-primary" : "btn-scan"}
          onClick={() => setMode("chunks")}
        >
          Check chunk boundaries
        </button>
      </div>

      {mode === "document" ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste extracted document text — checks for encoding damage, mojibake, unbalanced code fences, glued-together words from a lost space glyph."
          rows={8}
          style={{ ...inputStyle, resize: "vertical", fontFamily: "var(--mono)", fontSize: "var(--t-micro)" }}
        />
      ) : (
        <textarea
          value={chunksText}
          onChange={(e) => setChunksText(e.target.value)}
          placeholder={"Paste chunks as they'd reach the retriever, one per paragraph (blank line between chunks) — checks each for orphan fragments, mid-sentence splits, headings with no body."}
          rows={8}
          style={{ ...inputStyle, resize: "vertical", fontFamily: "var(--mono)", fontSize: "var(--t-micro)" }}
        />
      )}

      <div>
        <button type="button" className="btn-primary" onClick={run} disabled={busy || (mode === "document" ? !text.trim() : !chunksText.trim())}>
          Check
        </button>
      </div>

      {result && (
        <div className={result.ok === false ? "error" : "note-panel"}>
          {result.ok === false ? (
            <>
              <strong>Check failed</strong> — {result.detail || "unknown error"}
            </>
          ) : result.document ? (
            <>
              <strong>{result.document.usable ? "Usable" : "Would be rejected"}</strong> — score{" "}
              {result.document.score}
              {result.document.findings.length === 0 ? (
                <div className="small muted" style={{ marginTop: 6 }}>No defects found.</div>
              ) : (
                <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {result.document.findings.map((f: any, i: number) => (
                    <li key={i}>
                      <span className={`tag ${f.severity === "reject" ? "bad" : f.severity === "degraded" ? "warn" : ""}`}>
                        {f.severity}
                      </span>{" "}
                      {f.detail}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : result.chunks ? (
            <>
              <strong>{result.chunks.count} chunk(s) checked</strong>
              {result.chunks.findings.length === 0 ? (
                <div className="small muted" style={{ marginTop: 6 }}>No boundary defects found.</div>
              ) : (
                <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {result.chunks.findings.map((f: any, i: number) => (
                    <li key={i}>
                      <span className={`tag ${f.severity === "reject" ? "bad" : f.severity === "degraded" ? "warn" : ""}`}>
                        {f.severity}
                      </span>{" "}
                      {f.detail}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

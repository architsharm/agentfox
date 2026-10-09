"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useState, type ReactNode } from "react";
import { callJson } from "@/components/kit/Act";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { PATHS, PATH_NOTE, SAME_DB, SAME_DB_NOTE, snippetsFor, type PathKey } from "@/components/product/start/snippets";

/**
 * The browser half of Get started. A key created in step 2 is held here, in
 * memory only, so step 3 can use it for the test request and show the export
 * line, without the key ever going into a URL or storage.
 */
const KeyContext = createContext<{ token: string | null; setToken: (t: string) => void }>({
  token: null,
  setToken: () => {},
});

export function StartKeyProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  return <KeyContext.Provider value={{ token, setToken }}>{children}</KeyContext.Provider>;
}

/**
 * One checklist step. Open state is the user's after the first render: a refresh
 * that ticks a step (the test request does one) must not snap shut the step they
 * are reading, with its result in it.
 */
export function StepDetails({ defaultOpen, summary, children }: { defaultOpen: boolean; summary: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>{summary}</summary>
      {children}
    </details>
  );
}

const SLUG = /^[a-z0-9][a-z0-9-]{1,62}$/;

/** Step 1: register an agent, or pick which registered one the next steps are for. */
export function RegisterAgent({ agents, current }: { agents: string[]; current: string | null }) {
  const router = useRouter();
  const [adding, setAdding] = useState(agents.length === 0);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const s = slug.trim().toLowerCase();
    if (!SLUG.test(s)) {
      setError("Use lowercase letters, numbers and dashes.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await callJson("/api/start/agent", "POST", { slug: s, name: name.trim() || s });
      setAdding(false);
      setSlug("");
      setName("");
      router.push(`/app/start?agent=${encodeURIComponent(s)}`, { scroll: false });
      router.refresh();
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gs-action">
      {agents.length > 0 && (
        <div className="gs-row">
          <label htmlFor="gs-agent" className="k-muted">
            Agent
          </label>
          <select
            id="gs-agent"
            className="k-select"
            value={current || ""}
            onChange={(e) => router.push(`/app/start?agent=${encodeURIComponent(e.target.value)}`, { scroll: false })}
          >
            {agents.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          {!adding && (
            <button type="button" className="k-btn-ghost" onClick={() => setAdding(true)}>
              Register another
            </button>
          )}
        </div>
      )}
      {adding && (
        <form onSubmit={submit} className="gs-row">
          <input
            className="k-input"
            aria-label="Agent id"
            placeholder="support-bot"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
            autoFocus={agents.length === 0}
          />
          <input
            className="k-input"
            aria-label="Display name (optional)"
            placeholder="Support bot (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="k-btn-primary" disabled={busy}>
            {busy ? "Registering…" : "Register agent"}
          </button>
          {agents.length > 0 && (
            <button type="button" className="k-btn-ghost" onClick={() => setAdding(false)}>
              Cancel
            </button>
          )}
        </form>
      )}
      {error && <div className="k-act-error">{error}</div>}
    </div>
  );
}

/** Step 2: create an API key, shown once. */
export function CreateKey({ done }: { done: boolean }) {
  const router = useRouter();
  const { token, setToken } = useContext(KeyContext);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const body = await callJson("/api/tokens", "POST", { name: "get-started" });
      setToken(body.token);
      router.refresh();
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setBusy(false);
    }
  };

  if (token) {
    return (
      <div className="gs-action">
        <div className="gs-secret">
          <code className="mono">{token}</code>
          <button
            type="button"
            className="k-btn-primary"
            onClick={() =>
              navigator.clipboard.writeText(token).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              })
            }
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="k-muted gs-note">Shown once. Store it where your agent reads secrets.</p>
        <CodeSnippet label="Then, in your shell" code={`export AGENTFOX_TOKEN=${token}`} />
      </div>
    );
  }
  return (
    <div className="gs-action">
      <div className="gs-row">
        <button type="button" className={done ? "k-btn" : "k-btn-primary"} onClick={create} disabled={busy}>
          {busy ? "Creating…" : done ? "Create another key" : "Create API key"}
        </button>
        <Link href="/app/start?tab=tokens" className="k-btn-ghost">
          Manage keys
        </Link>
      </div>
      {error && <div className="k-act-error">{error}</div>}
    </div>
  );
}

/** Step 3: pick how the agent is built, copy the snippet, then prove the path works. */
export function IntegrationPicker({
  gateway,
  agent,
  paths,
}: {
  gateway: string;
  agent: string | null;
  /** A subset of the paths, in this order. All of them when absent. */
  paths?: PathKey[];
}) {
  const shown = paths ? PATHS.filter((p) => paths.includes(p.key)) : PATHS;
  const [path, setPath] = useState<PathKey>(shown[0].key);
  const a = agent || "my-agent";
  return (
    <div className="gs-action">
      <div className="chipbar" role="tablist" aria-label="How your agent is built" hidden={shown.length < 2}>
        {shown.map((p) => (
          <button
            key={p.key}
            type="button"
            role="tab"
            aria-selected={path === p.key}
            className={path === p.key ? "chip active" : "chip"}
            onClick={() => setPath(p.key)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <p className="k-muted gs-note">{PATH_NOTE[path]}</p>
      {snippetsFor(path, gateway, a).map((s) => (
        <CodeSnippet key={s.label} label={s.label} code={s.code} />
      ))}
      {SAME_DB.includes(path) && <p className="k-muted gs-note">{SAME_DB_NOTE}</p>}
    </div>
  );
}

type TestResult = {
  ok: boolean;
  status?: number;
  verdict?: string;
  summary?: string;
  trace_id?: string;
  ms?: number;
  detail?: string;
};

export function TestRequest({ agent }: { agent: string | null }) {
  const router = useRouter();
  const { token } = useContext(KeyContext);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  const send = async () => {
    if (!agent) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await fetch("/api/start/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent, token }),
      });
      setResult(await res.json());
      router.refresh();
    } catch (err: any) {
      setResult({ ok: false, detail: String(err?.message || err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gs-action">
      <div className="gs-row">
        <button type="button" className="k-btn" onClick={send} disabled={busy || !agent}>
          {busy ? "Sending…" : "Send a test request"}
        </button>
        <span className="k-muted">
          {agent ? (
            <>
              A message check as <span className="mono">{agent}</span>
              {token ? ", with the new key" : ""}.
            </>
          ) : (
            "Register an agent first."
          )}
        </span>
      </div>
      {result && (
        <div className={`gs-result ${result.ok ? "ok" : "bad"}`} role="status">
          {result.ok ? (
            <>
              <span className={`k-pill k-pill-${result.verdict === "allow" ? "ok" : "warn"}`}>{result.verdict}</span>
              <span>{result.summary || "Decision recorded."}</span>
              <span className="k-muted">{result.ms} ms</span>
              {result.trace_id && (
                <Link href={`/app/traces/${encodeURIComponent(result.trace_id)}`}>Open the trace</Link>
              )}
            </>
          ) : (
            <>
              <span className="k-pill k-pill-bad">{result.status || "error"}</span>
              <span>{result.detail || "The gateway did not answer."}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

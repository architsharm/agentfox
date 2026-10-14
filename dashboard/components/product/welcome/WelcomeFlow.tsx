"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { callJson } from "@/components/kit/Act";
import { CodeSnippet } from "@/components/product/start/CodeSnippet";
import { FirstRequestWatcher } from "@/components/product/start/FirstRequestWatcher";
import { scanRows, upCommand, type Repo } from "@/lib/product/welcome";

/**
 * `agentfox up`, in the browser. The same order: scan, choose, done.
 *
 *   1. Scan one of your repositories (the one updated most recently is preselected).
 *   2. See what it found, from the real scan, and approve all of it in one click.
 *      The proposed policies stay in observe: nothing is blocked yet.
 *   3. Finish on your machine with one command, already answered, and watch the
 *      first live request arrive here.
 *
 * Steps 1 and 2 are a real result on the user's own code in about a minute. Step 3
 * is the part a browser cannot do (install hooks, edit an entry point), so it hands
 * off to `agentfox up` with every answer filled in.
 */

type Phase = "pick" | "scanning" | "scanned" | "accepted";
type Counts = { traces: number; agents: number; decisions: number };

export function WelcomeFlow({
  repos,
  githubLogin,
  gateway,
  siteUrl,
  counts,
}: {
  repos: Repo[];
  githubLogin: string;
  gateway: string;
  siteUrl: string;
  counts: Counts;
}) {
  const [query, setQuery] = useState("");
  const [repo, setRepo] = useState(repos[0]?.full_name || "");
  const [phase, setPhase] = useState<Phase>("pick");
  const [scan, setScan] = useState<any>(null);
  const [accepted, setAccepted] = useState<{ agents: string[]; policies: string[] } | null>(null);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? repos.filter((r) => r.full_name.toLowerCase().includes(q)) : repos;
  }, [repos, query]);

  useEffect(() => {
    if (phase !== "scanning") return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  const runScan = async () => {
    const chosen = repos.find((r) => r.full_name === repo);
    if (!chosen) return;
    setPhase("scanning");
    setElapsed(0);
    setError("");
    try {
      setScan(await callJson("/api/welcome/scan", "POST", { repo_full_name: chosen.full_name, ref: chosen.default_branch }));
      setPhase("scanned");
    } catch (err: any) {
      setError(String(err?.message || err));
      setPhase("pick");
    }
  };

  const accept = async () => {
    setError("");
    try {
      setAccepted(await callJson(`/api/welcome/accept/${encodeURIComponent(scan.scan_run_id)}`, "POST"));
      setPhase("accepted");
    } catch (err: any) {
      setError(String(err?.message || err));
    }
  };

  const summary = scan?.summary || {};
  const proposedAgents: string[] = summary.agents_proposed || [];
  const proposedPolicies: string[] = summary.policies_proposed || [];
  const state = (step: number) => {
    const at = { pick: 1, scanning: 1, scanned: 2, accepted: 3 }[phase];
    return step < at ? "done" : step === at ? "now" : "";
  };

  return (
    <ol className="gs-steps wf-steps">
      <li className={state(1)}>
        <div className="wf-head">
          <span className="gs-marker" aria-hidden>{state(1) === "done" ? "✓" : 1}</span>
          <span className="gs-title">Scan a repository</span>
        </div>
        <div className="gs-body">
          {phase === "pick" || phase === "scanning" ? (
            <>
              <p className="gs-detail">
                Reads the code of a repository you choose from <strong>{githubLogin}</strong>&apos;s GitHub account and
                finds the model calls, tools, MCP servers and skills in it. Nothing is imported, run or changed.
              </p>
              {repos.length > 8 && (
                <input
                  className="k-input wf-filter"
                  type="search"
                  placeholder={`Filter ${repos.length} repositories…`}
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    const first = repos.find((r) => r.full_name.toLowerCase().includes(e.target.value.trim().toLowerCase()));
                    if (first) setRepo(first.full_name);
                  }}
                  disabled={phase === "scanning"}
                />
              )}
              <div className="gs-row">
                <select
                  className="k-input wf-select"
                  aria-label="Repository"
                  value={repo}
                  onChange={(e) => setRepo(e.target.value)}
                  disabled={phase === "scanning"}
                >
                  {shown.map((r) => (
                    <option key={r.full_name} value={r.full_name}>
                      {r.full_name}
                      {r.private ? " (private)" : ""}
                      {r.scanned ? " — scanned before" : ""}
                    </option>
                  ))}
                </select>
                <button type="button" className="k-btn-primary" onClick={runScan} disabled={!repo || phase === "scanning"}>
                  {phase === "scanning" ? `Scanning… ${elapsed}s` : "Scan"}
                </button>
              </div>
              {phase === "scanning" && (
                <p className="gs-note" role="status" aria-live="polite">
                  Downloading and reading <span className="mono">{repo}</span>. Most repositories take under a minute.
                </p>
              )}
            </>
          ) : (
            <p className="gs-detail">
              Scanned <span className="mono">{scan?.summary ? repo : ""}</span>: {summary.files_scanned ?? 0} files.
            </p>
          )}
          {error && phase === "pick" && <div className="k-act-error">{error}</div>}
        </div>
      </li>

      <li className={state(2)}>
        <div className="wf-head">
          <span className="gs-marker" aria-hidden>{state(2) === "done" ? "✓" : 2}</span>
          <span className="gs-title">See what it found, and set it up</span>
        </div>
        {(phase === "scanned" || phase === "accepted") && (
          <div className="gs-body">
            <ScanFindings summary={summary} />
            {phase === "scanned" ? (
              proposedAgents.length || proposedPolicies.length ? (
                <>
                  <p className="gs-detail">
                    Approving registers {plural(proposedAgents.length, "agent")} ({proposedAgents.join(", ") || "none"}) and{" "}
                    {plural(proposedPolicies.length, "policy", "policies")} for the frameworks found. Policies start in observe:
                    they record what they would stop and block nothing until you turn enforcement on.
                  </p>
                  <div className="gs-row">
                    <button type="button" className="k-btn-primary" onClick={accept}>
                      Set this up
                    </button>
                    <Link href="/app/agents?tab=proposed" className="k-btn-ghost">
                      Review one by one instead
                    </Link>
                  </div>
                </>
              ) : (
                <div className="gs-row">
                  <button type="button" className="k-btn-primary" onClick={() => setPhase("accepted")}>
                    Continue
                  </button>
                  <span className="k-muted">Nothing to register from this scan.</span>
                </div>
              )
            ) : (
              accepted && (
                <div className="gs-result" role="status">
                  <span className="k-pill k-pill-ok">set up</span>
                  <span>
                    {plural(accepted.agents.length, "agent")} registered, {plural(accepted.policies.length, "policy", "policies")} live
                    in observe.
                  </span>
                  <Link href="/app/agents">Agents</Link>
                  <Link href="/app/findings">Issues</Link>
                </div>
              )
            )}
            {error && phase === "scanned" && <div className="k-act-error">{error}</div>}
          </div>
        )}
      </li>

      <li className={state(3)}>
        <div className="wf-head">
          <span className="gs-marker" aria-hidden>3</span>
          <span className="gs-title">Govern it live</span>
        </div>
        {phase === "accepted" && (
          <div className="gs-body">
            <ConnectLive gateway={gateway} siteUrl={siteUrl} counts={counts} />
          </div>
        )}
      </li>
    </ol>
  );
}

function ScanFindings({ summary }: { summary: any }) {
  const h = summary?.highlights;
  const rows = scanRows(summary);
  if (summary?.inconclusive) {
    return (
      <div className="gs-result bad" role="status">
        <span className="k-pill k-pill-warn">inconclusive</span>
        <span>No code this scanner reads was found, so this is not a clean result. {summary.next_step || ""}</span>
      </div>
    );
  }
  if (!rows.length) {
    return <p className="gs-detail">No model calls, tools, MCP servers or skills found in this repository.</p>;
  }
  return (
    <div className="wf-findings">
      <dl className="wf-rows">
        {rows.map((r) => (
          <div key={r.label} className={`wf-row wf-${r.tone}`}>
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
      {h?.trifectas?.map((t: any) => (
        <div key={t.file + t.detail} className="gs-result bad">
          <span className="k-pill k-pill-bad">lethal trifecta</span>
          <span>{t.detail}</span>
        </div>
      ))}
      {h?.skill_issues?.map((s: any) => (
        <div key={s.path + s.type} className="gs-result bad">
          <span className="k-pill k-pill-bad">{s.severity}</span>
          <span>
            Skill <strong>{s.skill}</strong>: {String(s.type).replace(/^skill_/, "").replace(/_/g, " ")}{" "}
            <span className="mono k-muted">{s.path}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function ConnectLive({ gateway, siteUrl, counts }: { gateway: string; siteUrl: string; counts: Counts }) {
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const create = async () => {
    setBusy(true);
    setError("");
    try {
      setToken((await callJson("/api/tokens", "POST", { name: "welcome" })).token);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="gs-action">
      <p className="gs-detail">
        In the repository on your machine, one command does the rest: it installs the Claude Code or Codex hooks, adds{" "}
        <code>agentfox.auto()</code> or routes your model calls through this gateway, and declares the tools it found. Every
        question is already answered.
      </p>
      {token ? (
        <>
          <CodeSnippet label="Run in your repository" code={upCommand({ gateway, token, siteUrl })} />
          <p className="k-muted gs-note">The key is shown once and is part of the command. It is saved to .agentfox/agentfox.env (git-ignored).</p>
        </>
      ) : (
        <div className="gs-row">
          <button type="button" className="k-btn-primary" onClick={create} disabled={busy}>
            {busy ? "Creating a key…" : "Get the command"}
          </button>
          <span className="k-muted">Creates an API key for it.</span>
        </div>
      )}
      {error && <div className="k-act-error">{error}</div>}
      <FirstRequestWatcher
        initial={counts}
        waitingHint="Run the command, then use your agent: its first request through this gateway appears here."
      />
      <p className="k-muted gs-note">
        Requests through this gateway show up here. Claude Code and Codex hooks decide on your machine and record there.{" "}
        <Link href="/app">Go to the dashboard</Link> · <Link href="/app/start">Full checklist</Link>
      </p>
    </div>
  );
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

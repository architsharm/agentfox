"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * The project's attack tests, in the map's panel when nothing is selected.
 *
 * The first test runs by itself when `agentfox init` connects the project: the agent
 * as it is, no guardrails. Then one click adds the basic guardrails (what users send,
 * what goes back to them; nothing on tools) and the test runs again, so the two sit
 * side by side. After that the map is where everything else is set up.
 */

type ByType = { type: string; label: string; total: number; done: number; gotThrough: number };
type Run = {
  id: string;
  status: "running" | "done" | "failed";
  phase: "before" | "after";
  total: number;
  gotThrough: number;
  byType: ByType[];
  feed: { id: string; result: "got_through" | "resisted" | "error"; sentence: string }[];
  worst: { headline: string; attack: string; toolCall: string } | null;
  waitingForRunner: boolean;
  errors: number;
  error: string | null;
  finishedAt?: string | null;
};
type Tests = {
  project: string;
  first: Run | null;
  withBasic: Run | null;
  basicOn: boolean;
  connectedProject: string | null;
  runnerConnected: boolean;
};

/** What each kind of attack tries, in a line. */
const KINDS: Record<string, string> = {
  unsafe_tool_use: "Tricks it into running a tool it shouldn't, like a refund on someone else's order",
  prompt_injection: "Instructions hidden in what it reads, like a tool result or a document",
  data_leak: "Gets it to hand over someone else's personal data",
  jailbreak: "Talks it out of its own rules",
};

const POLL_MS = 1500;

async function send(url: string, method = "GET"): Promise<any> {
  const res = await fetch(url, { method, cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || data?.error || `Something went wrong (${res.status}).`);
  return data;
}

function done(r: Run) {
  return r.byType.reduce((n, t) => n + t.done, 0);
}

function Progress({ run }: { run: Run }) {
  const n = done(run);
  return (
    <div className="at-progress">
      <div className="at-progress-head">
        <span>
          {run.waitingForRunner && n === 0
            ? "Waiting for agentfox init on your machine…"
            : `Running ${run.phase === "after" ? "with the basic guardrails" : "on your agent as it is"} · ${n} of ${run.total}`}
        </span>
        {run.gotThrough ? <b className="at-bad">{run.gotThrough} got through</b> : null}
      </div>
      <div className="at-bar" role="progressbar" aria-valuemin={0} aria-valuemax={run.total} aria-valuenow={n}>
        <i style={{ width: `${run.total ? (n / run.total) * 100 : 0}%` }} />
      </div>
      {run.feed.length ? (
        <ul className="at-feed">
          {run.feed.slice(0, 3).map((f) => (
            <li key={f.id} className={`at-${f.result}`}>
              {f.sentence}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** One row per kind of attack: what it tries, and how many got through (before → after). */
function Kinds({ first, after }: { first: Run; after?: Run | null }) {
  const afterOf = (type: string) => after?.byType.find((t) => t.type === type);
  return (
    <ul className="at-kinds">
      {first.byType.map((t) => {
        const a = afterOf(t.type);
        const running = first.status === "running";
        return (
          <li key={t.type}>
            <div className="at-kind-head">
              <strong>{t.label}</strong>
              <span className="at-kind-n">{t.total} attacks</span>
            </div>
            <p>{KINDS[t.type] ?? ""}</p>
            <div className="at-kind-result">
              {running && t.done < t.total ? (
                <span className="gm-sub">
                  {t.done} of {t.total} run{t.gotThrough ? ` · ${t.gotThrough} got through` : ""}
                </span>
              ) : (
                <>
                  <span className={t.gotThrough ? "at-bad" : "at-good"}>{t.gotThrough ? `${t.gotThrough} got through` : "all stopped"}</span>
                  {a && a.done ? (
                    <>
                      <span className="at-arrow" aria-label="then, with basic guardrails">→</span>
                      <span className={a.gotThrough ? "at-bad" : "at-good"}>{a.gotThrough ? `${a.gotThrough} with basic guardrails` : "all stopped with basic guardrails"}</span>
                    </>
                  ) : null}
                </>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Failed({ run, retry, busy }: { run: Run; retry: () => void; busy: boolean }) {
  return (
    <div className="at-failed">
      <strong>The test couldn&apos;t run.</strong>
      <p>{run.error || "Most attacks failed before they reached your agent."}</p>
      <button type="button" className="at-btn at-btn-quiet" onClick={retry} disabled={busy}>
        Try again
      </button>
    </div>
  );
}

export function AttackTests({ project }: { project: string }) {
  const router = useRouter();
  const [tests, setTests] = useState<Tests | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const url = `/api/onboarding/projects/${encodeURIComponent(project)}/tests`;

  const load = useCallback(async () => {
    try {
      setTests(await send(url));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [url]);

  const running = Boolean(tests && [tests.first, tests.withBasic].some((r) => r?.status === "running"));
  useEffect(() => {
    load();
  }, [load]);
  // While a test runs (or the first one is about to start), keep watching.
  useEffect(() => {
    if (!running && tests?.first) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [running, tests?.first, load]);

  const act = async (path: string) => {
    setBusy(true);
    setError(null);
    try {
      await send(path, "POST");
      await load();
      router.refresh(); // the map's rails show the new guardrails
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const runAgain = () => act(url);
  const addBasic = async () => {
    await act(`/api/onboarding/projects/${encodeURIComponent(project)}/basic-guardrails`);
    // Straight into the second run: the difference is the point.
    await act(url);
  };

  if (!tests) {
    return (
      <section className="at">
        <h4>Attack test</h4>
        <p className="gm-sub">{error ?? "Loading…"}</p>
      </section>
    );
  }
  const { first, withBasic, basicOn } = tests;
  const here = tests.connectedProject === project;
  // Whichever test is running shows its progress first; the comparison waits for it.
  const live = first?.status === "running" ? first : withBasic?.status === "running" ? withBasic : null;
  const compared = withBasic?.status === "done" ? withBasic : null;

  return (
    <section className="at" aria-label="Attack test">
      <div className="at-head">
        <h4>Attack test</h4>
        <span className="gm-sub">140 attacks · tools are faked, nothing real happens</span>
      </div>

      {!first ? (
        <div className="at-empty">
          {here ? (
            <p>No tools found to test yet. Once the agent has tools, the test starts by itself.</p>
          ) : (
            <p>
              Tests run on your machine, through <code>agentfox init</code>. Run it in {project}&apos;s repository and leave it
              running: the test starts by itself.
            </p>
          )}
        </div>
      ) : (
        <>
          {live ? <Progress run={live} /> : null}
          {first.status === "failed" ? <Failed run={first} retry={runAgain} busy={busy || !here} /> : null}
          {first.status === "done" ? (
            <p className="at-summary">
              <b className={first.gotThrough ? "at-bad" : "at-good"}>
                {first.gotThrough} of {first.total}
              </b>{" "}
              attacks got through with no guardrails
              {compared ? (
                <>
                  {" · "}
                  <b className={compared.gotThrough ? "at-bad" : "at-good"}>{compared.gotThrough}</b> with the basic ones
                </>
              ) : null}
              .
            </p>
          ) : null}
          {first.status !== "failed" ? <Kinds first={first} after={compared} /> : null}
          {first.status === "done" && first.worst && !withBasic ? (
            <div className="at-worst">
              <span className="gm-sub">Worst one</span>
              <strong>{first.worst.headline}</strong>
              <code>{first.worst.toolCall}</code>
            </div>
          ) : null}
        </>
      )}

      {/* Step 2, once: the basic guardrails. */}
      {first?.status === "done" && !basicOn ? (
        <div className="at-next">
          <strong>Add basic guardrails</strong>
          <ul>
            <li>Block prompt attacks and jailbreaks in what users send</li>
            <li>Hide personal data and secrets in replies</li>
            <li>Nothing on tools yet: you set those up from the map</li>
          </ul>
          <button type="button" className="at-btn" onClick={addBasic} disabled={busy || !here}>
            {busy ? "Adding…" : "Add basic guardrails and test again"}
          </button>
          {!here ? <span className="gm-sub">Run agentfox init in this project&apos;s repository to test again.</span> : null}
        </div>
      ) : null}

      {/* Step 3: the second run, then the map. */}
      {basicOn && withBasic?.status === "failed" ? <Failed run={withBasic} retry={runAgain} busy={busy || !here} /> : null}
      {basicOn && first && !withBasic ? (
        <div className="at-next">
          <strong>Basic guardrails are on</strong>
          <p className="gm-sub">Run the test again to see what they stop.</p>
          <button type="button" className="at-btn" onClick={runAgain} disabled={busy || !here}>
            Run the test again
          </button>
        </div>
      ) : null}
      {withBasic?.status === "done" ? (
        <div className="at-next at-next-quiet">
          <p>
            What still gets through needs guardrails on tools and on what the agent reads. Click a line or a tool on the map to
            set them up.
          </p>
          <button type="button" className="at-btn at-btn-quiet" onClick={runAgain} disabled={busy || !here || running}>
            Run the test again
          </button>
        </div>
      ) : null}
      {error ? <p className="at-error">{error}</p> : null}
    </section>
  );
}

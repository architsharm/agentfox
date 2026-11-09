"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { projectHref, projectInPath } from "@/lib/product/project";
import { Play, Plus, Search, X } from "lucide-react";
import {
  cell,
  controlsLine,
  headline,
  liveRun,
  notRunWhy,
  progressText,
  worseRows,
  plainError,
  pollDelay,
  readyForApp,
  runNote,
  runState,
  shown as shownRuns,
  wouldStopNote,
  type ByType,
  type Run,
  type Tests as BaseTests,
} from "@/lib/product/attackTest";

/**
 * The project's attack test, in the map's panel when nothing is selected: one row per
 * attack set (name and what it tries; the result on the right), a "+" to add sets
 * from the library, and Run.
 *
 * The first test runs by itself when `agentfox init` connects the project, with no
 * guardrails. Then one click adds the basic guardrails and tests again; each row shows
 * before → after. Everything else is set up from the map.
 */

type LibrarySet = { key: string; name: string; description: string; attacks: number };
type Tests = BaseTests & {
  sets: string[];
  library: LibrarySet[];
};

async function send(url: string, method = "GET", body?: unknown): Promise<any> {
  const res = await fetch(url, {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : typeof data?.error === "string" ? data.error : null;
    throw new Error(plainError(detail) || `Something went wrong (${res.status}).`);
  }
  return data;
}

const of = (run: Run | null | undefined, type: string) => run?.byType.find((t) => t.type === type);

/**
 * The right-hand side of a row: how many got through, before → with basic guardrails.
 * "Not run" and "Errored" are neutral, never a green 0; errored and not-run attacks are
 * counted under the number. While a test runs again, the last numbers stay (dimmed)
 * beside its progress.
 */
function Result({
  before,
  after,
  live,
  basicEnforcing,
}: {
  before: { row?: ByType; run: Run | null };
  after: { row?: ByType; run: Run | null };
  live?: ByType;
  basicEnforcing?: boolean;
}) {
  const running = live && live.done < live.total;
  const progress = progressText(live);
  const has = (side: { row?: ByType; run: Run | null }) => Boolean(side.row && side.run);
  if (running && !has(before) && !has(after)) {
    return (
      <span className="at-r">
        <small className="at-progress">{progress}</small>
      </span>
    );
  }
  if (!has(before) && !has(after)) return <span className="at-r at-r-none">—</span>;
  const n = (side: { row?: ByType; run: Run | null }) => {
    const c = cell(side.row, side.run);
    const tone = c.tone === "bad" ? "at-bad" : c.tone === "good" ? "at-good" : "at-neutral";
    return (
      <span className="at-n">
        <b className={tone} title={c.title}>
          {c.text}
        </b>
        {c.note ? <small className="at-sub">{c.note}</small> : null}
      </span>
    );
  };
  const would = wouldStopNote(after.row, basicEnforcing);
  return (
    <span className={running ? "at-r at-stale" : "at-r"} title={running ? `Running again: ${live.done}/${live.total}` : undefined}>
      {has(before) ? n(before) : null}
      {has(before) && has(after) ? <span className="at-arrow">→</span> : null}
      {has(after) ? n(after) : null}
      {would ? <small className="at-sub at-would">{would}</small> : null}
      {running && progress ? <small className="at-progress">{progress}</small> : null}
    </span>
  );
}

function Library({ items, onAdd, onClose }: { items: LibrarySet[]; onAdd: (key: string) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => !box.current?.contains(e.target as globalThis.Node) && onClose();
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [onClose]);
  const shown = items.filter((x) => `${x.name} ${x.description}`.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <div className="at-lib" ref={box} role="dialog" aria-label="Add attack sets">
      <label className="at-lib-search">
        <Search size={13} aria-hidden />
        <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the attack library" />
      </label>
      {shown.length ? (
        <ul>
          {shown.map((x) => (
            <li key={x.key}>
              <button type="button" onClick={() => onAdd(x.key)}>
                <span>
                  <strong>{x.name}</strong>
                  <em>{x.description}</em>
                </span>
                <span className="at-lib-n">{x.attacks}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="gm-sub">{items.length ? "Nothing matches." : "Every set in the library is already added."}</p>
      )}
    </div>
  );
}

/** `paused`: why the test can't run now (an agent in the project is paused or stopped), shown on the Run button. */
export function AttackTests({
  project,
  agent,
  agentName,
  paused,
}: {
  project: string;
  /** The agent whose page this is: the project's test, as this agent saw it. */
  agent?: string;
  agentName?: string;
  paused?: string | null;
}) {
  const router = useRouter();
  // The agent whose page this is: the one the next step's Activity link opens.
  const pageAgent = agent ?? projectInPath(usePathname() || "") ?? undefined;
  const [tests, setTests] = useState<Tests | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const base = `/api/onboarding/projects/${encodeURIComponent(project)}`;

  const load = useCallback(async () => {
    try {
      setTests(await send(`${base}/tests${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [base, agent]);

  const live = liveRun(tests);
  useEffect(() => {
    load();
  }, [load]);
  // Watch while a test runs, and while the first one is still to start; never a
  // project that can't run here, and not for ever (`pollDelay`). Asked again when the
  // window comes back into focus.
  const idle = useRef(0);
  useEffect(() => {
    if (live) idle.current = 0;
    const delay = pollDelay(tests, project, idle.current);
    if (delay === null) return;
    const t = setTimeout(() => {
      if (!live) idle.current += 1;
      load();
    }, delay);
    return () => clearTimeout(t);
  }, [tests, live, project, load]);
  useEffect(() => {
    const again = () => {
      idle.current = 0;
      load();
    };
    window.addEventListener("focus", again);
    return () => window.removeEventListener("focus", again);
  }, [load]);

  const act = async (fn: () => Promise<unknown>, refresh = false) => {
    setBusy(true);
    setError(null);
    idle.current = 0;
    try {
      await fn();
      await load();
      if (refresh) router.refresh(); // the map's rails show the new guardrails
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const run = () => act(() => send(`${base}/tests`, "POST"));
  const addBasic = () =>
    act(async () => {
      await send(`${base}/basic-guardrails`, "POST");
      await send(`${base}/tests`, "POST"); // straight into the second run: the difference is the point
    }, true);
  const setSets = (sets: string[]) => act(() => send(`${base}/tests/sets`, "PUT", { sets }));

  const library = useMemo(() => tests?.library ?? [], [tests?.library]);
  if (!tests) {
    return (
      <section className="at">
        <h4 className="at-title">Attack test</h4>
        <p className="gm-sub">{error ?? "Loading…"}</p>
      </section>
    );
  }
  const { first, basicOn, sets } = tests;
  const here = tests.connectedProject === project;
  // The last finished numbers of each phase (kept while one runs again). A failed or
  // errored "after" run keeps what it got through before it stopped.
  const { before, after } = shownRuns(tests);
  const rows = sets.map((key) => library.find((x) => x.key === key)).filter((x): x is LibrarySet => Boolean(x));
  const rest = library.filter((x) => !sets.includes(x.key));
  const beforeRan = before ? runState(before) !== "not_run" : false;
  const afterRan = after ? runState(after) !== "not_run" : false;
  // What to say about each run that didn't simply finish clean (the latest first).
  const notes = live
    ? []
    : [after && { run: after, label: before ? "With basic guardrails: " : "" }, before && { run: before, label: after ? "No guardrails: " : "" }]
        .filter((x): x is { run: Run; label: string } => Boolean(x))
        .map(({ run: r, label }) => ({ note: runNote(r), label, nothing: runState(r) === "not_run" }))
        .filter((x) => x.note);
  const normal = [
    before && beforeRan ? { line: controlsLine(before), label: after && afterRan ? "no guardrails" : "" } : null,
    after && afterRan ? { line: controlsLine(after), label: before && beforeRan ? "basic guardrails" : "" } : null,
  ].filter((x): x is { line: string; label: string } => Boolean(x?.line));
  const worse = worseRows(before, after);
  const watching = Boolean(after && afterRan && basicOn && tests.basicEnforcing === false && (after.wouldStop ?? 0) > 0);

  return (
    <section className="at" aria-label="Attack test">
      <div className="at-head">
        <h4 className="at-title">Attack test</h4>
        <div className="at-actions">
          <button
            type="button"
            className="at-icon"
            onClick={run}
            disabled={busy || !here || Boolean(live) || Boolean(paused)}
            title={paused ? paused : here ? "Run the test" : "Run agentfox init in this project's repository to test it"}
            aria-label="Run the test"
          >
            <Play size={13} aria-hidden />
          </button>
          <button type="button" className="at-icon" onClick={() => setAdding((v) => !v)} title="Add from the library" aria-label="Add attack sets">
            <Plus size={14} aria-hidden />
          </button>
        </div>
        {adding ? (
          <Library
            items={rest}
            onClose={() => setAdding(false)}
            onAdd={(key) => {
              setAdding(false);
              setSets([...sets, key]);
            }}
          />
        ) : null}
      </div>

      {live ? (
        <div className="at-bar" role="progressbar" aria-valuemin={0} aria-valuemax={live.total} aria-valuenow={live.byType.reduce((n, t) => n + t.done, 0)}>
          <i style={{ width: `${live.total ? (live.byType.reduce((n, t) => n + t.done, 0) / live.total) * 100 : 0}%` }} />
        </div>
      ) : null}
      {live?.waitingForRunner && live.byType.every((t) => t.done === 0) ? (
        <p className="gm-sub">Waiting for agentfox init on your machine…</p>
      ) : live && (before || after) ? (
        <p className="gm-sub">Testing again; the last results stay until the new ones are in.</p>
      ) : null}

      {!live && headline(before, after) ? (
        <p className="at-headline">{headline(before, after)}</p>
      ) : null}

      <ul className="at-rows">
        {rows.map((x) => (
          <li key={x.key}>
            <div className="at-row-text">
              <strong>{x.name}</strong>
              <span>{x.description}</span>
              {notRunWhy(of(after, x.key) || of(before, x.key)) ? (
                <small className="at-why">{notRunWhy(of(after, x.key) || of(before, x.key))}</small>
              ) : null}
            </div>
            <Result
              before={{ row: of(before, x.key), run: before }}
              after={{ row: of(after, x.key), run: after }}
              live={of(live, x.key)}
              basicEnforcing={tests.basicEnforcing}
            />
            {sets.length > 1 ? (
              <button type="button" className="at-remove" onClick={() => setSets(sets.filter((k) => k !== x.key))} aria-label={`Remove ${x.name}`} title="Remove">
                <X size={12} aria-hidden />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {before || after ? (
        <p className="at-legend">
          Attacks that got through, fewer is better{before && after ? ": no guardrails → basic guardrails" : ""}
        </p>
      ) : null}
      {!live && worse.length ? (
        <p className="at-note">
          {worse.map((w) => `${w.label} went from ${w.before} to ${w.after}`).join("; ")}. Results vary between runs of a
          live model: the same attack can fail once and land the next time. Run the test again to see the spread.
        </p>
      ) : null}
      {normal.length ? (
        <p className="at-legend">
          {normal.map((n, i) => (
            <span key={i}>
              {i ? " · " : ""}
              {n.line}
              {n.label ? ` (${n.label})` : ""}
            </span>
          ))}
        </p>
      ) : null}
      {watching ? (
        <p className="at-note">
          The basic guardrails are watching, not blocking yet: they would stop {after?.wouldStop} more once they block. Simulate and
          promote them on the Policies page.
        </p>
      ) : null}

      {!first && !here ? (
        <p className="gm-sub">
          Run <code>agentfox init</code> in this project&apos;s repository; the test starts by itself.
        </p>
      ) : null}
      {notes.map(({ note, label, nothing }, i) => (
        <p key={i} className={note!.tone === "warn" ? "at-note at-warn" : "at-note"}>
          {nothing ? <strong>Not run. </strong> : null}
          {label}
          {note!.text}
        </p>
      ))}

      {first?.status === "done" && beforeRan && !basicOn ? (
        <div className="at-next">
          <div>
            <strong>Turn on basic guardrails</strong>
            <p>
              The run above had nothing blocking: AgentFox was only watching. Basic guardrails block attacks in what users
              send and in what the agent reads, and hide personal data and secrets in replies. Attacks are found by
              pattern rules, plus the prompt-injection classifier where your app has it
              (<code>pip install &apos;agentfox[classifiers]&apos;</code>); patterns alone miss reworded attacks.
            </p>
          </div>
          <button type="button" className="at-btn" onClick={addBasic} disabled={busy || !here || Boolean(paused)} title={paused || undefined}>
            Turn on basic guardrails and test again
          </button>
        </div>
      ) : null}
      {readyForApp({ beforeRan, afterRan, basicOn: Boolean(basicOn), live: Boolean(live) }) ? (
        <div className="at-next">
          <div>
            <strong>Next: run your app</strong>
            <p>
              Run it as you always do, with the <code>agentfox.auto(…)</code> line <code>agentfox init</code> added where your app
              starts (or printed for you to add). Each model and tool call then shows on Activity, with every check it went through.
            </p>
          </div>
          <Link className="at-btn" href={pageAgent ? projectHref(pageAgent, "activity") : "/app/traces"}>
            Open Activity
          </Link>
        </div>
      ) : null}
      {error ? <p className="at-error">{error}</p> : null}
    </section>
  );
}

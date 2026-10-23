"use client";

import { useCallback, useEffect, useState } from "react";
import { Progress } from "@/components/shadcn/progress";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/shadcn/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/shadcn/tabs";
import { simulateRun } from "@/lib/product/onboarding/fixtures";
import type { OnboardingApi } from "@/lib/product/onboarding/api";
import type { AttackResult, TestRun } from "@/lib/product/onboarding/types";
import { useOnboarding } from "./OnboardingFlow";
import { Dot, Panel, Pill, Snippet, StepHero, timeLeft, usePoll } from "./parts";

/** A finished fixture run, for the dev panel's forced "success" state. */
export function finishedFixtureRun(phase: "before" | "after"): TestRun {
  return simulateRun(`run-${phase}-0`, phase, Number.MAX_SAFE_INTEGER);
}

/**
 * The latest run for a phase: resumed if one exists, started if not, and polled
 * until it finishes. Returns the run, an error, and a restart function.
 */
export function useTestRun(api: OnboardingApi, phase: "before" | "after", enabled: boolean, mock: boolean) {
  const [run, setRun] = useState<TestRun | null>(null);
  const [error, setError] = useState("");

  const start = useCallback(async () => {
    setError("");
    setRun(null);
    try {
      setRun(await api.startTest(phase));
    } catch (e: any) {
      setError(e?.message || "Couldn't start the test.");
    }
  }, [api, phase]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api
      .latestTest(phase)
      .then((existing) => {
        if (cancelled) return;
        if (existing) {
          setRun(existing);
          if (existing.status === "failed") setError(existing.error || "The test run stopped before it finished.");
        } else start();
      })
      .catch((e) => !cancelled && setError(e?.message || "Couldn't load the test."));
    return () => {
      cancelled = true;
    };
  }, [api, phase, enabled, start]);

  usePoll(
    async () => {
      if (!run) return;
      try {
        const next = await api.getTest(run.id);
        setRun(next);
        if (next.status === "failed") setError(next.error || "The test run stopped before it finished.");
      } catch (e: any) {
        setError(e?.message || "Lost track of the test run.");
      }
    },
    mock ? 500 : 1000,
    enabled && run?.status === "running",
  );

  return { run, error, restart: start };
}

export function FeedTag({ result }: { result: "got_through" | "resisted" | "error" }) {
  if (result === "got_through")
    return (
      <Pill tone="red" mono>
        GOT THROUGH
      </Pill>
    );
  if (result === "error")
    return (
      <Pill tone="amber" mono>
        ERROR
      </Pill>
    );
  return (
    <Pill tone="green" mono>
      RESISTED
    </Pill>
  );
}

export function RunningView({
  run,
  step,
  title,
  highlight,
  sub,
}: {
  run: TestRun;
  step: string;
  title: string;
  highlight?: string;
  sub: string;
}) {
  const done = run.byType.reduce((n, t) => n + t.done, 0);
  return (
    <section className="flex flex-col gap-5" aria-labelledby="ob-h">
      <StepHero
        eyebrow={step}
        title={title}
        highlight={highlight}
        sub={sub}
        aside={
          <div className="flex flex-wrap gap-2">
            <Pill className="bg-card">{run.total} attacks · 4 types</Pill>
            <Pill className="bg-card">Runs on your machine</Pill>
            <Pill tone="violet" className="bg-card">
              Mapped to OWASP Top 10 for LLMs
            </Pill>
          </div>
        }
      />
      {run.waitingForRunner && <WaitingForRunner />}
      <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
        <Panel
          title="Progress"
          action={
            <span className="font-mono text-xs text-muted-foreground">
              {done} / {run.total}
            </span>
          }
        >
          <div className="flex flex-col gap-5">
            {run.byType.map((t) => (
              <div key={t.type}>
                <div className="mb-2 flex justify-between">
                  <span className="font-medium">{t.label}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {t.done} / {t.total}
                  </span>
                </div>
                <Progress value={(t.done / t.total) * 100} aria-label={t.label} className="h-1.5 bg-muted [&>div]:bg-primary" />
              </div>
            ))}
            <p className="flex items-center gap-2 text-muted-foreground">
              <span className="size-3.5 animate-spin rounded-full border-2 border-border border-t-primary" aria-hidden="true" />
              {run.waitingForRunner
                ? "Waiting for your agent to pick this up"
                : run.remainingMs == null
                  ? "Starting…"
                  : timeLeft(run.remainingMs)}
            </p>
          </div>
        </Panel>
        <Panel
          title="Live results"
          action={
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              <Dot tone="green" pulse /> Live
            </span>
          }
          bodyClassName="p-2"
        >
          <ol className="flex max-h-[360px] min-h-[240px] flex-col gap-2 overflow-hidden" aria-live="polite" aria-label="Live results">
            {run.feed.map((f) => (
              <li key={f.id} className="flex items-center gap-3 rounded-md border bg-card px-3 py-2.5">
                <FeedTag result={f.result} />
                <span className="min-w-0 flex-1 truncate">{f.sentence}</span>
              </li>
            ))}
          </ol>
        </Panel>
      </div>
    </section>
  );
}

/** The run is queued but nothing on the user's machine is connected to run it. */
function WaitingForRunner() {
  const { api } = useOnboarding();
  const [key, setKey] = useState<string | null>(null);
  useEffect(() => {
    api
      .getKey()
      .then((k) => setKey(k.value))
      .catch(() => setKey(null));
  }, [api]);
  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          <Dot tone="amber" pulse /> Waiting for your agent
        </span>
      }
    >
      <div className="grid gap-3">
        <p>
          Tests run on your machine, through <code className="font-mono">agentfox init</code>. Start it again in your
          agent's repo and the run begins by itself.
        </p>
        {key && <Snippet code={`agentfox init --key ${key}`} />}
      </div>
    </Panel>
  );
}

/** "See all N with full traces": every attack in the run, what it sent and what the agent did. */
export function AllResults({ runId, open, onClose }: { runId: string; open: boolean; onClose: () => void }) {
  const { api } = useOnboarding();
  const [rows, setRows] = useState<AttackResult[] | null>(null);
  const [filter, setFilter] = useState<"through" | "all">("through");
  useEffect(() => {
    if (!open) return;
    api
      .getResults(runId)
      .then(setRows)
      .catch(() => setRows([]));
  }, [api, runId, open]);
  const shown = (rows ?? []).filter((r) => filter === "all" || r.gotThrough);
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="tw gap-0 sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle className="text-base">Every attack</SheetTitle>
          <SheetDescription>What each attack sent, and what your agent did with it.</SheetDescription>
          <Tabs value={filter} onValueChange={(v) => setFilter(v as "through" | "all")} className="mt-2">
            <TabsList className="rounded-md">
              <TabsTrigger value="through" className="rounded-[4px]">
                Got through ({(rows ?? []).filter((r) => r.gotThrough).length})
              </TabsTrigger>
              <TabsTrigger value="all" className="rounded-[4px]">
                All ({rows?.length ?? 0})
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto">
          {rows === null ? (
            <p className="p-5 text-muted-foreground">Loading…</p>
          ) : shown.length === 0 ? (
            <p className="p-5 text-muted-foreground">
              Nothing here. In the sample walkthrough, the full trace list appears once a real agent is tested.
            </p>
          ) : (
            shown.map((r) => (
              <div key={r.id} className="grid gap-3 border-b px-5 py-4 last:border-0">
                <div className="flex items-center gap-3">
                  <FeedTag result={r.gotThrough ? "got_through" : r.error ? "error" : "resisted"} />
                  <span className="font-medium">{r.sentence}</span>
                </div>
                <Trace
                  rows={
                    [
                      ["The attack", r.attack],
                      ...(r.error ? [["Error", r.error]] : r.toolCall ? [["What it did", r.toolCall]] : []),
                    ] as [string, string][]
                  }
                />
              </div>
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function Trace({ rows }: { rows: [string, string][] }) {
  return (
    <div className="overflow-hidden rounded-md border font-mono text-[13px]">
      {rows.map(([k, v], i) => (
        <div key={k} className={`grid grid-cols-[96px_minmax(0,1fr)] gap-3 px-4 py-3 ${i === 0 ? "bg-muted/50" : "border-t"}`}>
          <span className="font-sans text-xs text-muted-foreground">{k}</span>
          <span className="break-words whitespace-pre-wrap">{v}</span>
        </div>
      ))}
    </div>
  );
}

export function downloadReport(run: TestRun, filename: string) {
  const blob = new Blob([JSON.stringify({ generatedAt: new Date().toISOString(), run }, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Eye } from "lucide-react";
import { Button } from "@/components/shadcn/button";
import { STRUCTURE, TOTAL_ATTACKS } from "@/lib/product/onboarding/fixtures";
import { suggestGuardrails } from "@/lib/product/onboarding/steps";
import type { SuggestedGuardrail, TestRun } from "@/lib/product/onboarding/types";
import { StepFooter, useOnboarding } from "./OnboardingFlow";
import { EmptyState, ErrorState, Loading, Panel, Pill, StepHero } from "./parts";
import { RunningView, finishedFixtureRun, useTestRun } from "./TestRunParts";

export function RetestStep() {
  const { api, mock, forced, state, finish, href } = useOnboarding();
  const { run, error, restart } = useTestRun(api, "after", !forced, mock);
  const [before, setBefore] = useState<TestRun | null | undefined>(undefined);
  const [guards, setGuards] = useState<SuggestedGuardrail[]>([]);
  const marked = useRef(false);

  useEffect(() => {
    if (forced) return;
    api
      .latestTest("before")
      // Mock mode can open Retest directly, with no first run: compare against the fixture.
      .then((b) => setBefore(b ?? (mock ? finishedFixtureRun("before") : null)))
      .catch(() => setBefore(null));
    api
      .getGuardrails()
      .then(setGuards)
      .catch(() => setGuards([]));
  }, [api, forced, mock]);

  const after = forced === "success" ? finishedFixtureRun("after") : run;
  const base = forced === "success" ? finishedFixtureRun("before") : before;

  // The retest finishing is what completes onboarding.
  useEffect(() => {
    if (forced || marked.current || after?.status !== "done" || state.completedAt) return;
    marked.current = true;
    finish("retest");
  }, [after?.status, forced, state.completedAt, finish]);

  if (forced === "loading") return <Loading label="Getting the retest ready…" />;
  if (forced === "empty" || (!forced && before === null))
    return (
      <EmptyState
        title="Nothing to compare yet"
        detail="Run the first test, turn on guardrails, then retest to see the difference."
        action={{ label: "Go to Test", href: href("test") }}
      />
    );
  if (forced === "error" || error)
    return (
      <ErrorState
        title="The retest didn't finish"
        detail={forced ? "Something went wrong partway through. Your guardrails are still on." : error}
        onRetry={forced ? undefined : restart}
      />
    );
  if (!after || base === undefined || !base) return <Loading label="Getting the retest ready…" />;
  if (after.status === "running")
    return (
      <>
        <RunningView
          run={after}
          step="Step 5 of 5"
          title="Running the same attacks again"
          highlight="again"
          sub={`The same ${after.total || TOTAL_ATTACKS} attacks, now with your guardrails on. Tools are still faked.`}
        />
        <StepFooter
          hint={
            <>
              <span className="size-3.5 animate-spin rounded-full border-2 border-border border-t-primary" aria-hidden="true" />
              Comparing before and after
            </>
          }
        >
          <Button size="lg" disabled>
            Configure more
          </Button>
        </StepFooter>
      </>
    );

  const shownGuards = (forced === "success" ? suggestGuardrails(STRUCTURE) : guards).filter((g) => g.enabled);
  const typeBefore = (type: string) => base.byType.find((t) => t.type === type);
  const drop = base.gotThrough ? Math.round(((base.gotThrough - after.gotThrough) / base.gotThrough) * 100) : 0;

  return (
    <section className="flex flex-col gap-5" aria-labelledby="ob-h">
      <StepHero
        eyebrow="Step 5 of 5"
        title={
          after.gotThrough < base.gotThrough
            ? `Same ${after.total} attacks. Now only ${after.gotThrough} get through.`
            : `Same ${after.total} attacks. ${after.gotThrough} still get through.`
        }
        highlight={after.gotThrough < base.gotThrough ? `only ${after.gotThrough}` : `${after.gotThrough} still`}
        sub="Here's what basic guardrails changed."
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-5">
          <div
            className="grid grid-cols-[1fr_auto_1fr] overflow-hidden rounded-lg border bg-card shadow-xs"
            aria-label={`${base.gotThrough} attacks got through before, ${after.gotThrough} after`}
          >
            <div className="p-5">
              <span className="text-muted-foreground">Before</span>
              <div className="mt-2 text-4xl font-semibold tracking-tight text-danger-ink tabular-nums">
                {base.gotThrough}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">got through</p>
            </div>
            <div className="grid place-items-center border-x bg-muted/40 px-4 text-muted-foreground" aria-hidden="true">
              <ArrowRight className="size-5" />
            </div>
            <div className="p-5">
              <span className="flex items-center justify-between text-muted-foreground">
                After <Pill tone="green">−{drop}%</Pill>
              </span>
              <div className="mt-2 text-4xl font-semibold tracking-tight text-success-ink tabular-nums">
                {after.gotThrough}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">got through</p>
            </div>
          </div>

          <Panel
            title="By attack type"
            action={
              <span className="flex items-center gap-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-sm bg-chart-pink" /> Before
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-sm bg-success" /> After
                </span>
              </span>
            }
          >
            <ul className="flex flex-col gap-4">
              {after.byType.map((t) => {
                const b = typeBefore(t.type);
                return (
                  <li key={t.type} className="grid grid-cols-[132px_minmax(0,1fr)_64px] items-center gap-4">
                    <span>{t.label}</span>
                    <span className="flex flex-col gap-1" aria-hidden="true">
                      <span className="h-2 overflow-hidden rounded-[2px] bg-muted">
                        <span
                          className="block h-full rounded-[2px] bg-chart-pink"
                          style={{ width: `${((b?.gotThrough ?? 0) / t.total) * 100}%` }}
                        />
                      </span>
                      <span className="h-2 overflow-hidden rounded-[2px] bg-muted">
                        <span className="block h-full rounded-[2px] bg-success" style={{ width: `${(t.gotThrough / t.total) * 100}%` }} />
                      </span>
                    </span>
                    <span className="text-right font-mono text-xs text-muted-foreground">
                      {b?.gotThrough ?? 0} → {t.gotThrough}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Panel>
        </div>

        <Panel title="Basic guardrails we added" bodyClassName="p-0">
          <ul>
            {shownGuards.map((g) => (
              <li key={g.id} className="flex gap-3 border-b px-5 py-3.5 last:border-0">
                <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-success-soft text-success-ink">
                  <Check className="size-3" strokeWidth={3} />
                </span>
                <span>
                  {g.sentence}
                  <small className="mt-0.5 block font-mono text-xs text-muted-foreground">{g.appliesTo}</small>
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="flex items-center gap-3 rounded-lg border border-warning/30 bg-warning-soft px-5 py-4 text-warning-ink" role="note">
        <Eye className="size-4 shrink-0" />
        <span>
          New guardrails start by watching: they record what they would stop, and stop nothing, so these numbers count
          only what blocks today.{" "}
          {after.wouldStop
            ? `${after.wouldStop} more ${after.wouldStop === 1 ? "attack" : "attacks"} would be stopped once the watching rules block.`
            : `${after.gotThrough} ${after.gotThrough === 1 ? "attack still gets" : "attacks still get"} through: tune them next.`}
        </span>
      </div>

      <StepFooter
        secondary={
          <Button asChild variant="outline">
            <Link href="/app">Go to home</Link>
          </Button>
        }
      >
        <Button asChild size="lg">
          <Link href="/app/policies">
            Configure more <ArrowRight />
          </Link>
        </Button>
      </StepFooter>
    </section>
  );
}

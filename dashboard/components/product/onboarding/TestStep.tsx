"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/shadcn/button";
import { TOTAL_ATTACKS } from "@/lib/product/onboarding/fixtures";
import type { TestRun } from "@/lib/product/onboarding/types";
import { ContinueLabel, StepFooter, useOnboarding } from "./OnboardingFlow";
import { EmptyState, ErrorState, Icon, Loading, Panel, Pill, StepHero } from "./parts";
import { AllResults, RunningView, Trace, downloadReport, finishedFixtureRun, useTestRun } from "./TestRunParts";

export function TestStep() {
  const { api, mock, forced, finish, href } = useOnboarding();
  const { run, error, restart } = useTestRun(api, "before", !forced, mock);

  if (forced === "loading") return <Loading label="Getting the test ready…" />;
  if (forced === "empty")
    return (
      <EmptyState
        title="Nothing to test yet"
        detail="Connect an agent with at least one tool, and we'll attack it safely."
        action={{ label: "Back to Connect", href: href("connect") }}
      />
    );
  if (forced === "error" || error)
    return (
      <ErrorState
        title="The test didn't finish"
        detail={forced ? "Something went wrong partway through. Nothing real was touched." : error}
        onRetry={forced ? undefined : restart}
      />
    );

  const shown = forced === "success" ? finishedFixtureRun("before") : run;
  if (!shown) return <Loading label="Getting the test ready…" />;
  if (shown.status === "running")
    return (
      <>
        <RunningView
          run={shown}
          step="Step 3 of 5"
          title="Attacking your agents (safely)"
          highlight="(safely)"
          sub={`${shown.total || TOTAL_ATTACKS} known attacks, built for your agent's tools. It talks to its real model; its tools are faked, so nothing real happens.`}
        />
        <StepFooter
          hint={
            <>
              <span className="size-3.5 animate-spin rounded-full border-2 border-border border-t-primary" aria-hidden="true" />
              Results appear when the run finishes
            </>
          }
        >
          <Button size="lg" disabled>
            <ContinueLabel>Fix with basic guardrails</ContinueLabel>
          </Button>
        </StepFooter>
      </>
    );

  return <Results run={shown} onNext={() => finish("test")} />;
}

function Results({ run, onNext }: { run: TestRun; onNext: () => void }) {
  const { api, mock } = useOnboarding();
  const [showAll, setShowAll] = useState(false);
  const download = async () => {
    const results = mock ? [] : await api.getResults(run.id).catch(() => []);
    downloadReport({ ...run, results } as TestRun, "agentfox-attack-report.json");
  };
  const pct = run.total ? Math.round((run.gotThrough / run.total) * 100) : 0;
  return (
    <section className="flex flex-col gap-5" aria-labelledby="ob-h">
      <StepHero
        eyebrow="Step 3 of 5"
        title="How exposed you are today"
        highlight="exposed"
        sub="The same attacks real people use. Here's what got past your agents."
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Today, without AgentFox" action={<Pill tone="red">Exposed</Pill>}>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-semibold tracking-tight text-danger-ink tabular-nums">{run.gotThrough}</span>
            <span className="text-muted-foreground">of {run.total} attacks got through</span>
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            That's {pct}% of known attacks. The worst one is below.
          </p>
        </Panel>

        <Panel title="By attack type" action={<span className="text-xs text-muted-foreground">got through</span>}>
          <ul className="flex flex-col gap-4">
            {run.byType.map((t) => (
              <li key={t.type} className="grid grid-cols-[132px_minmax(0,1fr)_56px] items-center gap-4">
                <span>{t.label}</span>
                <span className="h-2 overflow-hidden rounded-[2px] bg-muted" aria-hidden="true">
                  <span className="block h-full rounded-[2px] bg-danger/80" style={{ width: `${(t.gotThrough / t.total) * 100}%` }} />
                </span>
                <span className="text-right font-mono text-xs text-muted-foreground">
                  {t.gotThrough} / {t.total}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      {run.worst && (
        <Panel
          title={
            <span className="flex flex-wrap items-center gap-2">
              <Pill tone="red">Worst one</Pill>
              {run.worst.owasp.map((o) => (
                <Pill key={o}>{o}</Pill>
              ))}
            </span>
          }
          action={
            <Button variant="link" className="h-auto p-0" onClick={() => setShowAll(true)}>
              See all {run.gotThrough} with full traces
            </Button>
          }
        >
          <h2 className="mb-3 text-base font-semibold">{run.worst.headline}</h2>
          <Trace
            rows={[
              ["The attack", run.worst.attack],
              ["What it did", run.worst.toolCall],
            ]}
          />
        </Panel>
      )}
      {run.gotThrough === 0 && (
        <div className="flex items-center gap-3 rounded-lg border bg-success-soft px-5 py-4 text-success-ink">
          <Icon name="check" />
          <span>Nothing got through. Guardrails still help: they hold up when the model has a bad day.</span>
        </div>
      )}
      <AllResults runId={run.id} open={showAll} onClose={() => setShowAll(false)} />

      <StepFooter
        secondary={
          <Button variant="outline" onClick={download}>
            <Download /> Download report for security team
          </Button>
        }
      >
        <Button size="lg" onClick={onNext}>
          <ContinueLabel>Fix with basic guardrails</ContinueLabel>
        </Button>
      </StepFooter>
    </section>
  );
}

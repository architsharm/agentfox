"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Wordmark } from "@/components/product/Logo";
import { Button } from "@/components/shadcn/button";
import { onboardingApi, type OnboardingApi } from "@/lib/product/onboarding/api";
import {
  INITIAL_STATE,
  STEPS,
  completeStep,
  nextStep,
  prevStep,
  stepHref,
  stepIndex,
} from "@/lib/product/onboarding/steps";
import type { ForcedState, OnboardingState, OnboardingStep } from "@/lib/product/onboarding/types";
import { cn } from "@/lib/utils";
import { DevPanel } from "./DevPanel";
import { ConnectStep } from "./ConnectStep";
import { InstallStep } from "./InstallStep";
import { StructureStep } from "./StructureStep";
import { TestStep } from "./TestStep";
import { ProtectStep } from "./ProtectStep";
import { RetestStep } from "./RetestStep";
import { ErrorState, Loading } from "./parts";

type Ctx = {
  api: OnboardingApi;
  mock: boolean;
  step: OnboardingStep;
  state: OnboardingState;
  /** Set from the dev panel (`?state=`): render this state instead of the real one. */
  forced: ForcedState | null;
  /** Mark `step` done and go to the next one (or stay, on the last). */
  finish(step: OnboardingStep): Promise<void>;
  href(step: OnboardingStep): string;
};

const OnboardingContext = createContext<Ctx | null>(null);

export function useOnboarding(): Ctx {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboarding outside OnboardingFlow");
  return ctx;
}

const FORCED: ForcedState[] = ["loading", "empty", "error", "success"];

/**
 * The full-screen onboarding: header, the five steps across the top, the step
 * itself on a dotted ground, and a sticky action bar. Owns progress (load, save,
 * reset) so the steps only render.
 */
export function OnboardingFlow({ step, devTools }: { step: OnboardingStep; devTools: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const mock = params.get("mock") === "1";
  const forcedParam = params.get("state");
  const forced = FORCED.includes(forcedParam as ForcedState) ? (forcedParam as ForcedState) : null;
  const api = useMemo(() => onboardingApi(mock), [mock]);

  const [state, setState] = useState<OnboardingState | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // `?reset=1` always starts over at step 1, then drops itself from the URL.
        if (params.get("reset") === "1") {
          const fresh = await api.reset();
          if (cancelled) return;
          setState(fresh);
          router.replace(stepHref("connect", mock));
          return;
        }
        let current = await api.getState();
        // Viewing a step makes it the one to resume at; finished steps stay finished.
        if (current.currentStep !== step && !current.completedAt) {
          current = await api.saveState({ ...current, currentStep: step, skipped: false });
        }
        if (!cancelled) setState(current);
      } catch (e: any) {
        if (!cancelled) setLoadError(e?.message || "Couldn't load your setup progress.");
      }
    })();
    return () => {
      cancelled = true;
    };
    // Re-run when the step or mode changes, not on every query-string tweak.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, step, params.get("reset")]);

  const finish = useCallback(
    async (done: OnboardingStep) => {
      const saved = await api.saveState(completeStep(state ?? INITIAL_STATE, done));
      setState(saved);
      const next = nextStep(done);
      if (next) router.push(stepHref(next, mock));
    },
    [api, state, router, mock],
  );

  const skip = async () => {
    try {
      await api.saveState({ ...(state ?? INITIAL_STATE), currentStep: step, skipped: true });
    } finally {
      router.push("/app");
    }
  };

  const ctx: Ctx | null = state
    ? { api, mock, step, state, forced, finish, href: (s) => stepHref(s, mock) }
    : null;

  return (
    <div className="tw ob min-h-screen bg-background text-sm">
      <header className="sticky top-0 z-30 border-b bg-card">
        <div className="mx-auto grid h-14 max-w-[1180px] grid-cols-[1fr_auto_1fr] items-center gap-4 px-6">
          <Link href="/app" aria-label="AgentFox home" className="justify-self-start">
            <Wordmark />
          </Link>
          <Progress step={step} state={state} mock={mock} />
          <Button variant="ghost" size="sm" className="justify-self-end text-muted-foreground" onClick={skip}>
            Skip setup
          </Button>
        </div>
      </header>

      <div className="bg-dots min-h-[calc(100vh-56px)]">
        <main className={cn("mx-auto px-6 pt-16 pb-24", WIDE.has(step) ? "max-w-4xl" : "max-w-xl")}>
          {loadError ? (
            <ErrorState title="Couldn't load your setup" detail={loadError} onRetry={() => location.reload()} />
          ) : !ctx ? (
            <Loading label="Loading your setup…" />
          ) : (
            <OnboardingContext.Provider value={ctx}>
              {step === "connect" && <ConnectStep />}
              {step === "install" && <InstallStep />}
              {step === "structure" && <StructureStep />}
              {step === "test" && <TestStep />}
              {step === "protect" && <ProtectStep />}
              {step === "retest" && <RetestStep />}
            </OnboardingContext.Provider>
          )}
        </main>
      </div>

      {devTools && (
        <DevPanel
          step={step}
          mock={mock}
          forced={forced}
          onReset={async () => {
            await api.reset();
            setState(INITIAL_STATE);
            router.push(stepHref("connect", mock));
          }}
          pathname={pathname}
        />
      )}
    </div>
  );
}

/** Screens that show results need room; the rest are one narrow centred column. */
const WIDE = new Set<OnboardingStep>(["test", "retest"]);

/**
 * Progress as a thin segmented bar: done and current segments fill violet, the
 * rest stay grey. Done segments link back. No numbers, no labels on screen; the
 * label is there for screen readers and as a tooltip.
 */
function Progress({ step, state, mock }: { step: OnboardingStep; state: OnboardingState | null; mock: boolean }) {
  const here = stepIndex(step);
  return (
    <nav aria-label={`Setup progress: ${STEPS[here].label}, step ${here + 1} of ${STEPS.length}`}>
      <ol className="flex items-center gap-1.5">
        {STEPS.map(({ step: s, label }, i) => {
          const done = s !== step && Boolean(state?.completedSteps.includes(s));
          const bar = cn("block h-1 w-10 rounded-[1px] transition-colors", i <= here || done ? "bg-primary" : "bg-border");
          return (
            <li key={s} title={label}>
              {done ? (
                <Link href={stepHref(s, mock)} aria-label={`${label}, done. Go back`} className="block py-2">
                  <span className={bar} />
                </Link>
              ) : (
                <span className="block py-2" aria-current={s === step ? "step" : undefined} aria-label={label}>
                  <span className={bar} />
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * The step's actions, under its content: Back on the left, the one main action on
 * the right, and — when that action is waiting on something — a line saying what.
 */
export function StepFooter({
  children,
  secondary,
  hint,
}: {
  children: React.ReactNode;
  secondary?: React.ReactNode;
  hint?: React.ReactNode;
}) {
  const { step, href } = useOnboarding();
  const prev = prevStep(step);
  return (
    <div className="mt-2 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          {prev && (
            <Button asChild variant="ghost" className="text-muted-foreground">
              <Link href={href(prev)}>
                <ArrowLeft /> Back
              </Link>
            </Button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {secondary}
          {children}
        </div>
      </div>
      {hint && <p className="flex items-center justify-end gap-2 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

/** The main button's label: always says where it goes. */
export function ContinueLabel({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <ArrowRight />
    </>
  );
}

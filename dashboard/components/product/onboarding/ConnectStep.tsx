"use client";

import { useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { Button } from "@/components/shadcn/button";
import { ContinueLabel, StepFooter, useOnboarding } from "./OnboardingFlow";
import { ErrorState, Loading, Panel, Snippet, StepHero } from "./parts";

/** Step 1: create the key the project connects with. */
export function ConnectStep() {
  const { api, forced, state, finish } = useOnboarding();
  // Coming back to this step: the key already exists, so show it.
  const [key, setKey] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const returning = state.completedSteps.includes("connect");

  const create = async () => {
    setCreating(true);
    setError("");
    try {
      setKey((await api.getKey()).value);
    } catch (e: any) {
      setError(e?.message || "Couldn't create your key.");
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => {
    if (returning && !forced) void create();
    // Only on arrival: a returning user already has a key, so show it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (forced === "loading") return <Loading label="Creating your key…" />;
  if (forced === "error" || error)
    return <ErrorState title="Couldn't create your key" detail={forced ? "Try again in a moment." : error} onRetry={create} />;

  const shown = forced === "success" ? "afi_9f3c2b7d41e84a06b5d2" : forced === "empty" ? null : key;

  return (
    <section className="flex flex-col gap-6" aria-labelledby="ob-h">
      <StepHero title="Connect your project" highlight="project" sub="Create a key that links your project to AgentFox." />

      <Panel>
        {shown ? (
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-foreground">Your project key</span>
            <Snippet code={shown} />
          </div>
        ) : (
          <Button size="lg" className="w-full" onClick={create} disabled={creating}>
            <KeyRound /> {creating ? "Creating…" : "Create project key"}
          </Button>
        )}
      </Panel>

      {shown && (
        <StepFooter>
          <Button size="lg" onClick={() => finish("connect")}>
            <ContinueLabel>Continue</ContinueLabel>
          </Button>
        </StepFooter>
      )}
    </section>
  );
}

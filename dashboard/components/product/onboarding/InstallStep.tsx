"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/shadcn/button";
import { STRUCTURE, structureCounts } from "@/lib/product/onboarding/fixtures";
import type { Structure } from "@/lib/product/onboarding/types";
import { ContinueLabel, StepFooter, useOnboarding } from "./OnboardingFlow";
import { Dot, ErrorState, Loading, Panel, Snippet, StepHero, usePoll } from "./parts";

type Live = { connected: boolean; structure: Structure };
const EMPTY: Structure = { sources: [], agents: [], tools: [], systems: [] };

/** Step 2: one command in the project; this screen notices when it has run. */
export function InstallStep() {
  const { api, mock, forced, finish } = useOnboarding();
  const [key, setKey] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getKey()
      .then((k) => setKey(k.value))
      .catch((e) => setError(e?.message || "Couldn't load your key."));
  }, [api]);

  usePoll(
    async () => {
      try {
        setLive(await api.getStructure({ live: true }));
      } catch {
        // A missed poll is retried in two seconds; the waiting line covers it.
      }
    },
    mock ? 500 : 2000,
    !forced,
  );

  if (forced === "loading") return <Loading label="Loading…" />;
  if (forced === "error" || error)
    return <ErrorState title="Couldn't load your key" detail={forced ? "Try again in a moment." : error} onRetry={() => location.reload()} />;

  const view = forced === "success" ? { connected: true, structure: STRUCTURE } : forced === "empty" ? { connected: false, structure: EMPTY } : live;
  const found = Boolean(view?.connected && view.structure.agents.length > 0);
  const counts = structureCounts(view?.structure ?? EMPTY);
  const command = `pip install agentfox && agentfox init --key ${key ?? "afi_…"}`;

  return (
    <section className="flex flex-col gap-6" aria-labelledby="ob-h">
      <StepHero
        title="Install AgentFox"
        highlight="AgentFox"
        sub="Run the command below in your project to auto-detect its agents and tools."
      />

      <Panel bodyClassName="p-0">
        <div className="p-4">{key ? <Snippet code={command} /> : <div className="h-11 animate-pulse rounded-md bg-muted" />}</div>
        <div className="flex items-center gap-2 border-t px-4 py-3 text-sm" aria-live="polite">
          {found ? (
            <>
              <span className="grid size-4 place-items-center rounded-[3px] bg-success text-white">
                <Check className="size-3" strokeWidth={3} />
              </span>
              <span>
                Project found · {counts.agents} {counts.agents === 1 ? "agent" : "agents"}, {counts.tools}{" "}
                {counts.tools === 1 ? "tool" : "tools"}
              </span>
            </>
          ) : (
            <>
              <Dot tone="amber" pulse />
              <span className="text-muted-foreground">Waiting for your project…</span>
            </>
          )}
        </div>
      </Panel>

      <StepFooter
        secondary={
          !found && (
            <Button asChild variant="link" className="text-muted-foreground">
              <Link href="/app/welcome">Scan a repository instead</Link>
            </Button>
          )
        }
      >
        <Button size="lg" disabled={!found} onClick={() => finish("install")}>
          <ContinueLabel>Continue</ContinueLabel>
        </Button>
      </StepFooter>
    </section>
  );
}

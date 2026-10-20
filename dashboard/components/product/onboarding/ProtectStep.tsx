"use client";

import { useCallback, useEffect, useState } from "react";
import { Eye, ShieldCheck } from "lucide-react";
import { Button } from "@/components/shadcn/button";
import { Switch } from "@/components/shadcn/switch";
import { STRUCTURE } from "@/lib/product/onboarding/fixtures";
import { suggestGuardrails } from "@/lib/product/onboarding/steps";
import type { SuggestedGuardrail } from "@/lib/product/onboarding/types";
import { ContinueLabel, StepFooter, useOnboarding } from "./OnboardingFlow";
import { EmptyState, ErrorState, Loading, Panel, StepHero } from "./parts";

export function ProtectStep() {
  const { api, forced, finish, href } = useOnboarding();
  const [items, setItems] = useState<SuggestedGuardrail[] | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const load = useCallback(() => {
    setError("");
    setItems(null);
    api
      .getGuardrails()
      .then(setItems)
      .catch((e) => setError(e?.message || "Couldn't load suggestions."));
  }, [api]);
  useEffect(load, [load]);

  if (forced === "loading") return <Loading label="Picking guardrails from your results…" />;
  if (forced === "error" || (!forced && error))
    return (
      <ErrorState
        title="Couldn't load your guardrails"
        detail={forced ? "We couldn't reach AgentFox. Your test results are safe." : error}
        onRetry={forced ? undefined : load}
      />
    );
  const shown = forced === "empty" ? [] : forced === "success" ? suggestGuardrails(STRUCTURE) : items;
  if (!shown) return <Loading label="Picking guardrails from your results…" />;
  if (shown.length === 0)
    return (
      <EmptyState
        title="No guardrails to suggest"
        detail="Run the test first, and we'll pick guardrails that fit what got through."
        action={{ label: "Back to Test", href: href("test") }}
      />
    );

  const toggle = (id: string) =>
    setItems((prev) => (prev ?? shown).map((g) => (g.id === id ? { ...g, enabled: !g.enabled } : g)));
  const on = shown.filter((g) => g.enabled).length;

  const save = async () => {
    setSaving(true);
    setSaveError("");
    try {
      await api.saveGuardrails(shown);
      await finish("protect");
    } catch (e: any) {
      setSaveError(e?.message || "Couldn't save. Try again.");
      setSaving(false);
    }
  };

  return (
    <section className="flex flex-col gap-5" aria-labelledby="ob-h">
      <StepHero
        eyebrow="Step 4 of 5"
        title="Basic guardrails for your agents"
        highlight="guardrails"
        sub="We picked these from your test results. Change anything later."
      />

      <div className="max-w-3xl">
        <Panel
          title="Suggested for you"
          action={
            <span className="text-muted-foreground">
              {on} of {shown.length} on
            </span>
          }
          bodyClassName="p-0"
        >
          <ul>
            {shown.map((g) => (
              <li key={g.id} className="border-b last:border-0">
                <label className="flex cursor-pointer items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-muted/40">
                  <span className="flex items-start gap-3">
                    <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-violet-soft text-primary" aria-hidden="true">
                      <ShieldCheck className="size-4" />
                    </span>
                    <span className="flex flex-col gap-1">
                      <span className="font-medium">{g.sentence}</span>
                      <span className="font-mono text-xs text-muted-foreground">{g.appliesTo}</span>
                    </span>
                  </span>
                  <Switch checked={g.enabled} onCheckedChange={() => toggle(g.id)} aria-label={g.sentence} />
                </label>
              </li>
            ))}
          </ul>
        </Panel>

      </div>
      <p className="flex items-center gap-2 text-sm text-warning-ink" role="note">
        <Eye className="size-4 shrink-0" />
        Starts in watch mode: we log what we'd stop on live traffic, without stopping it.
      </p>
      {saveError && (
        <p className="text-danger-ink" role="alert">
          {saveError}
        </p>
      )}

      <StepFooter hint={on === 0 ? "Turn on at least one guardrail" : undefined}>
        <Button size="lg" onClick={save} disabled={saving || on === 0}>
          {saving ? "Turning on…" : <ContinueLabel>Turn on and retest</ContinueLabel>}
        </Button>
      </StepFooter>
    </section>
  );
}

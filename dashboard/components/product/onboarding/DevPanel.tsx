"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Wrench } from "lucide-react";
import { STEPS } from "@/lib/product/onboarding/steps";
import type { ForcedState, OnboardingStep } from "@/lib/product/onboarding/types";
import { cn } from "@/lib/utils";

const STATES: ForcedState[] = ["loading", "empty", "error", "success"];

function url(step: OnboardingStep, mock: boolean, state: ForcedState | null) {
  const q = new URLSearchParams();
  if (mock) q.set("mock", "1");
  if (state) q.set("state", state);
  const s = q.toString();
  return `/app/onboarding/${step}${s ? `?${s}` : ""}`;
}

const chip = "inline-flex h-6 items-center rounded-md border bg-card px-2 text-xs font-medium hover:bg-muted";
const on = "border-primary bg-primary text-primary-foreground hover:bg-primary-hover";

/**
 * "Onboarding dev": jump to any step, toggle mock, reset, force a state. Shown in
 * development and to internal users only. Everything it does is a URL, so any
 * state it reaches can be shared as a link.
 */
export function DevPanel({
  step,
  mock,
  forced,
  onReset,
  pathname,
}: {
  step: OnboardingStep;
  mock: boolean;
  forced: ForcedState | null;
  onReset: () => void;
  pathname: string;
}) {
  // Starts collapsed so it never covers the step; remembers being opened.
  const [open, setOpen] = useState(false);
  useEffect(() => {
    try {
      setOpen(localStorage.getItem("agentfox.onboarding.dev.open") === "1");
    } catch {}
  }, []);
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem("agentfox.onboarding.dev.open", open ? "0" : "1");
    } catch {}
  };
  return (
    <aside
      className={cn("fixed right-4 bottom-20 z-[35] overflow-hidden rounded-lg border bg-card text-xs shadow-lg", open && "w-80")}
      aria-label="Onboarding dev"
    >
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 border-b bg-muted/60 px-3 py-2 font-semibold"
        onClick={toggle}
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <Wrench className="size-3.5 text-primary" /> Onboarding dev
        </span>
        {open ? <ChevronDown className="size-3.5" /> : <ChevronUp className="size-3.5" />}
      </button>
      {open && (
        <div className="flex flex-col gap-2.5 p-3">
          <Row label="Step">
            {STEPS.map(({ step: s, label }) => (
              <Link key={s} href={url(s, mock, forced)} className={cn(chip, s === step && on)}>
                {label}
              </Link>
            ))}
          </Row>
          <Row label="State">
            <Link href={url(step, mock, null)} className={cn(chip, !forced && on)}>
              real
            </Link>
            {STATES.map((s) => (
              <Link key={s} href={url(step, mock, s)} className={cn(chip, forced === s && on)}>
                {s}
              </Link>
            ))}
          </Row>
          <Row label="Data">
            <Link href={url(step, !mock, forced)} className={cn(chip, mock && on)}>
              mock {mock ? "on" : "off"}
            </Link>
            <button type="button" className={chip} onClick={onReset}>
              reset
            </button>
          </Row>
          <div className="font-mono text-[11px] text-muted-foreground">{pathname}</div>
        </div>
      )}
    </aside>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="w-11 text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

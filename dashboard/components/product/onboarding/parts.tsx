"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Copy,
  Download,
  Eye,
  Info,
  Lock,
  Plus,
  X,
} from "lucide-react";
import { Button } from "@/components/shadcn/button";
import { Card } from "@/components/shadcn/card";
import { cn } from "@/lib/utils";

/** Icons by name, so steps don't each import from lucide. */
const ICONS = {
  copy: Copy,
  check: Check,
  plus: Plus,
  lock: Lock,
  arrow: ArrowRight,
  back: ArrowLeft,
  info: Info,
  alert: AlertTriangle,
  close: X,
  download: Download,
  eye: Eye,
} as const;

export function Icon({ name, size = 16, className }: { name: keyof typeof ICONS; size?: number; className?: string }) {
  const C = ICONS[name];
  return <C size={size} className={className} aria-hidden="true" />;
}

/**
 * The top of every step: one centred heading and one line under it. Nothing else:
 * the screen below says what to do.
 */
export function StepHero({
  title,
  highlight,
  sub,
}: {
  /** Kept for callers; not shown. Progress lives in the bar at the top. */
  eyebrow?: string;
  title: string;
  /** The word in `title` to set in violet. */
  highlight?: string;
  sub?: React.ReactNode;
  aside?: React.ReactNode;
}) {
  const parts = highlight && title.includes(highlight) ? title.split(highlight) : null;
  return (
    <div className="text-center">
      <h1 id="ob-h" className="text-2xl font-semibold tracking-tight text-foreground">
        {parts ? (
          <>
            {parts[0]}
            <span className="text-primary">{highlight}</span>
            {parts.slice(1).join(highlight)}
          </>
        ) : (
          title
        )}
      </h1>
      {sub && <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** A white card with a header row, Opero-style. */
export function Panel({
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  title?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <Card className={cn("gap-0 rounded-lg py-0 shadow-xs", className)}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-3 border-b px-5 py-4">
          <div className="text-[15px] font-semibold">{title}</div>
          {action}
        </div>
      )}
      <div className={cn("p-5", bodyClassName)}>{children}</div>
    </Card>
  );
}

/** Coloured pill: red got through / risky, green safe, amber outside, violet info. */
export function Pill({
  tone = "neutral",
  mono,
  children,
  className,
}: {
  tone?: "neutral" | "red" | "green" | "amber" | "violet";
  mono?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: "bg-muted text-foreground",
    red: "bg-danger-soft text-danger-ink",
    green: "bg-success-soft text-success-ink",
    amber: "bg-warning-soft text-warning-ink",
    violet: "bg-violet-soft text-violet-ink",
  };
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-[4px] px-2 text-xs font-medium whitespace-nowrap",
        mono && "font-mono text-[11px] tracking-wide",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Dot({ tone, pulse }: { tone: "red" | "green" | "amber" | "grey"; pulse?: boolean }) {
  const c = { red: "bg-danger", green: "bg-success", amber: "bg-warning", grey: "bg-muted-foreground/40" }[tone];
  return (
    <span className="relative inline-flex size-2 shrink-0" aria-hidden="true">
      {pulse && <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", c)} />}
      <span className={cn("relative inline-flex size-2 rounded-full", c)} />
    </span>
  );
}

/** A one-line command with a copy button. */
export function Snippet({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex h-11 items-center justify-between gap-3 rounded-md border bg-muted/50 pr-1.5 pl-3.5 font-mono text-[13px]">
      <pre className="overflow-x-auto whitespace-pre">
        <span className="mr-2 text-muted-foreground select-none">$</span>
        {code}
      </pre>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={copied ? "Copied" : `Copy command: ${code}`}
        className={cn(copied && "text-success-ink")}
        onClick={() =>
          navigator.clipboard
            .writeText(code)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => setCopied(false))
        }
      >
        {copied ? <Check /> : <Copy />}
      </Button>
    </div>
  );
}

function StateCard({ icon, tone, children }: { icon?: React.ReactNode; tone?: "error"; children: React.ReactNode }) {
  return (
    <Card className="items-center gap-3 rounded-lg px-6 py-14 text-center shadow-xs">
      {icon && (
        <div
          className={cn(
            "grid size-10 place-items-center rounded-md",
            tone === "error" ? "bg-danger-soft text-danger-ink" : "bg-violet-soft text-violet-ink",
          )}
        >
          {icon}
        </div>
      )}
      {children}
    </Card>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <StateCard>
      <div className="size-6 animate-spin rounded-full border-2 border-border border-t-primary" aria-hidden="true" />
      <p className="text-sm text-muted-foreground" aria-busy="true">
        {label}
      </p>
    </StateCard>
  );
}

export function ErrorState({ title, detail, onRetry }: { title: string; detail?: string; onRetry?: () => void }) {
  return (
    <div role="alert">
      <StateCard icon={<AlertTriangle className="size-5" />} tone="error">
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {detail && <p className="max-w-md text-sm text-muted-foreground">{detail}</p>}
        {onRetry && (
          <Button variant="outline" className="mt-2" onClick={onRetry}>
            Try again
          </Button>
        )}
      </StateCard>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: { label: string; href: string };
}) {
  return (
    <StateCard icon={<Info className="size-5" />}>
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{detail}</p>
      {action && (
        <Button asChild variant="outline" className="mt-2">
          <Link href={action.href}>{action.label}</Link>
        </Button>
      )}
    </StateCard>
  );
}

/** Calls `fn` every `ms` while `active`, and once immediately. */
export function usePoll(fn: () => void | Promise<void>, ms: number, active: boolean) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await saved.current();
      } finally {
        if (!stopped) timer = setTimeout(tick, ms);
      }
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [ms, active]);
}

/** "About 1 minute left", "About 6 seconds left". */
export function timeLeft(ms: number): string {
  const s = Math.ceil(ms / 1000);
  if (s <= 1) return "Almost done";
  if (s < 60) return `About ${s} seconds left`;
  const m = Math.round(s / 60);
  return `About ${m} minute${m === 1 ? "" : "s"} left`;
}

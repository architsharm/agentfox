"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Check, Copy, KeyRound, Loader2 } from "lucide-react";
import { Logo } from "@/components/product/Logo";
import { onboardingApi } from "@/lib/product/onboarding/api";
import { INITIAL_STATE } from "@/lib/product/onboarding/steps";
import type { OnboardingKey, Structure } from "@/lib/product/onboarding/types";
import { isFreshConnection } from "@/lib/product/onboarding/connect";
import { MAP_PROJECT_COOKIE, PROJECT_COOKIE_AGE } from "@/lib/product/project";
import { cn } from "@/lib/utils";

/** What the card is doing, in order. Each step after "waiting" is driven by a real answer. */
type Phase = "key" | "waiting" | "found" | "fetching" | "guarding" | "done";

/** Each progress line stays up at least this long, so it reads as a step and not a flash. */
const STEP_MS = 1400;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** Run `work`, but take at least `ms`. */
async function atLeast<T>(ms: number, work: Promise<T>): Promise<T> {
  const [v] = await Promise.all([work, sleep(ms)]);
  return v;
}

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

/**
 * Connecting a project, inside the dashboard. Three steps: create a key, run
 * `agentfox init` where the agents live, and watch them arrive. The third step is
 * live: it waits for a connection made *after* this page opened (an older one does
 * not count), then says what it found, fetches the project, checks its guardrails,
 * and opens its map.
 *
 * `hasProjects`: someone adding a second project cannot skip; there is nothing to
 * skip to that isn't already one click away in the sidebar.
 */
export function SetupCard({
  server,
  hasProjects = false,
  onSkip,
}: {
  server: string;
  hasProjects?: boolean;
  /** Fold the card away on this page (NewProjectPage); it stays folded on every page. */
  onSkip?: () => void;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const mock = params.get("mock") === "1";
  const api = useMemo(() => onboardingApi(mock), [mock]);

  const [phase, setPhase] = useState<Phase>("key");
  const [key, setKey] = useState<string | null>(null);
  // What the server says about the key: it is shown in full only when just made.
  const [keyInfo, setKeyInfo] = useState<OnboardingKey | null>(null);
  const [replacing, setReplacing] = useState(false);
  // Agents init proposes wait to be added; the person here adds them in one click.
  const [approved, setApproved] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [found, setFound] = useState<Structure | null>(null);
  const [detail, setDetail] = useState<Partial<Record<Phase, string>>>({});
  // The connection that existed when the page opened: only a newer one is "you".
  const baseline = useRef<{ connected: boolean; at: string | null } | null>(mock ? { connected: false, at: null } : null);

  useEffect(() => {
    if (mock) return;
    api
      .getStructure()
      .then((r: any) => (baseline.current = { connected: Boolean(r.connected), at: r.connectedAt ?? null }))
      .catch(() => (baseline.current = { connected: false, at: null }));
  }, [api, mock]);

  // Waiting: poll until `agentfox init` reports in.
  useEffect(() => {
    if (phase !== "waiting") return;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      try {
        const r: any = await api.getStructure({ live: true });
        const fresh = isFreshConnection(baseline.current, r);
        if (fresh && !stop) {
          setFound(r.structure);
          setPhase("found");
          return;
        }
      } catch {
        // Retried on the next tick.
      }
      if (!stop) setTimeout(tick, mock ? 600 : 2000);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [phase, api, mock]);

  // Found: say what arrived, and wait for the agents to be added.
  useEffect(() => {
    if (!found) return;
    const tools = found.tools.length;
    setDetail((d) => ({
      ...d,
      found: `${found.agents.map((a) => a.name).join(", ")} · ${tools} ${tools === 1 ? "tool" : "tools"}`,
    }));
  }, [found]);

  // Added: fetch the project, check its guardrails, open it. Keyed on `approved`
  // alone: each step moves `phase` on, and that must not cancel the sequence.
  useEffect(() => {
    if (!found || !approved) return;
    let stop = false;
    (async () => {
      const agents = found.agents as (Structure["agents"][number] & { slug?: string })[];
      const slug = agents[0]?.slug;

      setPhase("fetching");
      // The project is the one the agent init just registered belongs to.
      const agent = slug && !mock ? await atLeast(STEP_MS, getJson<{ project?: string }>(`/api/agents/${encodeURIComponent(slug)}`)) : null;
      if (mock || !slug) await sleep(STEP_MS);
      const project = agent?.project ?? null;
      const map = project ? await getJson<any>(`/api/projects/${encodeURIComponent(project)}/map`) : null;
      const n = map?.agents?.length ?? agents.length;
      setDetail((d) => ({ ...d, fetching: `${project ?? "your project"} · ${n} ${n === 1 ? "agent" : "agents"}` }));
      if (stop) return;

      setPhase("guarding");
      // Connecting a project queues its first attack test: the agent as it is.
      const tests = project && !mock ? await atLeast(STEP_MS, getJson<any>(`/api/onboarding/projects/${encodeURIComponent(project)}/tests`)) : null;
      if (mock || !project) await sleep(STEP_MS);
      setDetail((d) => ({
        ...d,
        guarding: tests?.first
          ? `${tests.first.total ?? "The"} attacks on your agent as it is, no guardrails yet. Tools are faked, nothing real happens. Results show beside the map.`
          : "No tools found to test yet.",
      }));
      if (stop) return;

      setPhase("done");
      await sleep(900);
      try {
        const state = await api.getState();
        await api.saveState({ ...state, completedSteps: ["connect", "install", "structure"], completedAt: new Date().toISOString() });
      } catch {
        // Setup state is a convenience; the project is already set up.
      }
      if (project) document.cookie = `${MAP_PROJECT_COOKIE}=${encodeURIComponent(project)}; path=/; max-age=${PROJECT_COOKIE_AGE}; samesite=lax`;
      router.push(slug ? `/app/projects/${encodeURIComponent(slug)}` : "/app/map");
      router.refresh();
    })();
    return () => {
      stop = true;
    };
  }, [found, approved, api, mock, router]);

  // `agentfox init` only proposes agents (a setup key can't add them by itself); the
  // person here, who made the key, adds them.
  const addAgents = async () => {
    if (!found) return;
    setAdding(true);
    setAddError("");
    try {
      const slug = (found.agents[0] as { slug?: string } | undefined)?.slug;
      const agent = slug && !mock ? await getJson<{ project?: string }>(`/api/agents/${encodeURIComponent(slug)}`) : null;
      if (agent?.project) {
        const r = await fetch(`/api/projects/${encodeURIComponent(agent.project)}/approve`, { method: "POST" });
        if (!r.ok) {
          setAddError(
            r.status === 403
              ? "You can't add agents in this workspace. Ask someone who can, or open the map to look first."
              : "Couldn't add them. Try again, or open the map and add them there.",
          );
          return;
        }
      }
      setApproved(true);
    } catch {
      setAddError("Couldn't reach AgentFox. Try again.");
    } finally {
      setAdding(false);
    }
  };

  const createKey = async () => {
    setCreating(true);
    setError("");
    try {
      const k = await api.getKey();
      setKeyInfo(k);
      setKey(k.value);
      // An existing key isn't shown again, but whoever saved it can run init with it.
      setPhase("waiting");
    } catch (e: any) {
      setError(e?.message || "Couldn't create a key. Try again.");
    } finally {
      setCreating(false);
    }
  };

  const replaceKey = async () => {
    setCreating(true);
    setError("");
    try {
      const k = await api.rotateKey();
      setKeyInfo(k);
      setKey(k.value);
      setReplacing(false);
      setPhase("waiting");
    } catch (e: any) {
      setError(e?.message || "Couldn't make a new key. Try again.");
    } finally {
      setCreating(false);
    }
  };

  // Skip: fold the card into a slim bar on every page (see NewProjectPage).
  const skip = async () => {
    try {
      await api.saveState({ ...(await api.getState().catch(() => INITIAL_STATE)), skipped: true });
    } catch {
      // Remembered in the browser either way.
    } finally {
      document.cookie = `agentfox_setup_skipped=1; path=/; max-age=${PROJECT_COOKIE_AGE}; samesite=lax`;
      onSkip?.();
    }
  };

  const shownKey = key ?? "<your-key>";
  // A key exists, shown now or earlier: the next steps can go ahead.
  const haveKey = Boolean(key || keyInfo?.hasKey);

  return (
    <div className="tw mx-auto mt-8 w-full max-w-[640px] text-sm text-foreground">
      <section className="overflow-hidden rounded-xl border bg-card shadow-[var(--af-shadow-1)]" aria-labelledby="setup-h">
        <header className="flex items-start gap-4 px-7 pt-7 pb-6">
          <Logo size={38} />
          <div className="min-w-0 flex-1">
            <h1 id="setup-h" className="text-[22px] leading-7 font-semibold tracking-tight">
              {hasProjects ? "Connect a new project" : "Connect your first agent"}
            </h1>
            <p className="mt-1 text-muted-foreground">
              AgentFox reads your agents from their code, maps the tools they can call, and guards every call. Two steps.
            </p>
          </div>
          {!hasProjects && (
            <button type="button" onClick={skip} className="shrink-0 text-[13px] text-muted-foreground hover:text-foreground">
              Skip for now
            </button>
          )}
        </header>

        <ol className="px-7 pb-7">
          <Step n={1} title="Create a key" state={haveKey ? "done" : "active"}>
            {key ? (
              <>
                <p className="text-muted-foreground">
                  Your key. <strong className="font-medium text-foreground">Copy it now: it&apos;s shown only once.</strong>{" "}
                  <code className="font-mono text-[12.5px]">agentfox init</code> uses it to send your agents&apos; map here. It can&apos;t read your data or
                  change this workspace.
                </p>
                <Code text={key} className="mt-3" />
              </>
            ) : keyInfo?.hasKey ? (
              <>
                <p className="text-muted-foreground">
                  You already have a key{keyInfo.prefix ? <> (<code className="font-mono text-[12.5px]">{keyInfo.prefix}…</code>)</> : null}
                  {keyInfo.createdAt ? `, made ${new Date(keyInfo.createdAt).toLocaleDateString()}` : ""}. It&apos;s shown only when it&apos;s made: use the one
                  you saved, or make a new one.
                </p>
                {replacing ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2" role="alertdialog" aria-label="Make a new key">
                    <span className="text-[13px]">The old key stops working, including in a running agentfox init.</span>
                    <button
                      type="button"
                      onClick={replaceKey}
                      disabled={creating}
                      className="inline-flex h-8 items-center gap-2 rounded-md bg-primary px-3.5 text-[13px] font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-60"
                    >
                      {creating ? <Loader2 className="size-3.5 animate-spin" /> : <KeyRound className="size-3.5" />}
                      {creating ? "Making…" : "Make a new key"}
                    </button>
                    <button type="button" onClick={() => setReplacing(false)} className="h-8 px-2 text-[13px] text-muted-foreground hover:text-foreground">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setReplacing(true)}
                    className="mt-3 inline-flex h-8 items-center gap-2 rounded-md border bg-card px-3.5 text-[13px] font-medium hover:bg-muted"
                  >
                    <KeyRound className="size-3.5" /> Make a new key
                  </button>
                )}
                {error && (
                  <p className="mt-2 text-danger-ink" role="alert">
                    {error}
                  </p>
                )}
              </>
            ) : (
              <>
                <p className="text-muted-foreground">One key connects every agent in a repository.</p>
                <button
                  type="button"
                  onClick={createKey}
                  disabled={creating}
                  className="mt-3 inline-flex h-8 items-center gap-2 rounded-md bg-primary px-3.5 text-[13px] font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-60"
                >
                  {creating ? <Loader2 className="size-3.5 animate-spin" /> : <KeyRound className="size-3.5" />}
                  {creating ? "Creating…" : "Create a key"}
                </button>
                {error && (
                  <p className="mt-2 text-danger-ink" role="alert">
                    {error}
                  </p>
                )}
              </>
            )}
          </Step>

          <Step n={2} title="Run AgentFox where your agents live" state={phase === "key" ? "todo" : phase === "waiting" ? "active" : "done"} >
            <p className="text-muted-foreground">In the repository. It finds every agent and tool and reports them here.</p>
            <Install keyText={shownKey} server={server} muted={!key} />
          </Step>

          <Step n={3} title="Your agents arrive" state={phase === "done" ? "done" : haveKey ? "active" : "todo"} last>
            {!haveKey ? (
              <p className="text-muted-foreground">Appears here the moment init reports in.</p>
            ) : phase === "waiting" ? (
              <Waiting />
            ) : (
              <>
                <Progress phase={phase} detail={detail} paused={phase === "found" && !approved} />
                {phase === "found" && !approved && (
                  <div className="mt-3">
                    <p className="text-muted-foreground">
                      init found {found?.agents.length === 1 ? "this agent" : `these ${found?.agents.length} agents`}. Add{" "}
                      {found?.agents.length === 1 ? "it" : "them"} to AgentFox to guard and test {found?.agents.length === 1 ? "it" : "them"}.
                    </p>
                    <button
                      type="button"
                      onClick={addAgents}
                      disabled={adding}
                      className="mt-3 inline-flex h-8 items-center gap-2 rounded-md bg-primary px-3.5 text-[13px] font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-60"
                    >
                      {adding ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
                      {adding ? "Adding…" : found?.agents.length === 1 ? "Add to AgentFox" : `Add ${found?.agents.length} agents to AgentFox`}
                    </button>
                    {addError && (
                      <p className="mt-2 text-danger-ink" role="alert">
                        {addError}
                      </p>
                    )}
                  </div>
                )}
              </>
            )}
          </Step>
        </ol>

        <footer className="flex flex-wrap gap-5 border-t bg-muted/50 px-7 py-3 text-[13px]">
          <FooterLink href="/docs/guides/python-auto">Read the full guide</FooterLink>
          <FooterLink href="/app/welcome">Scan a repository instead</FooterLink>
        </footer>
      </section>
    </div>
  );
}

function Step({
  n,
  title,
  state,
  last,
  children,
}: {
  n: number;
  title: string;
  state: "todo" | "active" | "done";
  last?: boolean;
  children: React.ReactNode;
}) {
  return (
    <li className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-x-4">
      {!last && <span className="absolute top-8 bottom-0 left-[13.5px] w-px bg-border" aria-hidden />}
      <span
        className={cn(
          "relative z-[1] grid size-7 place-items-center rounded-full border text-[12px] font-semibold",
          state === "done" && "border-success bg-success text-white",
          state === "active" && "border-primary bg-card text-primary",
          state === "todo" && "border-border bg-card text-muted-foreground",
        )}
        aria-hidden
      >
        {state === "done" ? <Check className="size-3.5" strokeWidth={3} /> : n}
      </span>
      <div className={cn("pb-7", last && "pb-0")}>
        <h2 className="mb-1 pt-1 text-[15px] font-semibold">{title}</h2>
        {children}
      </div>
    </li>
  );
}

/**
 * The command. Always with `--server`: init's default is a gateway on this machine,
 * which is only right for a local install. Pinned to 0.5, the first release with
 * `init --key` (0.4 has no such option and failed as "no such option --key").
 */
function Install({ keyText, server, muted }: { keyText: string; server: string; muted: boolean }) {
  const cmd = `pip install "agentfox>=0.5"\nagentfox init --key ${keyText} --server ${server}`;
  return (
    <div className="mt-3">
      <Code text={cmd} muted={muted} />
    </div>
  );
}

function Code({ text, className, muted }: { text: string; className?: string; muted?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className={cn("relative rounded-lg border bg-muted px-4 py-3", className)}>
      <pre className={cn("overflow-x-auto pr-10 font-mono text-[12.5px] leading-6 whitespace-pre", muted && "text-muted-foreground")}>{text}</pre>
      <button
        type="button"
        aria-label={copied ? "Copied" : "Copy"}
        className="absolute top-2.5 right-2.5 grid size-7 place-items-center rounded-md border bg-card text-muted-foreground hover:text-foreground"
        onClick={() =>
          navigator.clipboard
            .writeText(text)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => setCopied(false))
        }
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}

/** Step 3 before anything arrives: we're listening, and it moves on by itself. */
function Waiting() {
  return (
    <div className="mt-2 flex items-center gap-4 rounded-lg border border-dashed bg-background px-4 py-4" aria-live="polite">
      <span className="relative grid size-9 shrink-0 place-items-center">
        <span className="absolute inset-0 animate-ping rounded-full bg-primary/20" />
        <span className="absolute inset-2 rounded-full bg-primary/15" />
        <span className="relative size-2.5 rounded-full bg-primary" />
      </span>
      <div>
        <p className="font-medium">Waiting for you to run agentfox init…</p>
        <p className="text-[13px] text-muted-foreground">This moves on by itself the moment your agents report in.</p>
      </div>
    </div>
  );
}

const LINES: { phase: Phase; label: string; doing: string }[] = [
  { phase: "found", label: "Agents identified", doing: "Reading what init found" },
  { phase: "fetching", label: "Fetching your agents", doing: "Fetching your agents" },
  { phase: "guarding", label: "Attack test started", doing: "Starting the attack test" },
  { phase: "done", label: "Opening your map", doing: "Opening your map" },
];
const ORDER: Phase[] = ["found", "fetching", "guarding", "done"];

/** Step 3 once init reports in: each line ticks over as its step really finishes.
 * `paused`: waiting on the person (adding the agents), so the current line is done, not spinning. */
function Progress({ phase, detail, paused }: { phase: Phase; detail: Partial<Record<Phase, string>>; paused?: boolean }) {
  const at = ORDER.indexOf(phase);
  return (
    <ul className="mt-2 flex flex-col gap-2.5 rounded-lg border bg-background px-4 py-3.5" aria-live="polite">
      {LINES.map((l, i) => {
        const state = i < at || ((phase === "done" || paused) && i === at) ? "done" : i === at ? "active" : "todo";
        return (
          <li key={l.phase} className="flex items-start gap-3">
            <span className="mt-0.5 grid size-4 shrink-0 place-items-center">
              {state === "done" ? (
                <Check className="size-4 text-success" strokeWidth={2.5} />
              ) : state === "active" ? (
                <Loader2 className="size-4 animate-spin text-primary" />
              ) : (
                <span className="size-2 rounded-full bg-border" />
              )}
            </span>
            <span className="min-w-0">
              <span className={cn("block", state === "todo" ? "text-muted-foreground" : "font-medium")}>
                {state === "active" ? `${l.doing}…` : l.label}
              </span>
              {detail[l.phase] && state !== "todo" && <span className="block text-[12.5px] text-muted-foreground">{detail[l.phase]}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="inline-flex items-center gap-1 text-link hover:underline">
      {children} <ArrowUpRight className="size-3.5" />
    </Link>
  );
}

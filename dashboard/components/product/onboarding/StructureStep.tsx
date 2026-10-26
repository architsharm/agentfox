"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/shadcn/button";
import { Input } from "@/components/shadcn/input";
import { Label } from "@/components/shadcn/label";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/shadcn/sheet";
import { RISK_WHY, STRUCTURE } from "@/lib/product/onboarding/fixtures";
import { riskyToolCount } from "@/lib/product/onboarding/steps";
import type { Risk, Structure } from "@/lib/product/onboarding/types";
import { cn } from "@/lib/utils";
import { ContinueLabel, StepFooter, useOnboarding } from "./OnboardingFlow";
import { ErrorState, Panel, Pill, StepHero } from "./parts";

type Tool = Structure["tools"][number];
type Adding = "tool" | "agent" | null;
const EMPTY: Structure = { sources: [], agents: [], tools: [], systems: [] };


const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "item";

const RISK_TONE = { high: "red", outside: "amber", read_only: "neutral" } as const;

const RISK_LABEL: Record<Risk, string> = {
  high: "Can do real damage",
  outside: "Talks to the outside",
  read_only: "Read only",
};

const RISK_HELP: Record<Risk, string> = {
  high: "Moves money, changes or deletes data, or exports personal data.",
  outside: "Sends something outside: email, a webhook, a ticket, an API call.",
  read_only: "Only looks things up. It can't change anything.",
};

/** How long the "identifying" screen shows at least, so it reads as a step and not a flash. */
const DETECT_MS = 2400;

export function StructureStep() {
  const { api, forced, finish } = useOnboarding();
  const [structure, setStructure] = useState<Structure | null>(null);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [open, setOpen] = useState<Tool | null>(null);
  const [adding, setAdding] = useState<Adding>(null);
  const [detecting, setDetecting] = useState(true);

  const load = useCallback(() => {
    setError("");
    setStructure(null);
    api
      .getStructure()
      .then((r) => setStructure(r.structure))
      .catch((e) => setError(e?.message || "Couldn't load your project."));
  }, [api]);
  useEffect(load, [load]);
  useEffect(() => {
    const t = setTimeout(() => setDetecting(false), DETECT_MS);
    return () => clearTimeout(t);
  }, []);

  const update = (next: Structure) => {
    setStructure(next);
    setSaveError("");
    api.saveStructure(next).catch((e) => setSaveError(e?.message || "Couldn't save that change. Try again."));
  };

  const s =
    forced === "loading" || forced === "error"
      ? null
      : forced === "empty"
        ? EMPTY
        : forced === "success"
          ? STRUCTURE
          : structure;
  const err = forced === "error" ? "We couldn't read your project. Try again in a moment." : forced ? "" : error;

  if (err) return <ErrorState title="Couldn't read your project" detail={err} onRetry={load} />;
  if (forced === "loading" || ((!s || detecting) && !forced)) return <Detecting />;
  if (!s) return <Detecting />;

  const risky = riskyToolCount(s);
  const empty = s.agents.length === 0;

  return (
    <section className="flex flex-col gap-6" aria-labelledby="ob-h">
      <StepHero
        title={empty ? "We didn't find any agents" : `We found ${plural(s.agents.length, "agent")}`}
        highlight={empty ? undefined : plural(s.agents.length, "agent")}
        sub={empty ? "Add your agent and its tools, and we'll test them." : "Check the list. Add anything we missed."}
      />

      {!empty && (
        <Panel bodyClassName="p-0">
          <ul>
            {s.agents.map((a) => {
              const tools = s.tools.filter((t) => t.agentId === a.id);
              return (
                <li key={a.id} className="border-b last:border-0">
                  <div className="flex items-center justify-between gap-3 px-4 pt-3.5 pb-2">
                    <span className="flex items-center gap-2 font-medium">
                      {a.name}
                      {a.addedByUser && <Pill tone="violet">Added by you</Pill>}
                    </span>
                    <Pill mono>{a.model}</Pill>
                  </div>
                  <ul className="px-2 pb-2">
                    {tools.length === 0 && <li className="px-2 py-2 text-sm text-muted-foreground">No tools yet</li>}
                    {tools.map((t) => (
                      <li key={t.id}>
                        <button
                          type="button"
                          onClick={() => setOpen(t)}
                          className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted"
                          aria-label={`${t.name}, ${RISK_LABEL[t.risk]}. Show details`}
                        >
                          <code className="font-mono text-[13px]">{t.name}</code>
                          <Pill tone={RISK_TONE[t.risk]}>{RISK_LABEL[t.risk]}</Pill>
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        </Panel>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Button variant="outline" className="h-10 border-dashed" onClick={() => setAdding("agent")}>
          <Plus /> Add an agent
        </Button>
        <Button
          variant="outline"
          className="h-10 border-dashed"
          onClick={() => setAdding("tool")}
          disabled={empty}
          title={empty ? "Add an agent first" : undefined}
        >
          <Plus /> Add a tool
        </Button>
      </div>
      {saveError && (
        <p className="text-center text-sm text-danger-ink" role="alert">
          {saveError}
        </p>
      )}

      <ToolSheet
        tool={open}
        structure={s}
        onClose={() => setOpen(null)}
        onRemove={(id) => {
          update(removeTool(s, id));
          setOpen(null);
        }}
      />
      <AddToolSheet
        open={adding === "tool"}
        structure={s}
        onClose={() => setAdding(null)}
        onAdd={(next) => {
          update(next);
          setAdding(null);
        }}
      />
      <AddAgentSheet
        open={adding === "agent"}
        structure={s}
        onClose={() => setAdding(null)}
        onAdd={(next) => {
          update(next);
          setAdding(null);
        }}
      />

      <StepFooter hint={risky > 0 ? `${risky} ${risky === 1 ? "tool" : "tools"} can do real damage` : undefined}>
        <Button size="lg" onClick={() => finish("structure")} disabled={s.tools.length === 0}>
          <ContinueLabel>Test how safe this is</ContinueLabel>
        </Button>
      </StepFooter>
    </section>
  );
}

/** The loading screen: what we're doing, and a bar that moves. */
function Detecting() {
  return (
    <section className="flex flex-col items-center gap-6 pt-10 text-center" aria-busy="true" aria-labelledby="ob-h">
      <StepHero title="Identifying and installing guardrails in your project" highlight="guardrails" />
      <div className="h-1 w-64 overflow-hidden rounded-[1px] bg-border" aria-hidden="true">
        <div className="h-full w-1/3 animate-[ob-slide_1.2s_ease-in-out_infinite] bg-primary" />
      </div>
    </section>
  );
}

/** Drop a tool, and any system nothing touches any more. */
function removeTool(s: Structure, toolId: string): Structure {
  const tools = s.tools.filter((t) => t.id !== toolId);
  const used = new Set(tools.map((t) => t.systemId));
  return { ...s, tools, systems: s.systems.filter((x) => used.has(x.id)) };
}

function ToolSheet({
  tool,
  structure,
  onClose,
  onRemove,
}: {
  tool: Tool | null;
  structure: Structure;
  onClose: () => void;
  onRemove: (id: string) => void;
}) {
  const agent = tool && structure.agents.find((a) => a.id === tool.agentId);
  const system = tool && structure.systems.find((s) => s.id === tool.systemId);
  return (
    <Sheet open={Boolean(tool)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="tw gap-0 rounded-none sm:max-w-md">
        {tool && (
          <>
            <SheetHeader className="border-b">
              <SheetTitle className="font-mono text-base">{tool.name}</SheetTitle>
              <SheetDescription asChild>
                <span>
                  <Pill tone={RISK_TONE[tool.risk]}>{RISK_LABEL[tool.risk]}</Pill>
                </span>
              </SheetDescription>
            </SheetHeader>
            <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4 text-sm">
              <div>
                <h3 className="mb-1 text-xs font-medium text-muted-foreground">What it can do</h3>
                <p>{tool.whatItDoes}</p>
              </div>
              <div>
                <h3 className="mb-1 text-xs font-medium text-muted-foreground">Why it matters</h3>
                <p>{RISK_WHY[tool.risk]}</p>
              </div>
              <dl className="grid grid-cols-[88px_1fr] gap-2 border-t pt-4">
                <dt className="text-muted-foreground">Agent</dt>
                <dd className="font-mono">{agent?.name ?? "—"}</dd>
                <dt className="text-muted-foreground">Touches</dt>
                <dd className="font-mono">{system?.name ?? "—"}</dd>
              </dl>
            </div>
            <SheetFooter className="border-t">
              <Button variant="outline" className="text-danger-ink hover:bg-danger-soft hover:text-danger-ink" onClick={() => onRemove(tool.id)}>
                <Trash2 /> Remove from map
              </Button>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

const NEW = "__new__";

/** What kind of system a name the user typed is, so it reads right on the map. */
function guessKind(name: string, risk: Risk): string {
  const n = name.toLowerCase();
  if (/pay|bank|stripe|refund|charge|billing|invoice|wallet/.test(n)) return "payments";
  if (/mail|smtp|sendgrid/.test(n)) return "email";
  if (/crm|customer|salesforce|hubspot|contact/.test(n)) return "crm";
  if (/zendesk|ticket|helpdesk|intercom|support/.test(n)) return "helpdesk";
  if (/sql|postgres|mysql|mongo|database|\bdb\b|redis|table/.test(n)) return "database";
  return risk === "high" ? "database" : "external";
}

const selectCls =
  "h-9 w-full rounded-md border border-input bg-card px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

function FormSheet({
  open,
  title,
  description,
  onClose,
  onSubmit,
  submitLabel,
  children,
}: {
  open: boolean;
  title: string;
  description: string;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  submitLabel: string;
  children: React.ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="tw gap-0 rounded-none sm:max-w-md">
        <form onSubmit={onSubmit} noValidate className="flex h-full flex-col">
          <SheetHeader className="border-b">
            <SheetTitle className="text-base">{title}</SheetTitle>
            <SheetDescription>{description}</SheetDescription>
          </SheetHeader>
          <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4">{children}</div>
          <SheetFooter className="flex-row justify-end border-t">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">{submitLabel}</Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}

function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <span className="text-xs text-danger-ink" role="alert">
          {error}
        </span>
      ) : (
        hint && <span className="text-xs text-muted-foreground">{hint}</span>
      )}
    </div>
  );
}

function AddToolSheet({
  open,
  structure,
  onClose,
  onAdd,
}: {
  open: boolean;
  structure: Structure;
  onClose: () => void;
  onAdd: (s: Structure) => void;
}) {
  const [name, setName] = useState("");
  const [what, setWhat] = useState("");
  const [agentId, setAgentId] = useState("");
  const [risk, setRisk] = useState<Risk>("high");
  const [systemId, setSystemId] = useState("");
  const [newSystem, setNewSystem] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Fresh form every time it opens.
  useEffect(() => {
    if (!open) return;
    setName("");
    setWhat("");
    setAgentId(structure.agents[0]?.id ?? "");
    setRisk("high");
    setSystemId(structure.systems[0]?.id ?? NEW);
    setNewSystem("");
    setErrors({});
  }, [open, structure.agents, structure.systems]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = name.trim();
    const next: Record<string, string> = {};
    if (!clean) next.name = "Enter the tool's name, as it appears in your code.";
    else if (/\s/.test(clean)) next.name = "Tool names can't contain spaces. Try get_order or orders.refund.";
    else if (structure.tools.some((t) => t.name === clean && t.agentId === agentId))
      next.name = "This agent already has a tool with that name.";
    if (!what.trim()) next.what = "Say in one sentence what it does.";
    if (systemId === NEW && !newSystem.trim()) next.system = "Name what it touches, e.g. Stripe or Postgres.";
    setErrors(next);
    if (Object.keys(next).length) return;

    let systems = structure.systems;
    let sysId = systemId;
    if (systemId === NEW) {
      sysId = `sys-${slug(newSystem)}`;
      if (!systems.some((x) => x.id === sysId))
        systems = [...systems, { id: sysId, name: newSystem.trim(), kind: guessKind(newSystem, risk) }];
    }
    onAdd({
      ...structure,
      systems,
      tools: [
        ...structure.tools,
        {
          id: `t-${agentId}-${slug(clean)}-${Date.now().toString(36)}`,
          name: clean,
          agentId,
          risk,
          whatItDoes: what.trim().replace(/([^.!?])$/, "$1."),
          systemId: sysId,
          addedByUser: true,
        },
      ],
    });
  };

  return (
    <FormSheet
      open={open}
      title="Add a tool"
      description="Anything your agent can call that we didn't find. We'll test it with the rest."
      onClose={onClose}
      onSubmit={submit}
      submitLabel="Add tool"
    >
      <Field id="tool-name" label="Tool name" error={errors.name} hint="As it appears in your code.">
        <Input
          id="tool-name"
          className="font-mono"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setErrors((x) => ({ ...x, name: "" }));
          }}
          placeholder="orders.refund"
          aria-invalid={Boolean(errors.name)}
          autoFocus
        />
      </Field>
      <Field id="tool-what" label="What it does" error={errors.what}>
        <Input
          id="tool-what"
          value={what}
          onChange={(e) => {
            setWhat(e.target.value);
            setErrors((x) => ({ ...x, what: "" }));
          }}
          placeholder="Sends money back to a customer's card"
          aria-invalid={Boolean(errors.what)}
        />
      </Field>
      <Field id="tool-agent" label="Used by">
        <select id="tool-agent" className={selectCls} value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          {structure.agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 text-sm font-medium">What can it do?</legend>
        {(["high", "outside", "read_only"] as Risk[]).map((r) => (
          <label
            key={r}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors hover:bg-muted/50",
              risk === r && "border-primary bg-violet-soft/60 ring-[3px] ring-primary/10",
            )}
          >
            <input type="radio" name="risk" value={r} checked={risk === r} onChange={() => setRisk(r)} className="mt-1 accent-primary" />
            <span className="flex flex-col items-start gap-1">
              <Pill tone={RISK_TONE[r]}>{RISK_LABEL[r]}</Pill>
              <span className="text-xs text-muted-foreground">{RISK_HELP[r]}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <Field id="tool-system" label="What it touches" error={errors.system}>
        <select id="tool-system" className={selectCls} value={systemId} onChange={(e) => setSystemId(e.target.value)}>
          {structure.systems.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
          <option value={NEW}>Something else…</option>
        </select>
        {systemId === NEW && (
          <Input
            value={newSystem}
            onChange={(e) => {
              setNewSystem(e.target.value);
              setErrors((x) => ({ ...x, system: "" }));
            }}
            placeholder="Stripe, Postgres, Zendesk…"
            aria-label="What it touches"
            aria-invalid={Boolean(errors.system)}
          />
        )}
      </Field>
    </FormSheet>
  );
}

function AddAgentSheet({
  open,
  structure,
  onClose,
  onAdd,
}: {
  open: boolean;
  structure: Structure;
  onClose: () => void;
  onAdd: (s: Structure) => void;
}) {
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [newSource, setNewSource] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    setName("");
    setModel("");
    setSourceId(structure.sources[0]?.id ?? NEW);
    setNewSource("");
    setErrors({});
  }, [open, structure.sources]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const clean = name.trim();
    const next: Record<string, string> = {};
    if (!clean) next.name = "Give the agent a name.";
    else if (structure.agents.some((a) => a.name.toLowerCase() === clean.toLowerCase()))
      next.name = "There's already an agent with that name.";
    if (!model.trim()) next.model = "Which model does it use? e.g. gpt-4o or claude-sonnet.";
    if (sourceId === NEW && !newSource.trim()) next.source = "Who talks to it? e.g. Customers or Employees.";
    setErrors(next);
    if (Object.keys(next).length) return;

    let sources = structure.sources;
    let srcId = sourceId;
    if (sourceId === NEW) {
      srcId = `src-${slug(newSource)}`;
      if (!sources.some((x) => x.id === srcId)) sources = [...sources, { id: srcId, label: newSource.trim() }];
    }
    onAdd({
      ...structure,
      sources,
      agents: [
        ...structure.agents,
        {
          id: `ag-${slug(clean)}-${Date.now().toString(36)}`,
          name: clean,
          model: model.trim(),
          sourceIds: [srcId],
          addedByUser: true,
        },
      ],
    });
  };

  return (
    <FormSheet
      open={open}
      title="Add an agent"
      description="An agent we didn't find in the code. Add its tools next."
      onClose={onClose}
      onSubmit={submit}
      submitLabel="Add agent"
    >
      <Field id="agent-name" label="Agent name" error={errors.name}>
        <Input
          id="agent-name"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setErrors((x) => ({ ...x, name: "" }));
          }}
          placeholder="billing-bot"
          aria-invalid={Boolean(errors.name)}
          autoFocus
        />
      </Field>
      <Field id="agent-model" label="Model" error={errors.model}>
        <Input
          id="agent-model"
          className="font-mono"
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
            setErrors((x) => ({ ...x, model: "" }));
          }}
          placeholder="gpt-4o"
          aria-invalid={Boolean(errors.model)}
        />
      </Field>
      <Field id="agent-source" label="Who talks to it" error={errors.source}>
        <select id="agent-source" className={selectCls} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          {structure.sources.map((x) => (
            <option key={x.id} value={x.id}>
              {x.label}
            </option>
          ))}
          <option value={NEW}>Someone else…</option>
        </select>
        {sourceId === NEW && (
          <Input
            value={newSource}
            onChange={(e) => {
              setNewSource(e.target.value);
              setErrors((x) => ({ ...x, source: "" }));
            }}
            placeholder="Customers, Employees, Partners…"
            aria-label="Who talks to it"
            aria-invalid={Boolean(errors.source)}
          />
        )}
      </Field>
    </FormSheet>
  );
}

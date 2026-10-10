import Link from "next/link";
import { safeApi } from "@/lib/product/api";
import { Card, Empty, Pill } from "@/components/kit";
import { Act } from "@/components/kit/Act";
import { detectorName } from "@/lib/product/vocab";
import { ModelForm, ModelTest, PullButton, TierSwitch, type PostureDoc } from "./ChecksControls";
import { AccessCheckForm, AccessCheckTest } from "./AccessChecks";

type Detector = {
  key: string;
  label: string | null;
  available: boolean;
  enabled: boolean;
  always_on: boolean;
  unavailable_reason: string | null;
  install: string | null;
  stats: { runs?: number; avg_ms?: number };
  group: string;
  source: "builtin" | "open_source" | "llm_judge" | "yours";
  where: string[];
  models: { id: string; license: string | null }[];
  license: string | null;
  pull_blocked: string | null;
  pull_job: { id: string; status: string; last_error?: string | null } | null;
};

type Tier = { tier: string; enabled: boolean; sends_data: boolean; selectable: boolean; blocked_reason: string };

type Model = {
  key: string;
  name: string;
  url: string;
  surfaces: string[];
  entity: string;
  entity_prefix: string;
  rule_id: string | null;
  threshold: number;
  fail_mode: string;
  has_secret: boolean;
  enabled: boolean;
};

const GROUPS = [
  { key: "attacks", label: "Prompt attacks" },
  { key: "data", label: "Personal data & secrets" },
  { key: "content", label: "Harmful content" },
  { key: "grounding", label: "Grounding & wrong answers" },
  { key: "yours", label: "Your own" },
];

const WHERE: Record<string, string> = { input: "Input", output: "Output", tools: "Tools", context: "Context" };

const TIERS: Record<string, { name: string; sub: string }> = {
  deterministic: { name: "Rules and code", sub: "Always on. No model, no network." },
  local_model: { name: "Local models", sub: "Classifier weights on this server." },
  local_llm: { name: "Local LLM", sub: "A model served on this machine." },
  jev: { name: "JEV", sub: "TypeSafe System One, hosted." },
  llm: { name: "LLM judge", sub: "A hosted LLM with your provider key." },
};

const name = (d: Detector) => (detectorName(d.key) !== d.key ? detectorName(d.key) : d.label || d.key);

function Source({ d }: { d: Detector }) {
  if (d.source === "builtin") return <Pill tone="outline">Built-in</Pill>;
  if (d.source === "llm_judge") return <Pill tone="info" title="Decided by a judge tier below">LLM judge</Pill>;
  if (d.source === "yours") return <Pill tone="outline">Yours</Pill>;
  const model = d.models[0]?.id;
  return (
    <Pill tone="outline" title={model ? `${model}${d.license ? ` (${d.license})` : ""}` : d.license || undefined}>
      Open source{d.license ? ` · ${d.license}` : ""}
    </Pill>
  );
}

function speed(d: Detector) {
  const ms = d.stats?.avg_ms;
  return ms ? `${ms < 1 ? "<1" : Math.round(ms)} ms` : "";
}

function Control({ d, canEdit, judgesOn }: { d: Detector; canEdit: boolean; judgesOn: boolean }) {
  if (d.always_on) return <Pill tone="outline">Always on</Pill>;
  if (d.available) {
    if (!canEdit) return d.enabled ? <Pill tone="ok">On</Pill> : <Pill tone="outline">Off</Pill>;
    return (
      <span className="k-pills" style={{ gap: 8 }}>
        {d.enabled ? <Pill tone="ok">On</Pill> : <Pill tone="outline">Off</Pill>}
        <Act url={`/api/detectors/${encodeURIComponent(d.key)}`} body={{ enabled: !d.enabled }} className={d.enabled ? "k-btn" : "k-btn-primary"}>
          {d.enabled ? "Turn off" : "Turn on"}
        </Act>
      </span>
    );
  }
  if (d.source === "llm_judge")
    return (
      <a href="#judges" className="k-muted">
        {judgesOn ? "Needs a judge that may decide this" : "Turn on a judge below"}
      </a>
    );
  if (d.models.length && canEdit) return <PullButton detectorKey={d.key} job={d.pull_job} blocked={d.pull_blocked} />;
  if (d.install) return <code className="k-mono">pip install {d.install}</code>;
  return <span className="k-muted" title={d.unavailable_reason || undefined}>{d.unavailable_reason?.split(". ")[0] || "Needs setup"}</span>;
}

function Rows({ rows, canEdit, judgesOn }: { rows: Detector[]; canEdit: boolean; judgesOn: boolean }) {
  return (
    <table className="k-table">
      <tbody>
        {rows.map((d) => (
          <tr key={d.key}>
            <td>
              <span className="k-name" title={d.unavailable_reason || undefined}>{name(d)}</span>
              <span className="sub">
                {d.where.map((w) => WHERE[w] || w).join(" · ")}
                {d.models[0] ? ` · ${d.models[0].id}` : ""}
              </span>
            </td>
            <td className="tight">
              <Source d={d} />
            </td>
            <td className="tight muted">{speed(d)}</td>
            <td className="tight" style={{ textAlign: "right" }}>
              <Control d={d} canEdit={canEdit} judgesOn={judgesOn} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * One place to choose what checks traffic: every detector by what it catches, the
 * AI judges, and your own patterns and models. Rules (Policies → Rules) decide what
 * happens when a check fires.
 */
export async function Checks() {
  const [data, detail, mine, me, access] = await Promise.all([
    safeApi<any>("/api/detectors", { detectors: [] }),
    safeApi<any>("/api/judgment/posture", null),
    safeApi<any>("/api/custom-models", { models: [], prefixes: [] }),
    safeApi<any>("/api/me", null),
    safeApi<any>("/api/authorizers", { authorizers: [] }),
  ]);
  const canEdit = ["owner", "admin", "security"].includes(me?.role ?? "");
  const all: Detector[] = (data.detectors || []).filter((d: Detector) => d.key !== "custom.models");
  const tiers: Tier[] = detail?.tiers || [];
  const judgesOn = tiers.some((t) => t.enabled && t.tier !== "deterministic");
  const posture: PostureDoc | null = detail
    ? { tiers: detail.posture.tiers, pii_egress: detail.posture.pii_egress, backend: detail.posture.backend, fail_closed: detail.posture.fail_closed }
    : null;
  const models: Model[] = mine.models || [];

  return (
    <>
      <p className="k-muted" style={{ marginTop: 0 }}>
        What checks your agents&apos; traffic. Rules decide what happens when a check finds something.
      </p>

      {GROUPS.map((g) => {
        const inGroup = all.filter((d) => (d.group || "content") === g.key);
        // Ready to use, or one click from it (judges); the rest are things to add.
        const shown = inGroup.filter((d) => d.available || d.source === "llm_judge" || (d.models.length > 0 && !d.key.startsWith("rails.") && d.key !== "safety.restricted"));
        const more = inGroup.filter((d) => !shown.includes(d));
        if (!inGroup.length && g.key !== "yours") return null;
        return (
          <Card
            key={g.key}
            title={g.label}
            flush
            action={g.key === "yours" ? <Link href="/app/policies/new?from=custom&kind=patterns">Add a pattern (regex)</Link> : undefined}
          >
            {shown.length > 0 && <Rows rows={shown} canEdit={canEdit} judgesOn={judgesOn} />}
            {more.length > 0 && (
              <details className="k-details" style={{ padding: "0 16px 8px" }}>
                <summary>More you can add ({more.length})</summary>
                <Rows rows={more} canEdit={canEdit} judgesOn={judgesOn} />
              </details>
            )}
            {g.key === "yours" && (
              <>
                <ul className="k-list">
                  {models.map((m) => (
                    <li key={m.key}>
                      <div className="k-list-main">
                        <span className="k-name">{m.name}</span>
                        <span className="muted k-mono">{m.url}</span>
                        <span className="muted">
                          Reports {m.entity} at {m.threshold} · {m.fail_mode === "closed" ? "a hit when down" : "skipped when down"}
                          {m.rule_id ? (
                            <>
                              {" · "}
                              <Link href={`/app/policies/rules/${encodeURIComponent(m.rule_id)}`}>Rule</Link>
                            </>
                          ) : null}
                        </span>
                      </div>
                      <div className="k-list-end">
                        <Pill tone="outline">Your model</Pill>
                        {m.enabled ? <Pill tone="ok">On</Pill> : <Pill tone="outline">Off</Pill>}
                        {canEdit && (
                          <>
                            <ModelTest modelKey={m.key} surface={m.surfaces[0] || "input"} />
                            <Act url={`/api/custom-models/${encodeURIComponent(m.key)}/enabled`} body={{ enabled: !m.enabled }} className="k-btn">
                              {m.enabled ? "Turn off" : "Turn on"}
                            </Act>
                            <Act url={`/api/custom-models/${encodeURIComponent(m.key)}`} method="DELETE" className="k-btn-ghost" confirm={`Remove ${m.name}? It stops checking traffic now.`}>
                              Remove
                            </Act>
                          </>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
                {canEdit ? (
                  <div style={{ padding: "8px 16px 14px" }}>
                    <ModelForm prefixes={mine.prefixes || []} />
                  </div>
                ) : (
                  !models.length && <Empty>No models of your own.</Empty>
                )}
              </>
            )}
          </Card>
        );
      })}

      <div id="access">
        <Card
          title="Your access checks"
          hint="Your own RBAC service decides what the person an agent acts for may do. Matching tool calls are sent to it, with that person, before they run."
          flush
        >
          <ul className="k-list">
            {(access.authorizers || []).map((a: any) => (
              <li key={a.key}>
                <div className="k-list-main">
                  <span className="k-name">{a.name}</span>
                  <span className="muted k-mono">{a.url}</span>
                  <span className="muted">
                    Decides {a.tools.join(", ")}
                    {a.agents.length ? ` for ${a.agents.join(", ")}` : ""} · a no {a.on_deny === "escalate" ? "asks a person" : "blocks"} ·{" "}
                    {a.fail_mode === "closed" ? "refuses calls when down" : "lets calls through when down"}
                    {a.last_error ? <span className="k-act-error"> · Last error: {a.last_error}</span> : null}
                  </span>
                </div>
                <div className="k-list-end">
                  {a.enabled ? <Pill tone="ok">On</Pill> : <Pill tone="outline">Off</Pill>}
                  {canEdit && (
                    <>
                      <AccessCheckTest checkKey={a.key} tool={a.tools[0] || ""} />
                      <Act url={`/api/authorizers/${encodeURIComponent(a.key)}/enabled`} body={{ enabled: !a.enabled }} className="k-btn">
                        {a.enabled ? "Turn off" : "Turn on"}
                      </Act>
                      <Act url={`/api/authorizers/${encodeURIComponent(a.key)}`} method="DELETE" className="k-btn-ghost" confirm={`Remove ${a.name}? Tool calls stop being checked against it now.`}>
                        Remove
                      </Act>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {canEdit ? (
            <div style={{ padding: "8px 16px 14px" }}>
              <AccessCheckForm />
            </div>
          ) : (
            !(access.authorizers || []).length && <Empty>No access checks yet.</Empty>
          )}
        </Card>
      </div>

      {detail && posture && (
        <div id="judges">
          <Card
            title="AI judges"
            hint="Models that answer what code cannot. A hosted judge sends checked text to its provider, so it needs egress on this deployment."
            action={<Link href="/app/policies?tab=advanced&sec=judges">All judge settings</Link>}
            flush
          >
            <table className="k-table">
              <tbody>
                {tiers.map((t) => (
                  <tr key={t.tier}>
                    <td>
                      <span className="k-name">{TIERS[t.tier]?.name || t.tier}</span>
                      <span className="sub">{TIERS[t.tier]?.sub || ""}</span>
                    </td>
                    <td className="tight">
                      {t.sends_data ? (
                        detail.ceiling?.allow_egress ? <Pill tone="held">Sends data</Pill> : <Pill tone="outline" title={t.blocked_reason}>Egress off here</Pill>
                      ) : (
                        <Pill tone="outline">Stays here</Pill>
                      )}
                    </td>
                    <td className="tight">{t.enabled ? <Pill tone="ok">On</Pill> : <Pill tone="outline">Off</Pill>}</td>
                    <td className="tight" style={{ textAlign: "right" }}>
                      {t.tier === "deterministic" ? null : t.selectable && canEdit ? (
                        <TierSwitch tier={t.tier} on={t.enabled} sendsData={t.sends_data} posture={posture} />
                      ) : !t.selectable ? (
                        <span className="k-muted" title={t.blocked_reason}>Not allowed here</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="k-muted" style={{ padding: "8px 16px 14px", margin: 0 }}>
              Personal data on the way out: {detail.posture.pii_egress}.
            </p>
          </Card>
        </div>
      )}
    </>
  );
}

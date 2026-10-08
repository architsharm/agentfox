import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import {
  ActionPill,
  Card,
  Empty,
  Grid,
  Header,
  Kpi,
  ModePill,
  Pill,
  Sparkline,
  Tabs,
  ago,
  href,
  num,
} from "@/components/kit";
import { Act } from "@/components/kit/Act";
import { FilterBar } from "@/components/kit/FilterBar";
import { Detectors } from "@/components/product/policies/Detectors";
import { ImportGuard } from "@/components/product/policies/ImportGuard";
import { LibraryPacks } from "@/components/product/policies/LibraryPacks";
import { PackMode } from "@/components/product/policies/PackMode";
import { LegacyJudgmentTab, LegacyPacksTab, LegacyTuningTab } from "@/components/product/policies/legacy";
import { metricsQs, runsHref } from "@/lib/product/observe";
import { loadRules, ruleMode, type RuleInfo } from "@/lib/product/rules";
import { CATEGORIES, categoryLabel, rangeOf, ruleCategory, ruleTitle } from "@/lib/product/vocab";

export const metadata: Metadata = appPageMetadata("Policies", "What your agents may do, and how well each rule is working.");
export const dynamic = "force-dynamic";

type SP = Record<string, string | undefined>;

const TABS = [
  { key: "rules", label: "Rules" },
  { key: "performance", label: "Performance" },
  { key: "library", label: "Library" },
  { key: "changes", label: "Changes" },
  { key: "advanced", label: "Advanced" },
];

/** Tab names from before the redesign, so old links still land. */
const LEGACY: Record<string, { tab: string; sec?: string }> = {
  guardrails: { tab: "advanced", sec: "tuning" },
  judgment: { tab: "advanced", sec: "judges" },
};

function firstSentence(text: string): string {
  const m = text.match(/^(.{25,}?[.!?])\s+(?=[A-Z])/);
  return (m ? m[1] : text).slice(0, 160);
}

export default async function Policies({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const legacy = LEGACY[sp.tab || ""];
  const tab = legacy?.tab || (TABS.some((t) => t.key === sp.tab) ? sp.tab! : "rules");
  const sec = legacy?.sec || sp.sec;

  return (
    <>
      <Header title="Policies" actions={<Link href="/app/policies/new" className="k-btn-primary">Add rule</Link>} />
      <Tabs items={TABS.map((t) => ({ ...t, href: href("/app/policies", { tab: t.key === "rules" ? undefined : t.key }) }))} active={tab} />
      {sp.review_error && <div className="error">{sp.review_error}</div>}
      {sp.review_notice && <div className="note-panel">Done: {sp.review_notice}.</div>}
      {tab === "rules" && <RulesTab sp={sp} />}
      {tab === "performance" && <PerformanceTab sp={sp} />}
      {tab === "library" && <LibraryTab sec={sec} />}
      {tab === "changes" && <ChangesTab />}
      {tab === "advanced" && <AdvancedTab sec={sec} agent={sp.agent} />}
    </>
  );
}

// --- Rules -------------------------------------------------------------------

async function RulesTab({ sp }: { sp: SP }) {
  const [{ packs, rules }, stats, business] = await Promise.all([
    loadRules(),
    safeApi<any>(`/api/metrics/rules?range=7d`, { rules: [] }),
    safeApi<any>("/api/business/rules", { rules: [] }),
  ]);
  const fired: Record<string, any> = Object.fromEntries((stats.rules || []).map((r: any) => [r.rule_id, r]));
  const cat = sp.cat || "";
  const mode = sp.mode || "";
  const visible = rules.filter((r) => {
    if (cat && ruleCategory(r.rule_id) !== cat) return false;
    const m = ruleMode(r);
    if (mode === "watching" && m !== "observe") return false;
    if (mode === "enforcing" && m !== "enforce") return false;
    if (mode === "off" && m !== null) return false;
    return true;
  });
  const chip = (key: string, value: string, label: string, current: string) => (
    <Link key={value || "all"} href={href("/app/policies", { cat: key === "cat" ? value : cat, mode: key === "mode" ? value : mode })} className={current === value ? "active" : ""} scroll={false}>
      {label}
    </Link>
  );
  const watchedByPack = (key: string) =>
    packs
      .find((p) => p.key === key)
      ?.rules.reduce((n: number, r: any) => n + (fired[r.id]?.watched || 0), 0) || 0;

  return (
    <>
      <Card title="Packs" flush>
        <table className="k-table">
          <tbody>
            {packs.map((p) => (
              <tr key={p.key}>
                <td>
                  <Link className="k-name" href={`/app/policies/${encodeURIComponent(p.key)}`}>{p.name}</Link>
                  <span className="sub">{p.rules.length} rules</span>
                </td>
                <td className="tight"><ModePill mode={p.mode} /></td>
                <td className="tight" style={{ textAlign: "right" }}>
                  <PackMode packKey={p.key} mode={p.mode} body={p.liveBody} version={p.boundVersion} wouldStop={p.mode === "enforce" ? undefined : watchedByPack(p.key)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="k-toolbar" style={{ marginTop: 18 }}>
        <div className="k-seg" role="group" aria-label="Area">
          {chip("cat", "", "All", cat)}
          {CATEGORIES.filter((c) => rules.some((r) => ruleCategory(r.rule_id) === c.key)).map((c) => chip("cat", c.key, c.label, cat))}
        </div>
        <div className="k-seg" role="group" aria-label="Mode">
          {chip("mode", "", "Any", mode)}
          {chip("mode", "enforcing", "Enforcing", mode)}
          {chip("mode", "watching", "Watching", mode)}
          {chip("mode", "off", "Off", mode)}
        </div>
      </div>

      {CATEGORIES.map((c) => {
        const group = visible.filter((r) => ruleCategory(r.rule_id) === c.key);
        if (!group.length) return null;
        return (
          <Card key={c.key} title={c.label} flush>
            <RuleRows rules={group} fired={fired} />
          </Card>
        );
      })}
      {!visible.length && <Card><Empty>No rules match.</Empty></Card>}

      <Card title="Business rules" action={<Link href="/app/policies/new?from=describe">Add</Link>} flush>
        {business.rules?.length ? (
          <table className="k-table">
            <tbody>
              {business.rules.map((b: any) => (
                <tr key={b.key}>
                  <td>
                    <span className="k-name">{b.name}</span>
                    <span className="sub">{b.tool || "Any tool"}{b.description ? ` · ${b.description}` : ""}</span>
                  </td>
                  <td className="tight"><ModePill mode={b.enabled ? b.mode : null} /></td>
                  <td className="tight" style={{ textAlign: "right" }}>
                    <Act url={`/api/business/rules/${encodeURIComponent(b.key)}/mode`} body={{ mode: b.mode === "enforce" ? "observe" : "enforce" }} className={b.mode === "enforce" ? "k-btn" : "k-btn-primary"}>
                      {b.mode === "enforce" ? "Switch to watching" : "Start enforcing"}
                    </Act>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty action={<Link href="/app/policies/new?from=describe" className="k-btn">Describe a rule</Link>}>No business rules yet.</Empty>
        )}
      </Card>
    </>
  );
}

function RuleRows({ rules, fired }: { rules: RuleInfo[]; fired: Record<string, any> }) {
  return (
    <table className="k-table">
      <tbody>
        {rules.map((r) => {
          const s = fired[r.rule_id];
          const m = ruleMode(r);
          return (
            <tr key={r.rule_id}>
              <td>
                <Link className="k-name" href={`/app/policies/rules/${encodeURIComponent(r.rule_id)}`} title={r.description}>
                  {ruleTitle(r.rule_id, r.description)}
                </Link>
              </td>
              <td className="tight"><ActionPill effect={r.effect} /></td>
              <td className="tight"><ModePill mode={m} /></td>
              <td className="tight">{s ? <Sparkline values={s.series} width={60} /> : null}</td>
              <td className="num tight" style={{ minWidth: 40 }}>
                {s ? <Link href={runsHref({ range: "7d" }, { rule: r.rule_id })}>{num(s.fires)}</Link> : <span className="k-muted">0</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// --- Performance -------------------------------------------------------------

async function PerformanceTab({ sp }: { sp: SP }) {
  const range = rangeOf(sp.range);
  const sort = sp.sort || "fired";
  const [{ rules }, stats, agents] = await Promise.all([
    loadRules(),
    safeApi<any>(`/api/metrics/rules?${metricsQs({ range })}`, { rules: [] }),
    safeApi<any>("/api/agents", { agents: [] }),
  ]);
  const byId: Record<string, any> = Object.fromEntries((stats.rules || []).map((r: any) => [r.rule_id, r]));
  const rows = rules.map((r) => ({ r, s: byId[r.rule_id] }));
  const firedRows = rows.filter((x) => x.s);
  const never = rows.filter((x) => !x.s && ruleMode(x.r));
  const watching = firedRows.filter((x) => x.s.watched > 0);
  const list =
    sort === "never" ? never : sort === "watching" ? watching.sort((a, b) => b.s.watched - a.s.watched) : firedRows.sort((a, b) => b.s.fires - a.s.fires);
  const totals = firedRows.reduce((t, x) => ({ fires: t.fires + x.s.fires, enforced: t.enforced + x.s.enforced, watched: t.watched + x.s.watched }), { fires: 0, enforced: 0, watched: 0 });

  // Coverage: for each agent, is each area enforced, only watched, or uncovered?
  const live = (agents.agents || []).filter((a: any) => a.status !== "draft");
  const effective = await Promise.all(live.map((a: any) => safeApi<any>(`/api/policies/effective?agent=${encodeURIComponent(a.slug)}`, { rules: [] })));
  const cats = CATEGORIES.filter((c) => rules.some((r) => ruleCategory(r.rule_id) === c.key));
  const cell = (rs: any[], cat: string) => {
    const inCat = rs.filter((r) => ruleCategory(r.rule_id) === cat);
    if (inCat.some((r) => r.enforcement === "enforce")) return <Pill tone="ok">Enforced</Pill>;
    if (inCat.length) return <Pill tone="outline">Watching</Pill>;
    return <span className="k-muted">—</span>;
  };
  const sortChip = (key: string, label: string, n: number) => (
    <Link href={href("/app/policies", { tab: "performance", sort: key === "fired" ? undefined : key, range: sp.range })} className={sort === key ? "active" : ""} scroll={false}>
      {label} <span className="k-muted">{n}</span>
    </Link>
  );

  return (
    <>
      <FilterBar>
        <div className="k-seg" role="group" aria-label="Show">
          {sortChip("fired", "Most fired", firedRows.length)}
          {sortChip("watching", "Would block", watching.length)}
          {sortChip("never", "Never fired", never.length)}
        </div>
      </FilterBar>
      <Grid cols={4}>
        <Kpi label="Rule hits" value={num(totals.fires)} />
        <Kpi label="Stopped something" value={num(totals.enforced)} />
        <Kpi label="Would have stopped" value={num(totals.watched)} hint="Hits by rules that are only watching." />
        <Kpi label="Rules never fired" value={num(never.length)} hint="Switched on, but nothing matched in this period." />
      </Grid>
      <Card flush>
        {list.length ? (
          <table className="k-table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Area</th>
                <th className="tight">Mode</th>
                <th className="num">Hits</th>
                <th className="num">Stopped</th>
                <th className="num">Would stop</th>
                <th>Trend</th>
                <th>Most hit</th>
                <th className="tight">Last</th>
              </tr>
            </thead>
            <tbody>
              {list.map(({ r, s }) => (
                <tr key={r.rule_id}>
                  <td><Link className="k-name" href={`/app/policies/rules/${encodeURIComponent(r.rule_id)}`}>{ruleTitle(r.rule_id, r.description)}</Link></td>
                  <td className="muted">{categoryLabel(ruleCategory(r.rule_id))}</td>
                  <td className="tight"><ModePill mode={ruleMode(r)} /></td>
                  <td className="num">{s ? <Link href={runsHref({ range }, { rule: r.rule_id })}>{num(s.fires)}</Link> : "0"}</td>
                  <td className="num">{s ? num(s.enforced) : "0"}</td>
                  <td className="num">{s ? num(s.watched) : "0"}</td>
                  <td>{s ? <Sparkline values={s.series} /> : null}</td>
                  <td className="muted">{s ? Object.keys(s.agents)[0] || "—" : "—"}</td>
                  <td className="tight muted">{s ? ago(s.last_fired) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>Nothing here for this period.</Empty>
        )}
      </Card>
      <Card title="Coverage by agent" hint="Enforced: at least one rule in the area blocks. Watching: rules only record." flush>
        <table className="k-table">
          <thead>
            <tr>
              <th>Agent</th>
              {cats.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {live.map((a: any, i: number) => (
              <tr key={a.slug}>
                <td><Link className="k-name" href={`/app/agents/${encodeURIComponent(a.slug)}?tab=rules`}>{a.name || a.slug}</Link></td>
                {cats.map((c) => (
                  <td key={c.key}>{cell(effective[i].rules || [], c.key)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// --- Library -----------------------------------------------------------------

const LIBRARY = [
  { key: "packs", label: "Packs" },
  { key: "detectors", label: "Detectors" },
  { key: "import", label: "Import" },
];

async function LibraryTab({ sec }: { sec?: string }) {
  const section = LIBRARY.some((s) => s.key === sec) ? sec! : "packs";
  return (
    <>
      <div className="chipbar">
        {LIBRARY.map((s) => (
          <Link key={s.key} href={href("/app/policies", { tab: "library", sec: s.key === "packs" ? undefined : s.key })} className={section === s.key ? "chip active" : "chip"}>
            {s.label}
          </Link>
        ))}
      </div>
      {section === "packs" && <LibraryPacks />}
      {section === "detectors" && <Detectors />}
      {section === "import" && (
        <Card title="From Guardrails AI">
          <ImportGuard />
        </Card>
      )}
    </>
  );
}

// --- Changes -----------------------------------------------------------------

async function ChangesTab() {
  const [proposals, recs, supps, { packs }] = await Promise.all([
    safeApi<any>("/api/proposals", { proposals: [] }),
    safeApi<any>("/api/guardrails/recommendations", { recommendations: [] }),
    safeApi<any>("/api/guardrails/suppressions", { suppressions: [] }),
    loadRules(),
  ]);
  const open = (proposals.proposals || []).filter((p: any) => !["rejected", "rolled_back", "superseded", "verified"].includes(p.status));
  const versions = packs
    .flatMap((p) => p.versions.map((v: any) => ({ ...v, pack: p.name, key: p.key, live: v.version === p.boundVersion })))
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
    .slice(0, 12);
  const useful = (recs.recommendations || []).filter((r: any) => r.action !== "insufficient_data");

  return (
    <>
      <Card title="Suggested changes" flush>
        {open.length ? (
          <ul className="k-list">
            {open.map((p: any) => (
              <li key={p.id}>
                <div className="k-list-main">
                  <span className="k-name">{p.title}</span>
                  <span className="muted">{firstSentence(p.rationale || "")}</span>
                </div>
                <div className="k-list-end">
                  <Pill tone={p.direction === "loosens" ? "held" : "neutral"}>{p.direction === "loosens" ? "Loosens" : p.direction === "tightens" ? "Tightens" : "Neutral"}</Pill>
                  {["proposed", "proven"].includes(p.status) && (
                    <>
                      <Act url={`/api/proposals/${p.id}/decide`} body={{ approve: false, note: "rejected in the dashboard" }} className="k-btn-ghost">Reject</Act>
                      <Act url={`/api/proposals/${p.id}/decide`} body={{ approve: true, note: "approved in the dashboard" }} className="k-btn-primary">Approve</Act>
                    </>
                  )}
                  {p.status === "approved" && <Act url={`/api/proposals/${p.id}/apply`} className="k-btn-primary">Apply</Act>}
                  {["applied", "canary"].includes(p.status) && (
                    <Act url={`/api/proposals/${p.id}/rollback`} body={{ reason: "rolled back in the dashboard" }} className="k-btn" confirm="Roll this change back?">Roll back</Act>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No suggestions. Mark detections as wrong on a run to get some.</Empty>
        )}
      </Card>

      {useful.length > 0 && (
        <Card title="Sensitivity" flush>
          <ul className="k-list">
            {useful.map((r: any) => (
              <li key={r.detector_key}>
                <div className="k-list-main">
                  <span className="k-name">{r.detector_key}</span>
                  <span className="muted">{firstSentence(r.rationale)}</span>
                </div>
                {r.suggested_threshold != null && <Pill tone="info">Threshold {r.suggested_threshold}</Pill>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Exceptions" hint="Accepted false positives. Each one expires." flush>
        {supps.suppressions?.length ? (
          <ul className="k-list">
            {supps.suppressions.map((s: any) => (
              <li key={s.id}>
                <div className="k-list-main">
                  <span className="k-name">{s.detector_key || s.detector}{s.entity_type ? ` · ${s.entity_type}` : ""}</span>
                  <span className="muted">{s.scope === "global" ? "All agents" : s.agent || "One agent"} · expires {String(s.expires_at || "").slice(0, 10)}</span>
                </div>
                <form action="/api/guardrails/suppressions/revoke" method="POST">
                  <input type="hidden" name="id" value={s.id} />
                  <button type="submit" className="k-btn-ghost">Remove</button>
                </form>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No exceptions.</Empty>
        )}
      </Card>

      <Card title="History" flush>
        <table className="k-table">
          <tbody>
            {versions.map((v) => (
              <tr key={v.id}>
                <td>
                  <Link className="k-name" href={`/app/policies/${encodeURIComponent(v.key)}`}>{v.pack}</Link>
                  <span className="sub">{v.notes || `Version ${v.version}`}</span>
                </td>
                <td className="tight">{v.live ? <Pill tone="ok">Live</Pill> : <Pill tone="outline">v{v.version}</Pill>}</td>
                <td className="tight muted">{v.author}</td>
                <td className="tight muted">{ago(v.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// --- Advanced ----------------------------------------------------------------

function AdvancedTab({ sec, agent }: { sec?: string; agent?: string }) {
  const section = sec === "tuning" || sec === "judges" ? sec : "packs";
  const chip = (key: string, label: string) => (
    <Link href={href("/app/policies", { tab: "advanced", sec: key === "packs" ? undefined : key })} className={section === key ? "chip active" : "chip"}>
      {label}
    </Link>
  );
  return (
    <>
      <div className="chipbar">
        {chip("packs", "Packs & detectors")}
        {chip("tuning", "Detector tuning")}
        {chip("judges", "AI judges & egress")}
      </div>
      {section === "packs" && <LegacyPacksTab agent={agent} />}
      {section === "tuning" && <LegacyTuningTab agent={agent} />}
      {section === "judges" && <LegacyJudgmentTab />}
    </>
  );
}

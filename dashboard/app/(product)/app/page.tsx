import type { Metadata } from "next";
import Link from "next/link";
import { api, apiErrorProps, safeApi } from "@/lib/product/api";
import { appPageMetadata } from "@/lib/site";
import { ApiDown, InfoTip, InventoryStrip, Severity, Stat, findingTypeInfo, ts } from "@/components/ui";
import { PageHeader } from "@/components/product/PageHeader";
import { Coverage } from "@/components/product/Coverage";

export const dynamic = "force-dynamic";

/**
 * The dashboard, at `/app`.
 *
 * It used to be the signed-in branch of `/`, which had two consequences worth
 * writing down. A signed-in visitor could not reach the marketing site at all
 * without signing out — there was no URL that served it to them. And `/` was the
 * one route in the app whose chrome depended on a cookie, which is why both
 * `middleware.ts` and `layout.tsx` carried a special case for it.
 *
 * Every private route now lives under `/app`, so "is this page private" is a
 * prefix test rather than a list that has to be kept in step in three files.
 */
// `appPageMetadata`, not a literal: it also sets `alternates: { canonical: null }`,
// without which this page inherits the root layout's `canonical: "/"` and declares
// itself a duplicate of the marketing home page.
export const metadata: Metadata = appPageMetadata("Overview");

/**
 * Nobody opens a governance dashboard to ask "what do we have" — they open it to ask
 * "is anything wrong right now". A screen that leads with an inventory makes the
 * reader do the ranking themselves, so this one leads with what needs a human and
 * puts the inventory underneath.
 */
/**
 * The same detector firing on the same surface of repeated requests produces
 * several findings that are word-for-word identical. They are correct as
 * records and wrong as a queue: the reader triages one fact three times, and
 * the repeats crowd different problems off the visible top of the list.
 *
 * The key is deliberately the full title and not just subject + type +
 * severity. Grouping more loosely than that merges genuinely different
 * problems — an injection block and a PII block on the same agent are both
 * `guardrail_detection / high`, and collapsing them leaves one title standing
 * for an incident it does not describe. Under-collapsing costs a duplicate
 * row; over-collapsing hides an incident behind another incident's name, so
 * only exact repeats are folded, and the count travels with the row rather
 * than the records being silently dropped.
 */
function dedupe(items: any[]): (any & { dupes: number })[] {
  const out: any[] = [];
  const seen = new Map<string, any>();
  for (const item of items) {
    const key = `${item.subject}|${item.type}|${item.severity}|${item.title}`;
    const hit = seen.get(key);
    if (hit) {
      hit.dupes += 1;
      continue;
    }
    const row = { ...item, dupes: 1 };
    seen.set(key, row);
    out.push(row);
  }
  return out;
}

async function Overview() {
  let attention: any, onboarding: any, agents: any, posture: any;
  // The coverage strip is additive context, never the reason this page fails —
  // a detector registry that 404s should cost the reader that one tile, not the
  // list of things that need a person today.
  let policies: any, detectors: any, probes: any;
  try {
    [attention, onboarding, agents, posture, policies, detectors, probes] = await Promise.all([
      api("/api/attention"),
      api("/api/onboarding"),
      api("/api/agents"),
      api("/api/compliance/status"),
      safeApi("/api/policies", { policies: [] }),
      safeApi("/api/detectors", { detectors: [] }),
      safeApi("/api/redteam/probes", { probes: [] }),
    ]);
  } catch (e: any) {
    return (
      <>
        <PageHeader title="Overview" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  // Not connected and quiet are the same picture and opposite meanings. Saying which
  // one this is, is the single most useful thing this page does on day one.
  if (!onboarding.connected) {
    return (
      <>
        <PageHeader title="Overview" />
        <div className="hero empty">
          <div className="hero-title">Nothing is sending traffic yet</div>
          <p>Which is not the same as nothing being wrong. One line, and this fills in:</p>
          <code className="hero-code">import agentfox; agentfox.auto()</code>
          <p className="small muted">
            Every model call in the process, traced and recorded. Blocks nothing until
            you promote a policy.
          </p>
          <Link href="/app/start" className="cta">
            Start here →
          </Link>
        </div>

        {/* The worst version of this screen is the one a new reader used to get:
            a single card saying nothing is here, on a deployment that already
            has policy packs, rules and controls loaded and waiting. "No traffic
            yet" is a fact about their integration, not about whether the
            product does anything. */}
        <Coverage
          policies={policies.policies || []}
          detectors={detectors.detectors || []}
          probes={probes.probes || []}
          controls={posture}
        />
      </>
    );
  }

  const counts = attention.counts || {};
  const inv = agents.inventory;
  const rows = dedupe(attention.items || []);

  return (
    <>
      <PageHeader title="Overview" sub="What needs a person, most severe first." />

      {attention.quiet ? (
        <div className="hero ok">
          <div className="hero-title">Nothing needs attention</div>
          <p className="small muted">
            {onboarding.counts.traces} trace(s) governed,{" "}
            {onboarding.counts.enforcing > 0
              ? `${onboarding.counts.enforcing} decision(s) enforced`
              : "all decisions in observe mode — recorded, nothing blocked"}
            .
          </p>
        </div>
      ) : (
        <>
          <div className="cards">
            <Stat
              n={counts.critical || 0}
              label="critical problems"
              tone={counts.critical ? "bad" : "ok"}
              hint="Issues serious enough that someone should look today — a customer-facing failure, a data exposure, something a regulator would ask about."
            />
            <Stat
              n={counts.high || 0}
              label="high-priority problems"
              tone={counts.high ? "warn" : "ok"}
              hint="Worth fixing this week — not an emergency, but not fine to ignore either."
            />
            {/* The only number on this page that is good news when it is high.
                Left tone-less it read as one more grey count in a row of
                problems, which buries the single thing the product is for. */}
            <Stat
              n={counts.blocked_in_window || 0}
              label={`stopped automatically, last ${attention.window_hours}h`}
              tone={counts.blocked_in_window ? "ok" : undefined}
              hint="Requests a guardrail actually refused before they reached the customer — this is the system working, not a problem to fix."
            />
            <Stat
              n={counts.observed_in_window || 0}
              label={`flagged but allowed, last ${attention.window_hours}h`}
              hint="Requests a guardrail noticed and logged but didn't stop — the policy for this kind of issue is still in 'watch, don't block' mode."
            />
          </div>

          {/* This qualifies the four tiles, so it sits under the four tiles. It
              used to be the last element on the page, ~700px below the numbers
              it was talking about and wrapping 330px short of everything around
              it — a footnote with no referent in sight. */}
          <p className="stat-note">
            These four count what the detectors found in <em>text</em>. They miss the
            other half of the job: before any tool runs, the call itself is checked
            against what that agent was granted.
            <InfoTip text="Which tool, what the arguments say, where those argument values came from, and how much damage the tool can do — so an irreversible call assembled out of untrusted content is refused or sent for approval even when nothing flagged the prompt. It depends entirely on tools being declared honestly: a tool recorded as read-only that is not read-only is not covered by any of this." />{" "}
            <Link href="/app/policies">See it on Policies &rarr;</Link>
          </p>

          <h2>Needs attention</h2>
          <div className="panel">
            <table>
              <thead>
                <tr>
                  <th className="w-chip" />
                  <th className="w-prose">what</th>
                  <th className="w-name">subject</th>
                  <th className="w-when">when</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 6).map((item: any, i: number) => {
                  const typeInfo = findingTypeInfo(item.type);
                  return (
                    <tr key={i}>
                      <td>
                        <Severity value={item.severity} />
                      </td>
                      <td>
                        <Link href={item.href}>{item.title}</Link>
                        {item.dupes > 1 && (
                          <span
                            className="tag"
                            style={{ marginLeft: 8 }}
                            title={`${item.dupes} separate findings share this subject, kind and severity. Every one is kept — see all findings for the individual records.`}
                          >
                            ×{item.dupes}
                          </span>
                        )}
                        <div className="small muted">{typeInfo.blurb || typeInfo.label}</div>
                      </td>
                      <td className="mono small">{item.subject}</td>
                      <td className="small muted">{ts(item.at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {attention.total > 6 && (
              <div className="body small muted">
                {attention.total - 6} more — <Link href="/app/findings">see all findings</Link>
              </div>
            )}
            {/* Say when collapsing has hidden rows, rather than letting the
                reader wonder why six rows and eleven findings disagree. */}
            {rows.length < attention.items.length && (
              <div className="body small muted">
                {attention.items.length - rows.length} duplicate record(s) collapsed —
                rows marked × cover more than one finding.
              </div>
            )}
          </div>
        </>
      )}

      <Coverage
        policies={policies.policies || []}
        detectors={detectors.detectors || []}
        probes={probes.probes || []}
        controls={posture}
      />

      <h2>Inventory</h2>
      <InventoryStrip
        items={[
          { n: inv.agents, label: "agents under management", href: "/app/agents" },
          {
            n: inv.shadow,
            label: "unregistered",
            href: "/app/agents",
            ...(inv.shadow ? { tone: "bad" as const } : {}),
          },
          {
            n: inv.unowned,
            label: "without an owner",
            href: "/app/agents",
            ...(inv.unowned ? { tone: "warn" as const } : {}),
          },
          {
            n: onboarding.counts.boundaries,
            label: "knowledge boundaries",
            href: "/app/start",
            ...(onboarding.counts.boundaries ? {} : { tone: "warn" as const }),
          },
          {
            n: `${Math.round((posture.effectiveness || 0) * 100)}%`,
            label: "control effectiveness",
            href: "/app/compliance",
          },
        ]}
      />

      {onboarding.next && (
        <div className="note-panel">
          <strong>Next: {onboarding.next.title}.</strong>{" "}
          <InfoTip text={onboarding.next.detail} />{" "}
          <Link href="/app/start">Start here &rarr;</Link>
        </div>
      )}

    </>
  );
}

export default async function DashboardPage() {
  return <Overview />;
}

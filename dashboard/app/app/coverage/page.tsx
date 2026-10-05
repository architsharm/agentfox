import type { Metadata } from "next";
import Link from "next/link";
import { appPageMetadata } from "@/lib/site";
import { api, apiErrorProps } from "@/lib/api";
import { ApiDown, InfoTip } from "@/components/ui";
import { PageHeader } from "@/components/PageHeader";

export const metadata: Metadata = appPageMetadata(
  "Threat coverage",
  "Every published threat, and what this deployment actually does about it.",
);

export const dynamic = "force-dynamic";

/**
 * The page a security engineer would have gone looking for first, and the one axis
 * this product did not offer.
 *
 * It already sliced its data five ways — by agent, by finding, by policy, by
 * control, by trace. Somebody asking "how good is our AI security" slices it a
 * sixth way: down a published threat list, one entry at a time. Every ingredient
 * was tagged for it (detectors stamp `owasp_id`, red-team probes carry the same,
 * controls map to OWASP and ATLAS, rules name their controls) and nothing performed
 * the join. OWASP sat as the sixth tab of the compliance page, next to SOC 2 — a
 * threat model filed as an attestation framework.
 *
 * The number is deliberately unflattering. `enforcing` over `scored`, where
 * `observing` counts as not covered: a deployment that blocks nothing must not be
 * able to report full coverage, and a threat with no control mapped to it has to
 * appear as a gap rather than silently not appear at all. That is why the catalogue
 * is a declared list rather than derived from the mappings — LLM07 had nothing
 * mapped to it and therefore did not exist until it was written down.
 */

const STATUS: Record<string, { label: string; tone: string; rank: number }> = {
  breached: { label: "breached", tone: "bad", rank: 0 },
  uncovered: { label: "uncovered", tone: "bad", rank: 1 },
  observing: { label: "watching only", tone: "warn", rank: 2 },
  enforcing: { label: "enforcing", tone: "ok", rank: 3 },
  out_of_scope: { label: "out of scope", tone: "muted", rank: 4 },
};

export default async function Coverage({
  searchParams,
}: {
  searchParams: Promise<{ window?: string }>;
}) {
  const { window } = await searchParams;
  const days = Number(window) > 0 ? Number(window) : 30;

  let data: any;
  try {
    data = await api(`/api/coverage/threats?window_days=${days}`);
  } catch (e) {
    return (
      <>
        <PageHeader title="Threat coverage" />
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const pct = data.scored ? Math.round((data.enforcing / data.scored) * 100) : 0;
  const counts = data.counts || {};

  return (
    <>
      <PageHeader
        title="Threat coverage"
        sub={
          <>
            Every threat in the published lists, and what this deployment actually does
            about it. Detections counted over the last {data.window_days} days.
          </>
        }
      />

      <div className="cards">
        <Stat n={`${pct}%`} label={`of ${data.scored} in-scope threats enforced`} tone={pct >= 80 ? "ok" : pct >= 50 ? "warn" : "bad"} />
        <Stat n={counts.uncovered || 0} label="nothing watching" tone={counts.uncovered ? "bad" : "ok"} />
        <Stat n={counts.observing || 0} label="watching, not stopping" tone={counts.observing ? "warn" : "ok"} />
        <Stat n={counts.breached || 0} label="red team got through" tone={counts.breached ? "bad" : "ok"} />
      </div>

      <p className="stat-note">
        A threat counts as covered only when a rule is <span className="mono">enforcing</span>{" "}
        it.{" "}
        <InfoTip text="Observe mode records what would have happened and stops nothing. Counting it as covered would let a deployment that blocks nothing report full coverage, which is the most expensive wrong number this product could publish." />{" "}
        Out-of-scope threats are excluded from the ratio rather than counted as failures —
        training-data poisoning is not something a runtime control plane is in the path of.
      </p>

      {(data.gaps || []).length > 0 && (
        <>
          <h2>Worth looking at first</h2>
          <div className="panel">
            <table>
              <thead>
                <tr>
                  <th className="w-chip" />
                  <th>threat</th>
                  <th className="w-prose">why</th>
                </tr>
              </thead>
              <tbody>
                {data.gaps.map((t: any) => (
                  <tr key={`${t.catalogue}:${t.id}`}>
                    <td>
                      <span className={`tag ${STATUS[t.status]?.tone}`}>
                        {STATUS[t.status]?.label ?? t.status}
                      </span>
                    </td>
                    <td>
                      <span className="mono">{t.id}</span> {t.title}
                    </td>
                    <td className="small muted wrap">{t.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {Object.entries(data.catalogues || {}).map(([key, cat]: [string, any]) => {
        const rows = (data.threats || [])
          .filter((t: any) => t.catalogue === key)
          .sort(
            (a: any, b: any) =>
              (STATUS[a.status]?.rank ?? 9) - (STATUS[b.status]?.rank ?? 9) ||
              a.id.localeCompare(b.id, undefined, { numeric: true }),
          );
        return (
          <section key={key}>
            <h2>
              {cat.title}{" "}
              {cat.url && (
                <a className="small" href={cat.url} target="_blank" rel="noreferrer">
                  the list ↗
                </a>
              )}
            </h2>
            <div className="panel scroll-x">
              <table>
                <thead>
                  <tr>
                    <th className="w-chip" />
                    <th>threat</th>
                    <th className="w-prose">what we do about it</th>
                    <th className="num">caught</th>
                    <th className="num">red team</th>
                    <th>controls</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t: any) => (
                    <tr key={t.id}>
                      <td>
                        <span className={`tag ${STATUS[t.status]?.tone}`}>
                          {STATUS[t.status]?.label ?? t.status}
                        </span>
                      </td>
                      <td>
                        <div>
                          <span className="mono">{t.id}</span> {t.title}
                        </div>
                        {t.detectors.length > 0 && (
                          <div className="small muted">
                            {t.detectors
                              .filter((d: any) => d.available)
                              .map((d: any) => d.key)
                              .join(", ") || "no detector installed"}
                          </div>
                        )}
                      </td>
                      <td className="small muted wrap">{t.detail}</td>
                      {/* A count, not a link: Findings filters by agent, severity
                          and status, not by threat id, and a link that silently
                          does not filter is worse than no link. */}
                      <td
                        className="num small"
                        title="Detections stamped with this threat id in the window"
                      >
                        {t.detections > 0 ? t.detections : <span className="muted">—</span>}
                      </td>
                      <td className="num small">
                        {t.redteam_attempts === 0 ? (
                          <span className="muted">not tried</span>
                        ) : (
                          <span className={t.redteam_breaches ? "bad" : "ok"}>
                            {t.redteam_breaches}/{t.redteam_attempts}
                          </span>
                        )}
                      </td>
                      <td className="small">
                        {t.controls.length === 0 ? (
                          <span className="muted">none</span>
                        ) : (
                          t.controls.map((c: any) => (
                            <div key={c.key}>
                              <span className="mono">{c.key}</span>{" "}
                              <span className="muted">{c.status.replace(/_/g, " ")}</span>
                            </div>
                          ))
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      <p className="small muted">
        Threat lists are versioned content, not code — see{" "}
        <span className="mono">compliance_data/threats.yaml</span>. The same controls are
        mapped to SOC 2, ISO 42001, the EU AI Act and NIST AI RMF on{" "}
        <Link href="/app/compliance">Compliance</Link>, which answers the attestation
        question rather than this one.
      </p>
    </>
  );
}

function Stat({ n, label, tone }: { n: number | string; label: string; tone?: string }) {
  return (
    <div className={`card ${tone || ""}`}>
      <div className="n">{n}</div>
      <div className="label">{label}</div>
    </div>
  );
}

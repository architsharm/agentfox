import Link from "next/link";
import { InventoryStrip } from "@/components/ui";

/** Every finding type that doesn't have a bespoke evidence view (most of them —
 * unowned agent, missed hand-off, budget exceeded, model drift, disclosure risk,
 * and a dozen more) used to fall back to a raw JSON dump. This renders the same
 * data as labeled fields instead, so a non-technical reader gets sentences and a
 * list, not a blob of braces and snake_case keys to decode themselves. */
export function humanizeKey(key: string): string {
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function EvidenceValue({ value }: { value: any }) {
  if (value === null || value === undefined || value === "") {
    return <span className="muted">—</span>;
  }
  if (typeof value === "boolean") return <>{value ? "yes" : "no"}</>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted">none</span>;
    return (
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {value.map((v, i) => (
          <li key={i} className="small">
            {/* Never JSON.stringify. This branch is what rendered a red-team
                finding's 22 probe objects as 22 lines of raw JSON: an array of
                objects is still a list of labelled fields, so it recurses like
                any other object rather than giving up and printing braces. */}
            {typeof v === "object" && v !== null ? <EvidenceValue value={v} /> : String(v)}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    return (
      <div className="stack" style={{ gap: 2 }}>
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="small">
            <span className="muted">{humanizeKey(k)}: </span>
            <EvidenceValue value={v} />
          </div>
        ))}
      </div>
    );
  }
  return <>{String(value)}</>;
}

export function GenericEvidence({ evidence }: { evidence: any }) {
  const entries = Object.entries(evidence || {});
  if (entries.length === 0) {
    return <p className="small muted">No further detail was recorded with this finding.</p>;
  }
  return (
    <div className="panel">
      <table>
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key}>
              <td className="small muted" style={{ whiteSpace: "nowrap", verticalAlign: "top" }}>
                {humanizeKey(key)}
              </td>
              <td className="small wrap" style={{ maxWidth: 460 }}><EvidenceValue value={value} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function GuardrailDetectionEvidence({ evidence }: { evidence: any }) {
  const detections = evidence.detections || [];
  return (
    <div className="stack">
      <p className="small muted" style={{ marginTop: -4 }}>
        Each excerpt below is masked at the moment the detector runs — enough to show
        what triggered this, never the underlying value. That's already true of every
        detector in this product; this is that same masked sample, just shown here
        instead of only on the trace it happened on.
      </p>
      <div className="row small" style={{ gap: 16 }}>
        <span><span className="muted">surface </span><span className="mono">{evidence.surface || "—"}</span></span>
        <span><span className="muted">verdict </span><span className={`tag ${evidence.verdict === "block" ? "bad" : "warn"}`}>{evidence.verdict}</span></span>
        {evidence.trace_id && (
          <span>
            <Link href={`/app/traces/${evidence.trace_id}`}>See full detector activity on this trace →</Link>
          </span>
        )}
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr><th>entity</th><th className="num">score</th><th>masked excerpt</th><th>reference</th></tr>
          </thead>
          <tbody>
            {detections.map((d: any, i: number) => (
              <tr key={i}>
                <td className="mono small">{d.entity_type}</td>
                <td className="num small">{d.score?.toFixed?.(2) ?? d.score}</td>
                <td className="mono small wrap" style={{ maxWidth: 360 }}>{d.sample || <span className="muted">—</span>}</td>
                <td className="small muted">
                  {d.owasp_id && <span className="tag" style={{ marginRight: 4 }}>{d.owasp_id}</span>}
                  {d.atlas_id && <span className="tag">{d.atlas_id}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {evidence.reason && <p className="small muted">{evidence.reason}</p>}
    </div>
  );
}

/**
 * A red-team campaign's result, for the two findings it can raise.
 *
 * Both carry the SAME evidence blob — the whole campaign summary — and differ
 * only in which subset of probes the finding is about:
 *
 *   redteam             attacks that were not blocked   (`probe_keys`)
 *   redteam_over_block  benign probes that WERE blocked (`probe_keys`)
 *
 * The over-block variant used to reach this file not at all: FindingEvidence
 * routed only "redteam", so it fell through to GenericEvidence, whose array
 * branch calls JSON.stringify on each element. The page rendered twenty-two raw
 * JSON objects, one per probe, and the single line naming the probe that was
 * actually wrong sat underneath all of them.
 *
 * It also has to lead with the right number. On an over-block finding the
 * campaign summary reads 18 blocked, 0 got through, posture 100% — all true, all
 * about the attacks, and none of it about the thing the finding is reporting.
 * Four green tiles above the words "wrongly blocked 1 of 4 legitimate probes" is
 * a page arguing with itself, so the headline is the finding's own subset and
 * the campaign totals are context underneath it.
 */
export function RedteamEvidence({
  evidence,
  variant = "breach",
}: {
  evidence: any;
  variant?: "breach" | "over_block";
}) {
  const byCategory = evidence.by_category || {};
  const probes: any[] = evidence.probes || [];
  const keys: string[] = evidence.probe_keys || evidence.critical_breaches || [];
  const subject = probes.filter((p) => keys.includes(p.key));
  const overBlock = variant === "over_block";

  return (
    <div className="stack">
      {/* What this finding is about, before anything else. */}
      {keys.length > 0 && (
        <div className={`rt-focus ${overBlock ? "rt-warn" : "rt-bad"}`}>
          <h3>
            {overBlock
              ? `${keys.length} legitimate request${keys.length === 1 ? "" : "s"} ${keys.length === 1 ? "was" : "were"} blocked`
              : `${keys.length} attack${keys.length === 1 ? "" : "s"} ${keys.length === 1 ? "was" : "were"} not blocked`}
          </h3>
          <p>
            {overBlock
              ? "These probes are the control group: ordinary requests the agent is supposed to answer. Blocking one is a false positive, and a guardrail that refuses real work gets turned off."
              : "These probes reached the agent without being stopped. Each one is a real attack shape, and the payload below is the literal text that got through."}
          </p>
          {subject.length > 0 ? (
            <ul className="rt-cases">
              {subject.map((p) => (
                <li key={p.key}>
                  <div className="rt-case-head">
                    <span className="mono">{p.key}</span>
                    <span className="rt-case-cat">{p.category}</span>
                    <span className={`tag ${overBlock ? "warn" : "bad"}`}>{p.verdict}</span>
                  </div>
                  {p.payload ? (
                    <pre className="rt-payload">{p.payload}</pre>
                  ) : (
                    <p className="rt-nopayload">
                      A tool call, not a prompt — there is no text to show.{" "}
                      {p.description}
                    </p>
                  )}
                  {p.payload && p.description && <p className="rt-why">{p.description}</p>}
                </li>
              ))}
            </ul>
          ) : (
            /* An older campaign recorded the names but not the payloads. */
            <ul className="rt-cases">
              {keys.map((k) => (
                <li key={k}>
                  <div className="rt-case-head"><span className="mono">{k}</span></div>
                  <p className="rt-nopayload">
                    This campaign ran before prompts were recorded per finding — only
                    the probe name survived. Re-run the campaign to see the text tried.
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* The campaign this came out of: context, not headline. */}
      <div>
        <h3 className="rt-h">The campaign this came from</h3>
        <InventoryStrip
          items={[
            { n: evidence.probes_run ?? "—", label: "probes run", href: "/app/evals" },
            { n: evidence.attacks_blocked ?? "—", label: "attacks blocked", href: "/app/evals" },
            {
              n: evidence.attacks_succeeded ?? "—",
              label: "attacks got through",
              href: "/app/evals",
              ...(evidence.attacks_succeeded ? { tone: "bad" as const } : {}),
            },
            {
              n: evidence.benign_false_positives ?? "—",
              label: "legitimate requests blocked",
              href: "/app/evals",
              ...(evidence.benign_false_positives ? { tone: "warn" as const } : {}),
            },
          ]}
        />
      </div>

      {/* Everything else is reference. Closed by default: it is twenty-plus rows
          of probe detail, and someone opening a finding wants the finding. */}
      {Object.keys(byCategory).length > 0 && (
        <details className="rt-more">
          <summary>Results by category ({Object.keys(byCategory).length})</summary>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr><th>category</th><th className="num">run</th><th className="num">blocked</th><th className="num">succeeded</th><th className="num">over-blocked</th></tr>
              </thead>
              <tbody>
                {Object.entries(byCategory).map(([cat, v]: [string, any]) => (
                  <tr key={cat}>
                    <td className="small">{humanizeKey(cat)}</td>
                    <td className="num small">{v.run}</td>
                    <td className="num small">{v.blocked}</td>
                    <td className={`num small${v.succeeded ? " bad" : ""}`}>{v.succeeded}</td>
                    <td className={`num small${v.over_blocked ? " warn" : ""}`}>{v.over_blocked ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {probes.length > 0 && (
        <details className="rt-more">
          <summary>Every prompt tried ({probes.length})</summary>
          <p className="small muted" style={{ margin: "0 0 10px" }}>
            The literal text sent through this agent&rsquo;s enforcement path for each
            probe — read it yourself rather than trusting the score above.
          </p>
          <div className="panel scroll-x">
            <table>
              <thead>
                <tr><th>probe</th><th>prompt tried</th><th>verdict</th><th>result</th></tr>
              </thead>
              <tbody>
                {probes.map((p: any) => (
                  <tr key={p.key} className={keys.includes(p.key) ? "rt-row-subject" : undefined}>
                    <td className="small">
                      <span className="mono">{p.key}</span>
                      <div className="muted">{humanizeKey(p.category || "")}</div>
                    </td>
                    <td className="small mono wrap" style={{ maxWidth: 420 }}>
                      {p.payload || <span className="muted">tool call — no prompt text</span>}
                    </td>
                    <td className="small">
                      <span className={`tag ${p.verdict === "allow" ? "" : "warn"}`}>{p.verdict}</span>
                    </td>
                    <td className="small">
                      {p.over_blocked ? (
                        <span className="tag warn">wrongly blocked</span>
                      ) : (
                        <span className={`tag ${p.succeeded ? "bad" : "ok"}`}>
                          {p.succeeded ? "got through" : "blocked"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {evidence.campaign_id && (
        <p className="page-foot">
          Campaign <span className="mono">{evidence.campaign_id}</span> ·{" "}
          <Link href="/app/evals">Run another →</Link>
        </p>
      )}
    </div>
  );
}

export function FindingEvidence({ finding }: { finding: any }) {
  if (finding.type === "redteam") return <RedteamEvidence evidence={finding.evidence} />;
  // Was missing, so this fell through to GenericEvidence and rendered the
  // campaign's 22 probe objects as 22 JSON strings.
  if (finding.type === "redteam_over_block")
    return <RedteamEvidence evidence={finding.evidence} variant="over_block" />;
  if (finding.type === "guardrail_detection") return <GuardrailDetectionEvidence evidence={finding.evidence} />;
  return <GenericEvidence evidence={finding.evidence} />;
}

import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import Link from "next/link";
import { api, apiErrorProps } from "@/lib/product/api";
import { ApiDown, InfoTip, Panel, StatusBar } from "@/components/ui";
import { PageHeader } from "@/components/product/PageHeader";
import { ContextCheck } from "@/components/product/ContextCheck";
import { Modal } from "@/components/product/Modal";
import { SourceAddFlow } from "@/components/product/SourceAddFlow";
import { SourceRowActions } from "@/components/product/SourceRowActions";
import { TIER_TONE } from "@/lib/product/sourceOptions";

/**
 * Behind the sign-in wall: `noindex`, plus a tab title that is not the fourth
 * copy of "AgentFox Control Plane". See lib/site.ts appPageMetadata.
 */
export const metadata: Metadata = appPageMetadata("Verified sources");

export const dynamic = "force-dynamic";

const VALIDATION_TONE: Record<string, string> = {
  valid: "ok",
  changed: "warn",
  unreachable: "bad",
  not_fetchable: "",
};

const VALIDATION_LABEL: Record<string, string> = {
  valid: "content verified",
  changed: "content changed since last check",
  unreachable: "could not fetch",
  not_fetchable: "not a URL — can't verify",
};

function ValidationStatus({ source }: { source: any }) {
  if (!source.last_validated_at) {
    return <span className="small muted">never checked</span>;
  }
  const tone = VALIDATION_TONE[source.last_validation_status] || "";
  const label = VALIDATION_LABEL[source.last_validation_status] || source.last_validation_status;
  return (
    <span className={`tag ${tone}`} title={`Last checked ${new Date(source.last_validated_at).toLocaleString()}`}>
      {label}
    </span>
  );
}

const CONNECTION_LABEL: Record<string, string> = {
  database: "Database",
  api: "Enterprise API / KB",
};

function ConnectionBadge({ source }: { source: any }) {
  if (!source.connection_kind) {
    return (
      <span className="small muted" title="No connection registered — a plain http(s) key is fetched directly; anything else can't be checked at all.">
        {/^https?:\/\//i.test(source.key) ? "plain URL" : "no connection"}
      </span>
    );
  }
  return <span className="tag">{CONNECTION_LABEL[source.connection_kind] || source.connection_kind}</span>;
}

/**
 * P8 — source authority.
 *
 * The gap our own groundedness scorer is blind to by construction: it checks the
 * answer against the retrieved context and never asks whether that context was
 * authoritative. An answer faithfully grounded in a deprecated wiki page scores 1.0.
 */
export default async function Sources({
  searchParams,
}: {
  searchParams: Promise<{ review_error?: string; review_notice?: string }>;
}) {
  const { review_error, review_notice } = await searchParams;
  let sources: any, health: any;
  try {
    [sources, health] = await Promise.all([api("/api/sources"), api("/api/sources/health")]);
  } catch (e: any) {
    return (
      <>
        <h1>Verified sources</h1>
        <ApiDown {...apiErrorProps(e)} />
      </>
    );
  }

  const counts = sources.counts || {};

  const addSourceModal = (
    <Modal trigger="+ Add a source" triggerClassName="btn-primary" title="Add a source">
      <SourceAddFlow />
    </Modal>
  );

  return (
    <>
      <PageHeader
        title="Verified sources"
        sub={
          <>
            Which sources are systems of record, and which are somebody&rsquo;s
            notebook. A stale one raises a{" "}
            <Link href="/app/findings">finding</Link> next time an agent is grounded
            in it.
          </>
        }
        action={sources.sources.length > 0 ? addSourceModal : undefined}
      />

      {review_error && <div className="error">{review_error}</div>}
      {review_notice && <div className="note-panel">{review_notice}</div>}

      {sources.sources.length === 0 ? (
        <>
          <div className="hero empty" style={{ marginBottom: 20 }}>
            <div className="hero-title">No sources tiered yet</div>
            <p>
              Until a source has a tier, every retrieved chunk is treated as unverified —
              which is the safe default and tells you nothing. Register one below (just a
              name and a trust tier), then come back to actually connect it to a real
              database or API — that's step 2, and it's what turns this from a claim into
              a checked fact. Or import a whole corpus at once with{" "}
              <code className="mono">agentfox declare import-sources sources.json</code>.
            </p>
          </div>
          <Panel title="Add a source">
            <SourceAddFlow />
          </Panel>
        </>
      ) : (
        <>
          {/* Five tiles, and on a healthy index three of them are zero wearing a
              coloured border — "0 external" and "0 past their freshness SLA" are the
              good news and were shouting. The tier distribution is a breakdown of one
              total, so it is a bar; staleness is the one thing that wants a person,
              so it stays a tile and only when it is non-zero. */}
          {(health.stale?.length || 0) > 0 && (
            <div className="cards">
              <div className="card warn">
                <div className="n">{health.stale.length}</div>
                <div className="l">past their freshness SLA</div>
              </div>
            </div>
          )}

          <StatusBar
            segments={[
              { n: counts.system_of_record || 0, label: "system of record", tone: "ok" },
              { n: counts.approved || 0, label: "approved", tone: "ok" },
              { n: counts.unverified || 0, label: "unverified", tone: "warn" },
              { n: counts.external || 0, label: "external", tone: "bad" },
            ]}
          />

          {(health.deprecated?.length > 0 || health.unowned?.length > 0) && (
            <div className="note-panel">
              {health.deprecated?.length > 0 && (
                <div>
                  <strong>{health.deprecated.length} deprecated source(s)</strong> still in
                  the index. Every answer grounded in one raises a finding.
                </div>
              )}
              {health.unowned?.length > 0 && (
                <div>
                  <strong>{health.unowned.length} source(s) without an owner.</strong> Nobody
                  is accountable for whether they are still true.
                </div>
              )}
            </div>
          )}

          <h2>Registered sources</h2>
          <p className="sub">
            A tier is a person&rsquo;s claim about a source. &ldquo;Validate&rdquo; is us
            actually fetching it and checking the content is still what it was — a
            registered key is not proof anything real backs it.
          </p>
          <div className="panel">
            <table>
              <thead>
                <tr>
                  <th>tier</th>
                  <th>source</th>
                  <th>
                    connection
                    <InfoTip text="How this source is actually reached for validation — a database or an authenticated API, not just a name. A plain http(s) key is fetched directly with no connection needed." />
                  </th>
                  <th>owner</th>
                  <th>domain</th>
                  <th>freshness</th>
                  <th>
                    content check
                    <InfoTip text="Only http(s) source keys, or sources with a registered connection, can be checked. A bare table name or document id with no connection has nothing to check against, and is reported as 'not a URL' rather than silently passing." />
                  </th>
                  <th style={{ textAlign: "right" }}>actions</th>
                </tr>
              </thead>
              <tbody>
                {sources.sources.map((s: any) => (
                  <tr key={s.key}>
                    <td>
                      <span className={`tag ${TIER_TONE[s.tier] || ""}`}>
                        {s.tier.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td>
                      <span className="mono small">{s.key}</span>
                      {s.deprecated && <span className="tag bad">deprecated</span>}
                      {s.is_seed && (
                        <span
                          className="tag"
                          title="Created by `agentfox admin seed` for demo purposes — not a real registration."
                        >
                          sample data
                        </span>
                      )}
                    </td>
                    <td className="small">
                      <ConnectionBadge source={s} />
                    </td>
                    <td className="small">{s.owner || <span className="muted">unowned</span>}</td>
                    <td className="small muted">{s.domain || "—"}</td>
                    <td className="small">
                      {s.freshness_sla_hours ? (
                        <>
                          <span className={`tag ${s.stale ? "warn" : "ok"}`}>
                            {s.stale ? "stale" : "fresh"}
                          </span>
                          <span className="muted"> {s.freshness_sla_hours}h SLA</span>
                        </>
                      ) : (
                        <span className="muted">no SLA</span>
                      )}
                    </td>
                    <td className="small">
                      <ValidationStatus source={s} />
                    </td>
                    <td className="small" style={{ textAlign: "right" }}>
                      <SourceRowActions source={s} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>
        Check ingestion quality
        <InfoTip text="A source can be perfectly authoritative and still fail an agent because of how it was extracted or chunked — a lost space glyph glues words together, a PDF-to-text pass leaves mojibake, a chunk boundary cuts a claim's exception onto the wrong side. This is a dry run against real text before it becomes context, distinct from the trust tiering above, which is about whether the source itself is authoritative, not whether the text survived extraction intact." />
      </h2>
      <p className="sub">
        Not tied to a registered source — paste what a loader actually extracted, or
        what would reach the retriever as chunks, and see the same checks a governed
        ingestion pipeline would run.
      </p>
      <ContextCheck />
    </>
  );
}

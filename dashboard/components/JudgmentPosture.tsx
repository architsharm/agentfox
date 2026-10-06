import Link from "next/link";

/**
 * What the optional judgment tiers may decide, what leaves the box, and the form
 * that changes both.
 *
 * The detector catalogue can say these checks are off; it cannot say why, or what
 * happens to a customer's text once they are on. Both are policy choices, and until
 * this panel existed the only way to see or change either was to edit a TOML file and
 * redeploy — including the egress posture, which is the most consequential setting in
 * the product and the one an auditor is most likely to ask the history of.
 *
 * Two things are deliberately not symmetrical here:
 *
 * *The ceiling is not editable.* `allow_egress` and the deployment's own PII floor
 * come from the process environment. A control that cannot be chosen is still
 * rendered, disabled, with the reason — a checkbox that is simply absent teaches an
 * operator the feature does not exist, and they go looking for a vendor who has it.
 *
 * *Widening egress is confirmed; narrowing is not.* The confirmation guards the
 * direction whose consequence is invisible from this screen: nothing breaks, no
 * latency moves, and the first observable effect is a customer's data in somebody
 * else's logs.
 *
 * Everything factual is rendered from `judgment/capability.py`'s routing table,
 * refusal reasons and measurements included. Restating any of it here would be a
 * second copy to drift.
 */

type Kind = {
  combine: string;
  deciders: string[];
  refused: Record<string, string>;
  band?: number[] | null;
  measured?: Record<string, { accuracy: number; n: number; corpus: string; note: string }>;
};

/** The shape `/api/detectors` carries — read-only, no ceiling, no form. */
export type Posture = {
  tiers_enabled: string[];
  allow_egress: boolean;
  pii_egress: string;
  backend: string;
  redact_before_egress: boolean;
  fail_closed?: boolean;
  kinds: Record<string, Kind>;
};

/** The shape `/api/judgment/posture` carries — everything needed to render the form. */
export type PostureDetail = {
  posture: {
    tiers: string[];
    pii_egress: string;
    fail_closed: boolean;
    backend: string;
    version: number;
  };
  ceiling: {
    allow_egress: boolean;
    pii_egress: string;
    fail_closed_required: boolean;
    explains: string;
  };
  tiers: {
    tier: string;
    enabled: boolean;
    sends_data: boolean;
    selectable: boolean;
    blocked_reason: string;
  }[];
  pii_egress_options: { value: string; label: string; detail: string; selectable: boolean }[];
  backends: { value: string; selectable: boolean }[];
  sends_anything: boolean;
  kinds: Record<string, Kind>;
};

const KIND_LABEL: Record<string, string> = {
  structural_parsed: "Parsed structure (SQL blast radius)",
  structural_grant: "Grant lookup (entitlement)",
  pattern_open: "Open-ended patterns (injection, PII presence)",
  semantic: "Meaning (is this question contested)",
  performative: "What an utterance does (binding commitments)",
};

const TIER_LABEL: Record<string, string> = {
  deterministic: "Deterministic — code, parsers and rules",
  local_model: "Local model — classifier weights on this host",
  local_llm: "Local LLM — a model served on loopback",
  jev: "Jev — TypeSafe System One (hosted)",
  llm: "LLM as judge (hosted)",
};

const EGRESS_NOTE: Record<string, string> = {
  block:
    "Nothing containing detected personal data leaves, redacted or not. The only setting under which a subject's data cannot reach a vendor.",
  redact:
    "Locally-detected personal data is masked before anything is sent. Redaction can only mask what the local detector finds, so some still leaves.",
  allow: "Payloads are sent unredacted. A deliberate downgrade.",
};

function KindTable({ kinds }: { kinds: Record<string, Kind> }) {
  return (
    <table className="rt-table small">
      <thead>
        <tr>
          <th>Decision</th>
          <th>Decided by</th>
          <th>Not permitted, and why</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(kinds).map(([kind, k]) => (
          <tr key={kind}>
            <td>{KIND_LABEL[kind] ?? kind}</td>
            <td className="mono small">{k.deciders.join(" → ")}</td>
            <td className="small muted">
              {Object.entries(k.refused).length === 0 ? (
                "—"
              ) : (
                <ul className="bare">
                  {Object.entries(k.refused).map(([tier, why]) => (
                    <li key={tier}>
                      <span className="mono">{tier}</span> — {why}
                    </li>
                  ))}
                </ul>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * The read-only summary, rendered from `/api/detectors`.
 *
 * Kept for the pages that already have the detector payload in hand and have no
 * business offering a write — the catalogue is a status page, and a status page that
 * grows a settings form stops being readable at a glance.
 */
export function JudgmentPosture({ posture }: { posture?: Posture | null }) {
  if (!posture) return null;
  const optional = posture.tiers_enabled.filter((t) => t !== "deterministic");
  const live = optional.length > 0;

  return (
    <details className="rt-more">
      <summary>
        Judgment tiers —{" "}
        {live ? (
          <>
            <strong>{optional.join(", ")}</strong> enabled
          </>
        ) : (
          <>none enabled (deterministic only)</>
        )}
      </summary>

      <p className="small muted">
        Optional evaluators that answer the questions code cannot. Each is forbidden from
        deciding the kinds it measured worse on, so enabling one widens coverage and cannot
        make an existing control worse —{" "}
        <Link href="/docs/benchmarks">the measurements</Link> behind that are published.
      </p>

      <table className="rt-table small">
        <tbody>
          <tr>
            <th>Egress</th>
            <td>
              {posture.allow_egress ? (
                <span className="mono">allowed</span>
              ) : (
                <span className="mono">off — nothing leaves this deployment</span>
              )}
            </td>
          </tr>
          <tr>
            <th>Personal data</th>
            <td>
              <span className="mono">{posture.pii_egress}</span>{" "}
              <span className="muted">{EGRESS_NOTE[posture.pii_egress] ?? ""}</span>
            </td>
          </tr>
        </tbody>
      </table>

      <KindTable kinds={posture.kinds} />

      <p className="small muted">
        Change these on{" "}
        <Link href="/app/policies?tab=judgment">Policies → Judgment posture</Link>. A
        self-hosted model on loopback counts as <span className="mono">local_llm</span> and
        does not egress.
      </p>
    </details>
  );
}

/**
 * The editable surface, rendered from `/api/judgment/posture`.
 *
 * A plain form that posts the whole document: the dangerous changes here are
 * combinations, and a field-at-a-time control never shows anyone the pair.
 */
export function JudgmentPostureForm({
  detail,
  returnTo,
  canEdit,
  error,
  notice,
}: {
  detail: PostureDetail;
  returnTo: string;
  canEdit: boolean;
  error?: string;
  notice?: string;
}) {
  const { posture, ceiling } = detail;
  const blocked = detail.tiers.filter((t) => !t.selectable && t.tier !== "deterministic");

  return (
    <div className="panel">
      <div className="head">
        <span>Judgment posture</span>
        <span className="small muted">version {posture.version}</span>
      </div>
      <div className="body">
        {notice && <p className="small ok">{notice}</p>}
        {error && (
          <p className="small bad" role="alert">
            {error}
          </p>
        )}

        <p className="small muted" style={{ marginTop: 0 }}>
          Optional evaluators that answer the questions code cannot. Each is forbidden
          from deciding the kinds it measured worse on, so enabling one widens coverage
          and cannot make an existing control worse —{" "}
          <Link href="/docs/benchmarks">the measurements</Link> are published.
        </p>

        <div
          className="panel"
          style={{
            marginBottom: 16,
            borderColor: detail.sends_anything ? "var(--warn)" : "var(--border)",
          }}
        >
          <div className="body small">
            <strong>
              {detail.sends_anything
                ? "This tenant sends payloads to a third party."
                : "Nothing leaves this deployment."}
            </strong>{" "}
            {ceiling.allow_egress ? (
              <>
                Egress is permitted by the deployment (
                <span className="mono">allow_egress</span>), so the tiers below that send
                data can be switched on here.
              </>
            ) : (
              <>
                Egress is switched off at the deployment level (
                <span className="mono">NOMETRIA_ALLOW_EGRESS</span>). {ceiling.explains}
              </>
            )}
          </div>
        </div>

        <form method="post" action="/api/judgment/posture">
          <input type="hidden" name="return_to" value={returnTo} />

          <fieldset disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
            <h4 className="small">Tiers</h4>
            <ul className="bare">
              {detail.tiers.map((t) => (
                <li key={t.tier} style={{ marginBottom: 8 }}>
                  <label>
                    <input
                      type="checkbox"
                      name="tiers"
                      value={t.tier}
                      defaultChecked={t.enabled}
                      disabled={!t.selectable}
                    />{" "}
                    <span className="mono">{t.tier}</span> —{" "}
                    {TIER_LABEL[t.tier] ?? t.tier}
                    {t.sends_data && (
                      <span className="small warn"> · sends the payload off this machine</span>
                    )}
                  </label>
                  {t.blocked_reason && (
                    <div className="small muted" style={{ marginLeft: 22 }}>
                      {t.blocked_reason}
                    </div>
                  )}
                </li>
              ))}
            </ul>

            <h4 className="small">Personal data on the way out</h4>
            <ul className="bare">
              {detail.pii_egress_options.map((o) => (
                <li key={o.value} style={{ marginBottom: 8 }}>
                  <label>
                    <input
                      type="radio"
                      name="pii_egress"
                      value={o.value}
                      defaultChecked={posture.pii_egress === o.value}
                      disabled={!o.selectable}
                    />{" "}
                    <span className="mono">{o.value}</span> — {o.label}
                  </label>
                  <div className="small muted" style={{ marginLeft: 22 }}>
                    {o.detail}
                    {!o.selectable && (
                      <>
                        {" "}
                        <em>
                          Not available: this deployment&apos;s floor is{" "}
                          <span className="mono">{ceiling.pii_egress}</span>, and posture
                          may only tighten it.
                        </em>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>

            <h4 className="small">Transport</h4>
            <p className="small">
              <label>
                Backend{" "}
                <select name="backend" defaultValue={posture.backend}>
                  {detail.backends.map((b) => (
                    <option key={b.value} value={b.value} disabled={!b.selectable}>
                      {b.value}
                      {b.selectable ? "" : " (egress off)"}
                    </option>
                  ))}
                </select>
              </label>
            </p>
            <p className="small">
              {/* A disabled input is not submitted, so a checkbox that is merely
                  greyed out would post "fail_closed: false" and be refused by the
                  very ceiling that greyed it out — the form would be unsaveable on
                  exactly the deployments that care most. The hidden field carries
                  the required value; the visible one is there to be read. */}
              {ceiling.fail_closed_required && (
                <input type="hidden" name="fail_closed" value="on" />
              )}
              <label>
                <input
                  type="checkbox"
                  name={ceiling.fail_closed_required ? "fail_closed_display" : "fail_closed"}
                  defaultChecked={posture.fail_closed || ceiling.fail_closed_required}
                  disabled={ceiling.fail_closed_required}
                />{" "}
                Fail closed — a tier&apos;s outage denies the request rather than passing
                it unjudged.
              </label>
              {ceiling.fail_closed_required && (
                <span className="muted"> Required by this deployment.</span>
              )}
            </p>

            <h4 className="small">Why</h4>
            <p className="small">
              <input
                type="text"
                name="reason"
                required
                placeholder="Why this change is being made"
                style={{ width: "100%" }}
              />
            </p>
            <p className="small muted">
              Recorded in the audit chain with what the posture was before and after. It
              is the field an investigation actually reads, so it is required rather than
              optional.
            </p>

            <p className="small">
              <label>
                <input type="checkbox" name="confirm_egress" />{" "}
                <strong>
                  I am turning on a tier that sends data off this machine, or loosening
                  how personal data is handled on the way.
                </strong>
              </label>
            </p>
            <p className="small muted">
              Only needed for changes in that direction. Turning a remote tier off, or
              tightening personal-data handling, needs no confirmation.
            </p>

            <button type="submit" className="btn">
              Save posture
            </button>
          </fieldset>
        </form>

        {!canEdit && (
          <p className="small muted">
            Read-only for your role. Changing what leaves the building is restricted to
            owner, admin and security — the same roster that may silence a detector.
          </p>
        )}

        {blocked.length > 0 && (
          <p className="small muted">
            {blocked.length} tier{blocked.length === 1 ? "" : "s"} cannot be enabled from
            here. That bound is set by whoever runs the process, not from this page.
          </p>
        )}

        <h4 className="small">What each decision kind would use</h4>
        <KindTable kinds={detail.kinds} />
      </div>
    </div>
  );
}

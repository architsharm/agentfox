import Link from "next/link";

/**
 * What the optional judgment tiers may decide, and what leaves the box.
 *
 * The detector catalogue can say these two checks are off; it cannot say why,
 * or what happens to a customer's text once they are on. Both of those are
 * policy choices an operator makes, and until this panel existed the only way
 * to see or change either was to edit a TOML file — including the egress
 * posture, which is the most consequential setting in the product.
 *
 * Everything here is rendered from `judgment/capability.py`'s own routing
 * table, including the refusal reasons. Restating them in the UI would mean a
 * second copy to drift: if the table changes because a measurement changed,
 * this panel changes with it.
 */

type Kind = {
  combine: string;
  deciders: string[];
  refused: Record<string, string>;
};

export type Posture = {
  tiers_enabled: string[];
  allow_egress: boolean;
  pii_egress: string;
  backend: string;
  redact_before_egress: boolean;
  kinds: Record<string, Kind>;
};

const KIND_LABEL: Record<string, string> = {
  structural_parsed: "Parsed structure (SQL blast radius)",
  structural_grant: "Grant lookup (entitlement)",
  pattern_open: "Open-ended patterns (injection, PII presence)",
  semantic: "Meaning (is this question contested)",
  performative: "What an utterance does (binding commitments)",
};

const EGRESS_NOTE: Record<string, string> = {
  block:
    "Nothing containing detected personal data leaves, redacted or not. The only setting under which a subject's data cannot reach a vendor.",
  redact:
    "Locally-detected personal data is masked before anything is sent. Redaction can only mask what the local detector finds, so some still leaves.",
  allow: "Payloads are sent unredacted. A deliberate downgrade.",
};

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

      <table className="rt-table small">
        <thead>
          <tr>
            <th>Decision</th>
            <th>Decided by</th>
            <th>Not permitted, and why</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(posture.kinds).map(([kind, k]) => (
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

      <p className="small muted">
        Set with <span className="mono">judgment_tiers</span>,{" "}
        <span className="mono">allow_egress</span> and{" "}
        <span className="mono">judgment_pii_egress</span>. A self-hosted model on loopback
        counts as <span className="mono">local_llm</span> and does not egress.
      </p>
    </details>
  );
}

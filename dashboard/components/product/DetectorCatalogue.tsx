import Link from "next/link";

/**
 * Every check this product can run, installed or not.
 *
 * The Detectors strip counts three states — on, available but off, not
 * installed — and "not installed" used to be a number with nowhere to go. Most
 * of that number is now the Guardrails AI Hub, wrapped one validator per
 * detector, which means it is not a deficiency to explain away. It is a
 * catalogue, and the single best idea in Guardrails AI's own product is that
 * their catalogue is browsable: you can see the sixty-five things it can check
 * before you install any of them.
 *
 * So this is the same idea, with the part they do not have. Theirs lists what
 * exists. This one shows, for each check, whether it is running in your
 * deployment, what it costs when it runs, and the command that turns it on —
 * and a check that is on carries its own measured latency from your traffic,
 * which is a claim a catalogue of packages cannot make.
 *
 * Collapsed, because it is reference: an operator opens Policies to read the
 * rules in force, not to shop.
 */

type Detector = {
  key: string;
  version: string;
  surfaces: string[];
  available: boolean;
  enabled: boolean;
  unavailable_reason: string | null;
  label?: string | null;
  install?: string | null;
  stats?: { runs?: number; avg_ms?: number; max_ms?: number };
};

/** The prefix before the first dot, which is also how policy rules match. */
function family(key: string): string {
  return key.split(".")[0];
}

const FAMILY_LABEL: Record<string, string> = {
  injection: "Prompt injection and jailbreak",
  pii: "Personal data",
  secrets: "Credentials",
  safety: "Content safety",
  schema: "Structure and format",
  rails: "Wrapped from other projects",
};

export function DetectorCatalogue({ detectors }: { detectors: Detector[] }) {
  if (!detectors?.length) return null;

  // On first, then installed-but-off, then the rest — the same order as the
  // strip above, so the two agree about what matters.
  const rank = (d: Detector) => (d.enabled && d.available ? 0 : d.available ? 1 : 2);
  const rows = [...detectors].sort(
    (a, b) => rank(a) - rank(b) || a.key.localeCompare(b.key),
  );
  const installable = rows.filter((d) => !d.available && d.install).length;

  return (
    <details className="rt-more" style={{ marginTop: 18 }}>
      <summary>
        Every check available ({detectors.length})
        {installable > 0 && ` — ${installable} one command away`}
      </summary>

      <p className="sub">
        What each check looks at, whether it is running here, and what it costs
        when it does. Checks wrapped from other projects report through this
        product&rsquo;s own latency budget and precision tracking, so a number
        beside one of them was measured on your traffic.
      </p>

      <div className="panel scroll-x">
        <table>
          <thead>
            <tr>
              <th>check</th>
              <th>looks at</th>
              <th>state</th>
              <th className="num">typical</th>
              <th>to turn it on</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => {
              const fam = family(d.key);
              const on = d.enabled && d.available;
              return (
                <tr key={d.key} className={on ? undefined : "det-off"}>
                  <td className="small wrap" style={{ maxWidth: 260 }}>
                    {/* Native detectors have no separate label — their key IS
                        the name — so showing both printed it twice. */}
                    {d.label ? (
                      <>
                        {d.label}
                        <div className="mono small muted">{d.key}</div>
                      </>
                    ) : (
                      <span className="mono">{d.key}</span>
                    )}
                    <div className="det-fam">{FAMILY_LABEL[fam] || fam}</div>
                  </td>
                  {/* Which surfaces, not how many: "input only" and "everything
                      an agent reads" are the difference between a check that
                      sees indirect injection and one that cannot. */}
                  <td className="small muted wrap" style={{ maxWidth: 220 }}>
                    {d.surfaces.length >= 6 ? (
                      <span title={d.surfaces.join(", ")}>every surface</span>
                    ) : (
                      d.surfaces.join(", ")
                    )}
                  </td>
                  <td className="small">
                    {on ? (
                      <span className="tag ok">on</span>
                    ) : d.available ? (
                      <span className="tag">installed, off</span>
                    ) : (
                      <span className="tag muted-tag">not installed</span>
                    )}
                  </td>
                  {/* Only a check that has actually run has a number. An empty
                      cell here is honest; a 0.0 would read as "instant". */}
                  <td className="num small muted">
                    {d.stats?.runs ? `${d.stats.avg_ms?.toFixed(2)}ms` : "—"}
                  </td>
                  <td className="small wrap" style={{ maxWidth: 300 }}>
                    {on ? (
                      <span className="muted">running</span>
                    ) : d.available ? (
                      <code className="mono">add {d.key} to enabled_detectors</code>
                    ) : d.install ? (
                      <code className="mono">pip install {d.install}</code>
                    ) : (
                      <span className="muted small">{d.unavailable_reason ? "see below" : "—"}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="page-foot">
        Checks from the{" "}
        <a href="https://guardrailsai.com/hub" target="_blank" rel="noreferrer">
          Guardrails AI Hub
        </a>{" "}
        carry their own licences, independent of that project&rsquo;s Apache-2.0
        core, so none ships enabled — installing one is a deliberate act. They
        report into this product&rsquo;s taxonomy, so a jailbreak found by a
        wrapped check fires the same policy rule as one found by ours, with no new
        rule to write. Their telemetry is switched off before any of them runs:
        see <Link href="/app/glossary">the glossary</Link> on egress.
      </p>
    </details>
  );
}

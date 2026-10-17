/*
 * A grant, and a call that does not fit inside it.
 *
 * The old capability panel said this in prose: "The grant allows amount below
 * 1000, but this call passed 5000." True, and nobody reads it. A ceiling and a
 * value that crosses it is a quantity, and a quantity should be drawn — the bar
 * runs past the limit line and stops being green, which is the entire argument
 * of the product in one picture.
 *
 * It is also the most useful thing this page can show, because it is the case
 * that defeats the obvious objection. The agent is NOT missing a permission: it
 * holds a grant for payments.transfer and uses it legitimately every day. What
 * it does not hold is permission for this amount, from this source. A reader who
 * thinks "so just don't give the agent the tool" has not understood the problem
 * until they have seen this.
 *
 * Values are the ones in mocks.tsx's GrantMock and the containment suite's cb3:
 * `amount lt 1000`, a call at 5000, rule capability.constraint_violated.
 */

const LIMIT = 1000;
const ATTEMPTED = 5000;
/** The axis runs a little past the attempt so the overshoot has somewhere to go. */
const AXIS = 6000;

const pct = (n: number) => `${(n / AXIS) * 100}%`;

export function GrantLimit() {
  return (
    <div className="gl">
      <div className="gl-head">
        <span className="mk-label">the grant</span>
        <code className="mk-mono">agent:payments-ops &rarr; payments.transfer</code>
      </div>

      <dl className="gl-terms">
        <div>
          <dt>actions</dt>
          <dd className="mk-mono">*</dd>
        </div>
        <div>
          <dt>limits</dt>
          <dd className="mk-mono">amount lt 1000 · currency in USD</dd>
        </div>
        <div>
          <dt>provenance</dt>
          <dd className="mk-mono">user</dd>
        </div>
        <div>
          <dt>approval</dt>
          <dd className="mk-mono">not required</dd>
        </div>
      </dl>

      {/* The measurement. A ceiling and a value that crosses it. */}
      <div className="gl-scale">
        <div className="gl-track">
          <span className="gl-allowed" style={{ width: pct(LIMIT) }} />
          <span className="gl-bar" style={{ ["--w" as string]: pct(ATTEMPTED) }} />
          <span className="gl-limit" style={{ left: pct(LIMIT) }}>
            <i />
            <em>
              limit <b>1,000</b>
            </em>
          </span>
        </div>
        <div className="gl-axis" aria-hidden>
          <span>0</span>
          <span>{AXIS.toLocaleString()}</span>
        </div>
        <p className="gl-call">
          <span className="mk-label">this call</span>
          <code className="mk-mono">
            {"{ amount: "}
            <b>5000</b>
            {', currency: "USD", to: "acct_x" }'}
          </code>
        </p>
      </div>

      <div className="gl-verdict">
        <span className="gl-chip">block</span>
        <code className="mk-mono">capability.constraint_violated</code>
      </div>
      <p className="gl-why">
        The agent is not missing a permission — it holds this tool and uses it every
        day. It does not hold permission for <b>this amount</b>.
      </p>
    </div>
  );
}

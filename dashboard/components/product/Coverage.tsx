import Link from "next/link";

/* Written before the signed-in app moved under /app. Middleware still 308s the
   old paths, so these worked — through a redirect on every click. */
import { StatLink } from "@/components/ui";
import { coverageNumbers, type CoverageInput } from "@/lib/product/coverage";

/**
 * What is actually switched on — the one thing the Overview never said.
 *
 * Every number on this strip already existed in the product, each on a different
 * page, and each only reachable by someone who already knew the page was there:
 * rule counts on /policies, detector enablement on /policies?tab=guardrails,
 * the probe library at the bottom of /policies, control effectiveness on
 * /compliance. A reader who lands on the Overview and sees only "5 problems"
 * has no way to tell whether that 5 came out of a system with 34 rules and 5
 * detectors running, or out of an empty one. The count of problems is not a
 * measure of protection, and without the denominator it reads like one.
 *
 * Each tile is a link rather than a number, because the honest version of every
 * one of these claims is the page that itemises it — a summary of enforcement
 * that can't be drilled into is a marketing figure.
 *
 * Deliberately NOT toned green. `enforcing` vs `observing` is a legitimate
 * configuration choice, not a score, and colouring "22 of 34 enforcing" as a
 * failure would push readers to promote policies they haven't validated — which
 * is exactly the behaviour the observe-first default exists to prevent.
 */
export function Coverage(input: CoverageInput) {
  const c = coverageNumbers(input);

  return (
    <>
      <h2>What is switched on</h2>
      <p className="sub" style={{ marginTop: -8 }}>
        The checks standing between your agents and a bad outcome right now. Every
        number here links to the page that itemises it.
      </p>
      <div className="cards">
        <StatLink
          n={`${c.rulesEnforcing} of ${c.rulesTotal}`}
          label="policy rules enforcing"
          href="/app/policies"
          hint={
            c.rulesObserving > 0
              ? `The other ${c.rulesObserving} are in observe mode: they evaluate every request and record what they would have done, without changing the outcome. That is the shipped default — a rule is meant to be watched before it is allowed to block.`
              : "Every rule in every policy is enforcing — a matching request is acted on, not just recorded."
          }
        />
        <StatLink
          n={`${c.detectorsOn} of ${c.detectorsAvailable}`}
          label="detectors running"
          href="/app/policies?tab=advanced&sec=tuning"
          hint={`Of ${c.detectorsInstalled} checks this build knows about, ${c.detectorsAvailable} are installed here and ${c.detectorsOn} are switched on. Detection raises the cost of an attack; it is not what contains one — see the three checks that hold after a model has already been fooled.`}
        />
        <StatLink
          n={c.probes}
          label="attack simulations you can run"
          href="/app/evals"
          hint="Scripted attempts to break an agent — injection, jailbreak, exfiltration, ungranted tool use — that can be run against any agent on demand, rather than assuming it holds up."
        />
        <StatLink
          n={`${c.controlsEffective} of ${c.controlsAssessed}`}
          label="controls effective"
          href="/app/compliance"
          tone={c.controlsAssessed && c.controlsEffective < c.controlsAssessed ? "warn" : undefined}
          hint="Of controls that have actually been assessed from telemetry. Controls that are not implemented, not applicable, or not yet computed are excluded rather than counted as passes — the full breakdown is on the Compliance page."
        />
      </div>
      <p className="small muted" style={{ marginTop: 10 }}>
        Observing is not off. A rule in observe mode still evaluates every request
        and writes the decision it would have made to the audit log, so you can see
        what promoting it would have blocked before you promote it —{" "}
        <Link href="/app/traces">replay it against your own traces</Link> first.
      </p>
    </>
  );
}

/**
 * The arithmetic behind the Overview's "what is switched on" strip, kept out of
 * the component so it can be tested directly — each of these ratios has a
 * denominator that is a judgement call, and a wrong denominator here misstates
 * the product's posture on the first screen a reader sees.
 */

export type CoverageInput = {
  policies: { mode?: string; rules?: number }[];
  detectors: { enabled?: boolean; available?: boolean }[];
  probes: unknown[];
  controls: { counts?: Record<string, number> };
};

export function coverageNumbers({ policies, detectors, probes, controls }: CoverageInput) {
  const rulesTotal = policies.reduce((n, p) => n + (p.rules || 0), 0);
  const rulesEnforcing = policies
    .filter((p) => p.mode === "enforce")
    .reduce((n, p) => n + (p.rules || 0), 0);

  const detectorsOn = detectors.filter((d) => d.enabled).length;
  // "Available" is the honest denominator for detectors: a check that isn't
  // installed can't be switched on, so counting it as a gap would be telling
  // the reader to fix something that isn't theirs to fix. The installed count
  // still travels, in the hint, so the larger number isn't hidden either.
  const detectorsAvailable = detectors.filter((d) => d.available).length;

  const counts = controls.counts || {};
  // not_implemented / not_applicable / not_computed are neither passes nor
  // failures. Folding them into the denominator would understate effectiveness
  // and folding them into the numerator would overstate it, so assessed
  // controls are the only honest base.
  const controlsAssessed =
    (counts.effective || 0) + (counts.degraded || 0) + (counts.failing || 0);

  return {
    rulesTotal,
    rulesEnforcing,
    rulesObserving: rulesTotal - rulesEnforcing,
    detectorsOn,
    detectorsAvailable,
    detectorsInstalled: detectors.length,
    probes: probes.length,
    controlsEffective: counts.effective || 0,
    controlsAssessed,
  };
}

/**
 * Control posture as one number, said the same way on Reports → Summary and
 * Reports → Compliance.
 *
 * They used to disagree: Summary divided working controls by every control that
 * applies (35 of 43, 81%), Compliance by the ones measured so far (35 of 40, 88%),
 * and Summary's headline was an average of four framework rows rather than the
 * workspace's own figure. Both now use this: working out of every control that
 * applies, because "8 of 8 measured" read as 100% with 29 controls not set up.
 */

export type Posture = {
  controls?: number;
  counts?: Record<string, number | undefined>;
};

export function controlShare(p: Posture | null | undefined): {
  working: number;
  applies: number;
  measured: number;
  notSetUp: number;
  share: number | null;
} {
  const c = p?.counts || {};
  const applies = Math.max(0, (p?.controls || 0) - (c.not_applicable || 0));
  const working = c.effective || 0;
  const measured = working + (c.degraded || 0) + (c.failing || 0);
  return {
    working,
    applies,
    measured,
    notSetUp: c.not_implemented || 0,
    share: applies ? working / applies : null,
  };
}

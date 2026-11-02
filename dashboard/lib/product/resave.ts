/**
 * Bodies for re-saving something the gateway stores whole. Each save endpoint
 * overwrites the row with what it is sent, and fills anything missing with its
 * default, so an editor that only shows some fields must send back the rest as it
 * found them. Otherwise one edit quietly widens a grant, re-enables a rule, or drops
 * a ladder band's check.
 */

/** An agent's grant for one tool, as GET /api/agents/{slug}/access returns it. */
export type Grant = {
  tool_key: string;
  /** Which of the tool's actions the grant covers. */
  actions?: string[];
  requires_approval: boolean;
  max_taint: string;
  constraints: Record<string, any>;
};

/** The grant with one change, keeping its actions so a narrowed grant stays narrow. */
export function grantPayload(c: Grant, patch: Partial<Grant>) {
  return {
    tool_key: c.tool_key,
    requires_approval: patch.requires_approval ?? c.requires_approval,
    max_taint: patch.max_taint ?? c.max_taint,
    constraints: patch.constraints ?? c.constraints,
    ...(patch.actions || c.actions ? { actions: patch.actions ?? c.actions } : {}),
  };
}

/** One rung of an approval ladder. `verify` and `label` are not edited in the
 *  dashboard; they ride along from the saved band. */
export type Band = {
  upto: number | null;
  outcome: string;
  approver_role?: string | null;
  reason?: string;
  verify?: Record<string, unknown> | null;
  label?: string;
  [extra: string]: unknown;
};

/** Ladder bands ready to PUT: ordered, open band last, every field the editor
 *  doesn't touch kept. A role only means something on "ask a person", and a check
 *  spec only on "check first", so those are dropped from bands that moved off them. */
export function bandsForSave(bands: Band[]): Record<string, unknown>[] {
  const ordered = [...bands].sort((a, b) => (a.upto ?? Infinity) - (b.upto ?? Infinity));
  return ordered.map(({ upto, approver_role, reason, verify, ...rest }) => ({
    ...rest,
    ...(upto === null ? {} : { upto }),
    ...(rest.outcome === "escalate" && approver_role ? { approver_role } : {}),
    ...(reason ? { reason } : {}),
    ...(rest.outcome === "verify" && verify ? { verify } : {}),
  }));
}

/** A "check first" band needs a check spec, which is written in the rule's
 *  definition (YAML or the API), not here. */
export function canCheckFirst(band: Band): boolean {
  return Boolean(band.verify);
}

/** Custom-rule fields the rule form doesn't show. The gateway defaults them
 *  (case-insensitive, enabled, within the session) on every save. */
export type KeptRuleFields = {
  case_sensitive?: boolean;
  enabled?: boolean;
  sequence?: { within?: string } | null;
};

export function keptRuleFields(initial?: KeptRuleFields): { case_sensitive?: boolean; enabled?: boolean } {
  if (!initial) return {};
  return {
    ...(initial.case_sensitive !== undefined ? { case_sensitive: initial.case_sensitive } : {}),
    ...(initial.enabled !== undefined ? { enabled: initial.enabled } : {}),
  };
}

export function keptWithin(initial?: KeptRuleFields): { within?: string } {
  const within = initial?.sequence?.within;
  return within ? { within } : {};
}

/**
 * Which kind of principal a grant names.
 *
 * The gateway matches a grant against a caller as either `("subject", their id)` or
 * `("group", one of their teams)` (capabilities/grounding/entitlement.py). The Access control form
 * used to post `principal_kind=group` for every grant, so a grant to
 * `alice@yourcompany.com` was stored as a *group* called that, matched nobody, and
 * the source stayed invisible to Alice with no error anywhere.
 *
 * An explicit choice from the form wins. Left on "work it out", an address with an
 * `@` is a person and anything else is a team — the same split the form's own
 * placeholders (`alice@yourcompany.com`, `support-team`) already teach.
 */
export type PrincipalKind = "subject" | "group";

export function grantPrincipalKind(principal: string, chosen?: string | null): PrincipalKind {
  const choice = (chosen || "").trim().toLowerCase();
  if (choice === "subject" || choice === "user" || choice === "person") return "subject";
  if (choice === "group" || choice === "team") return "group";
  return principal.includes("@") ? "subject" : "group";
}

import { NextRequest } from "next/server";
import { proxyPublicFormPost } from "@/lib/product/proxy";

/**
 * "Join the hosted-cloud waitlist" — posted by a plain HTML form on the pricing
 * page, from a visitor who by definition has no account. Same
 * plain-form-POST-plus-`return_to`-redirect shape as the review actions, and the one
 * route in this app that forwards without a session cookie, because the gateway
 * endpoint behind it (`POST /api/waitlist`) is public by design. `middleware.ts`
 * has a matching entry; without it a signed-out visitor submitting the form is
 * redirected to /login and their signup is silently dropped.
 *
 * Fields are whitelisted rather than forwarded wholesale: a public form is a public
 * write, so what reaches the gateway should be what the page meant to ask, not
 * whatever a crafted POST happens to include — and `return_to` itself must never end
 * up in the API payload.
 */

/** What `source` may be, matching the gateway's own rule. A value that is a slug and
 *  nothing else keeps the operator's `WHERE source = ...` honest; anything else is
 *  dropped here so the gateway's default ("hosted-cloud") applies instead of the
 *  visitor seeing a validation error about a field their form did not show them. */
const SOURCE = /^[a-z0-9][a-z0-9-]{0,63}$/;

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const returnTo = form.get("return_to");

  const body: Record<string, string> = {};
  for (const key of ["email", "company", "note"]) {
    const value = form.get(key);
    if (typeof value === "string" && value.trim()) body[key] = value.trim();
  }
  const source = form.get("source");
  if (typeof source === "string" && SOURCE.test(source.trim().toLowerCase())) {
    body.source = source.trim().toLowerCase();
  }

  return proxyPublicFormPost(
    req,
    "/api/waitlist",
    typeof returnTo === "string" ? returnTo : null,
    "/pricing",
    body,
    (res, resBody) => {
      if (res.ok) {
        // The gateway distinguishes a new signup from a repeat one and phrases both;
        // pass its wording through rather than second-guessing it here.
        return { notice: resBody?.message || "You're on the list." };
      }
      // Fixed messages by status rather than the gateway's `detail`: a 422 body is
      // Pydantic's error list, which renders as "[object Object]" in a query string,
      // and this page is public — whatever lands in the URL is something a stranger
      // can put there via a link.
      if (res.status === 422 || res.status === 400) {
        return { error: "That doesn't look like an email address — please check it." };
      }
      if (res.status === 429) {
        return { error: "Too many signups from your network just now — try again later." };
      }
      return { error: "Something went wrong — please try again." };
    },
    { noticeParam: "waitlist_notice", errorParam: "waitlist_error" },
  );
}

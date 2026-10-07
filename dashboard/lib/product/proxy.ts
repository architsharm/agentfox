/**
 * Shared body for the review-action route handlers (agent/policy approve & reject,
 * and every other plain-HTML-form-POST-no-client-JS route). Each one turns a form
 * submission into an authenticated call to the gateway and a redirect back to where
 * the user was, with the outcome in the query string.
 *
 * `proxyForward` is the one real implementation; everything else below is a thin,
 * named wrapper over it. A route with a genuinely custom request body (parsed
 * comma-separated lists, checkbox arrays, numeric coercion — `agents/[slug]/boundary`
 * is the example that motivated `proxyCustomBody`) still gets the shared
 * auth-check/fetch/error-handling/redirect skeleton; it just builds its own `body`
 * object first instead of forwarding form fields verbatim.
 *
 * Deliberately session-cookie-only, unlike `lib/product/api.ts`'s `authHeaders()` (used by
 * server-rendered *reads*), which also falls back to `AGENTFOX_API_TOKEN` or a
 * static dev-identity header so local dev/demo pages work with no auth wired up at
 * all. Every route here is a *mutation* — approve, deny, revoke, delete, save — and
 * this is an audit/governance product: attributing a mutation to a synthetic
 * "admin@example.com" identity under the dev fallback would misattribute exactly
 * the record this product exists to keep honest. A caller with no real session gets
 * a clean "not signed in" instead of a silently-misattributed write.
 */

import { NextRequest, NextResponse } from "next/server";
import { apiBase } from "@/lib/env";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "./api";

const API_BASE = apiBase();

type ForwardOpts = {
  /** Present -> redirect-shaped response; absent -> JSON response. */
  redirectTo?: string;
  body?: unknown;
  /** Set on the redirect target's query string when the call succeeds. */
  successNotice?: string;
  /**
   * Query param the error message is reported under. Defaults to "review_error",
   * the convention every page except app/start/page.tsx reads. That page
   * deliberately uses "scan_error" for a distinct concept (repo/API scan status,
   * not a review-action outcome) — pass it explicitly for that case rather than
   * silently renaming it to match everything else.
   */
  errorParam?: string;
  /** Passed straight through to fetch's `cache` option — "no-store" for a route
   * whose data must never be served stale (tokens/route.ts's GET, which lists
   * live credentials). */
  cache?: RequestCache;
};

async function proxyForward(
  req: NextRequest | null,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
  gatewayPath: string,
  opts: ForwardOpts = {},
): Promise<NextResponse> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const errorParam = opts.errorParam || "review_error";

  if (opts.redirectTo) {
    const target = new URL(opts.redirectTo, req!.nextUrl.origin);
    if (!token) {
      target.searchParams.set(errorParam, "not signed in");
      return NextResponse.redirect(target);
    }
    try {
      const res = await fetch(`${API_BASE}${gatewayPath}`, {
        method,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      });
      if (!res.ok) {
        const resBody = await res.json().catch(() => ({}));
        target.searchParams.set(errorParam, resBody.detail || res.statusText);
      } else if (opts.successNotice) {
        target.searchParams.set("review_notice", opts.successNotice);
      }
    } catch (e: any) {
      target.searchParams.set(errorParam, String(e?.message || e));
    }
    return NextResponse.redirect(target);
  }

  // No redirectTo -> a client component wants the response body directly.
  if (!token) {
    return NextResponse.json({ detail: "not signed in" }, { status: 401 });
  }
  try {
    const res = await fetch(`${API_BASE}${gatewayPath}`, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      ...(opts.cache ? { cache: opts.cache } : {}),
    });
    const resBody = await res.json().catch(() => ({}));
    return NextResponse.json(resBody, { status: res.status });
  } catch (e: any) {
    return NextResponse.json({ detail: String(e?.message || e) }, { status: 502 });
  }
}

/** Every non-blank field on the submitted form, trimmed. Blank fields are dropped
 * rather than sent as "" so a form re-submitted with one field filled in doesn't
 * clobber the others back to empty. */
async function formBody(req: NextRequest): Promise<Record<string, string>> {
  const form = await req.formData();
  const body: Record<string, string> = {};
  for (const [key, value] of form.entries()) {
    if (typeof value === "string" && value.trim()) body[key] = value.trim();
  }
  return body;
}

export async function proxyReviewAction(
  req: NextRequest,
  gatewayPath: string,
  redirectTo: string,
  opts?: { successNotice?: string; errorParam?: string },
): Promise<NextResponse> {
  return proxyForward(req, "POST", gatewayPath, { redirectTo, ...opts });
}

export async function proxyFormPatch(
  req: NextRequest,
  gatewayPath: string,
  redirectTo: string,
  opts?: { successNotice?: string; errorParam?: string },
): Promise<NextResponse> {
  return proxyForward(req, "PATCH", gatewayPath, { redirectTo, body: await formBody(req), ...opts });
}

export async function proxyFormPost(
  req: NextRequest,
  gatewayPath: string,
  redirectTo: string,
  opts?: { successNotice?: string; errorParam?: string },
): Promise<NextResponse> {
  return proxyForward(req, "POST", gatewayPath, { redirectTo, body: await formBody(req), ...opts });
}

export async function proxyFormPut(
  req: NextRequest,
  gatewayPath: string,
  redirectTo: string,
  opts?: { successNotice?: string; errorParam?: string },
): Promise<NextResponse> {
  return proxyForward(req, "PUT", gatewayPath, { redirectTo, body: await formBody(req), ...opts });
}

/**
 * Same skeleton (auth check, fetch, error handling, redirect) as the Form* helpers
 * above, but for a route whose request body isn't "forward every form field
 * verbatim" — comma-separated lists that need splitting into arrays, checkboxes
 * that need `formData.getAll`, numeric coercion, and the like. Build that body
 * locally, then hand it to this instead of hand-rolling the skeleton around it.
 */
export async function proxyCustomBody(
  req: NextRequest,
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  gatewayPath: string,
  redirectTo: string,
  body: unknown,
  opts?: { successNotice?: string; errorParam?: string },
): Promise<NextResponse> {
  return proxyForward(req, method, gatewayPath, { redirectTo, body, ...opts });
}

/**
 * For client components that need a live response rather than a redirect (the
 * policy YAML editor validates and saves interactively) — same authenticated
 * server-side forward as the helpers above, but returns the gateway's JSON body
 * (and status) directly instead of redirecting, so the client can render it inline.
 */
export async function proxyJson(
  gatewayPath: string,
  method: "GET" | "POST",
  jsonBody?: unknown,
  opts?: { cache?: RequestCache },
): Promise<NextResponse> {
  return proxyForward(null, method, gatewayPath, { body: jsonBody, ...opts });
}

/**
 * A path on this origin, or null. The guard on the public helper below.
 *
 * `new URL(returnTo, origin)` resolves an absolute URL to *that* URL, so a
 * `return_to=https://example.invalid/pay` on a form anyone can reach turns this
 * app's own domain into a redirector — the shape a phishing link wants, because the
 * link a victim sees and hovers is ours. The authenticated helpers above take their
 * `redirectTo` from route code rather than from the request, so they have never been
 * reachable this way; this one takes it from a form field posted by a stranger, so
 * it checks. A protocol-relative `//evil.example` is the case a bare `startsWith("/")`
 * misses, and is why the second test is here.
 */
function sameOriginPath(returnTo: string | null, fallback: string): string {
  if (!returnTo || !returnTo.startsWith("/") || returnTo.startsWith("//")) return fallback;
  return returnTo;
}

/**
 * The one helper here that sends no session cookie, for the one gateway endpoint
 * that is public: `POST /api/waitlist`. Joining a waitlist is what someone does
 * *before* they have an account, so the "not signed in" refusal every other helper
 * starts with would reject exactly the people the form exists for.
 *
 * Keep the exception to that: a route using this must front an endpoint that is
 * unauthenticated *at the gateway*, so nothing here is a way to reach a protected
 * one without a credential — the gateway still 401s those whatever this sends.
 *
 * Otherwise the skeleton is `proxyRedirectWithHandler`'s: forward, hand the caller
 * the parsed body so it can phrase the outcome, redirect back with the result in the
 * query string. The message is built by the route rather than echoed from the
 * gateway, because reflecting a stranger's input back into a URL on a marketing page
 * is not a thing to do by default.
 */
export async function proxyPublicFormPost(
  req: NextRequest,
  gatewayPath: string,
  returnTo: string | null,
  fallbackReturnTo: string,
  body: unknown,
  handleResult: (res: Response, body: any) => { notice?: string; error?: string },
  params: { noticeParam: string; errorParam: string },
): Promise<NextResponse> {
  const target = new URL(sameOriginPath(returnTo, fallbackReturnTo), req.nextUrl.origin);
  try {
    const res = await fetch(`${API_BASE}${gatewayPath}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const resBody = await res.json().catch(() => ({}));
    const { notice, error } = handleResult(res, resBody);
    if (error) target.searchParams.set(params.errorParam, error);
    else if (notice) target.searchParams.set(params.noticeParam, notice);
  } catch {
    // Deliberately not `String(e)`: with the gateway down that is a connection
    // string with a host and port in it, and this one lands on a public page.
    target.searchParams.set(params.errorParam, "Something went wrong — please try again.");
  }
  // 303, not `NextResponse.redirect`'s 307 default: 307 preserves the method, so the
  // browser would POST the form again at the page it is being sent to — which is a
  // Server Component that only answers GET. The helpers above inherit the default
  // because changing it is a behaviour change on a dozen signed-in routes; this one
  // is new, and the pricing form is a plain POST with no client JS to paper over it.
  return NextResponse.redirect(target, 303);
}

/**
 * Same auth-check/fetch/redirect skeleton as the helpers above, but for a route
 * whose success/error message depends on the *content* of the response, not just
 * its status — `audit/verify`'s "chain verified — N entries (seq A–B)" message,
 * built from the response body, is the case that motivated this. `handleResult`
 * always receives the parsed body (even on a non-ok status, since some of these
 * checks are logically pass/fail independent of HTTP status) and returns whatever
 * query params the route wants set on the redirect target — `notice`/`error` map
 * to the usual `review_notice`/`review_error` (or `opts.errorParam`, for the two
 * scan routes using `scan_error`), and `extra` covers a route-specific param like
 * `scan_run_id` that isn't a notice or an error at all.
 */
export async function proxyRedirectWithHandler(
  req: NextRequest,
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  gatewayPath: string,
  redirectTo: string,
  body: unknown,
  handleResult: (
    res: Response,
    body: any,
  ) => { notice?: string; error?: string; extra?: Record<string, string> },
  opts?: { errorParam?: string },
): Promise<NextResponse> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const errorParam = opts?.errorParam || "review_error";
  const target = new URL(redirectTo, req.nextUrl.origin);
  if (!token) {
    target.searchParams.set(errorParam, "not signed in");
    return NextResponse.redirect(target);
  }
  try {
    const res = await fetch(`${API_BASE}${gatewayPath}`, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const resBody = await res.json().catch(() => ({}));
    const { notice, error, extra } = handleResult(res, resBody);
    if (error) target.searchParams.set(errorParam, error);
    else if (notice) target.searchParams.set("review_notice", notice);
    if (extra) for (const [k, v] of Object.entries(extra)) target.searchParams.set(k, v);
  } catch (e: any) {
    target.searchParams.set(errorParam, String(e?.message || e));
  }
  return NextResponse.redirect(target);
}

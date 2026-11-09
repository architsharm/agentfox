/**
 * What the pricing page says after a waitlist submit, from the gateway's answer.
 *
 * The wording is the page's, not the gateway's: the gateway's `message` still
 * promises an email "when hosted AgentFox opens", from when this was a queue for the
 * hosted product, while the form now asks "tell me when pricing is announced". The
 * gateway's `status` ("added" or "already_on_list") is what is passed through.
 *
 * Fixed messages for failures rather than the gateway's `detail`: a 422 body is
 * Pydantic's error list, which renders as "[object Object]" in a query string, and
 * this page is public, so whatever lands in the URL is something a stranger can put
 * there via a link.
 */
export function waitlistResult(status: number, body: { status?: string } | null | undefined): { notice?: string; error?: string } {
  if (status >= 200 && status < 300) {
    return body?.status === "already_on_list"
      ? { notice: "You're already on the list. We'll email you once, when pricing is announced." }
      : { notice: "You're on the list. We'll email you once, when pricing is announced." };
  }
  if (status === 422 || status === 400) {
    return { error: "That doesn't look like an email address. Please check it and try again." };
  }
  if (status === 429) {
    return { error: "Too many signups from your network just now. Please try again later." };
  }
  return { error: "Something went wrong. Please try again." };
}

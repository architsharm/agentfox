import { redirect } from "next/navigation";

/**
 * A page that moved from being its own nav item to a tab on another page.
 * Forwards whatever query params the old URL carried (so a bookmarked filter
 * still works) and sets `tab` to the new home. Every route that calls this
 * exists purely so an old bookmark or link keeps working.
 */
export async function legacyTabRedirect(
  searchParams: Promise<Record<string, string | undefined>>,
  target: string,
  tab: string,
): Promise<never> {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string") query.set(key, value);
  }
  query.set("tab", tab);
  redirect(`${target}?${query.toString()}`);
}

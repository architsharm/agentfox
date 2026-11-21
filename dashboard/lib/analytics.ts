/**
 * Which pages the analytics script reports. The product app's URLs carry agent and
 * project names, so nothing under /app is sent; /app/welcome is the one exception,
 * where a new workspace's sign-up is counted and its URL names nobody.
 */
export function reported(pathname: string): boolean {
  return !pathname.startsWith("/app") || pathname === "/app/welcome";
}

/** Set once a browser's sign-up has been counted, so a reload of /app/welcome is not a second one. */
export const SIGNUP_KEY = "agentfox-signup-counted";

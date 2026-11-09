/**
 * Signing in and out, shared by the sign-in routes.
 */

/** The one first screen after any sign-in (a pasted key, GitHub, another provider):
 * Agents, which shows the setup card until something is connected. Matches the docs. */
export const SIGNED_IN_LANDING = "/app";

/**
 * Set when the session cookie holds a token the person pasted (their own key) rather
 * than one minted for this browser: signing out must then end the browser session
 * only, never revoke the key their CLI and app run on.
 */
export const KEPT_COOKIE = "agentfox_session_kept";

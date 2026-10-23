/**
 * Feature flags for the dashboard. A flag is off unless its environment
 * variable is exactly "1", so a missing or misspelled variable can never turn
 * something on by accident.
 *
 *   onboarding_on_signup   AGENTFOX_FLAG_ONBOARDING_ON_SIGNUP
 *     Send a new user to /app/onboarding after sign-in, on every login, until
 *     they finish or skip it. Off.
 */
export type Flag = "onboarding_on_signup";

const DEFAULTS: Record<Flag, boolean> = {
  onboarding_on_signup: false,
};

const ENV: Record<Flag, string> = {
  onboarding_on_signup: "AGENTFOX_FLAG_ONBOARDING_ON_SIGNUP",
};

export function flagOn(flag: Flag, env: Record<string, string | undefined> = process.env): boolean {
  const value = env[ENV[flag]];
  return value === undefined ? DEFAULTS[flag] : value === "1";
}

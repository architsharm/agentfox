import { redirect } from "next/navigation";

export const metadata = { title: "Connect your first agent" };

/**
 * Setup lives inside the dashboard: with no project yet (or one being added), every
 * page shows its own empty cards and the connection card (AppChrome → NewProjectPage).
 * This old address, and the sign-up redirect behind `onboarding_on_signup`, lead there.
 */
export default function OnboardingPage() {
  redirect("/app/map");
}

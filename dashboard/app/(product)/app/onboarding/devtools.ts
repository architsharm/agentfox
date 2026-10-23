import { safeApi } from "@/lib/product/api";

/** The "Onboarding dev" panel: always in development, and for internal users anywhere. */
export async function showDevTools(): Promise<boolean> {
  if (process.env.NODE_ENV === "development") return true;
  const me = await safeApi<{ email?: string } | null>("/api/me", null);
  return Boolean(me?.email?.toLowerCase().endsWith("@nometria.com"));
}

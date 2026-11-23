import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("codex");

export default function Page() {
  return <IntegrationPage slug="codex" />;
}

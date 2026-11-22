import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("mcp");

export default function Page() {
  return <IntegrationPage slug="mcp" />;
}

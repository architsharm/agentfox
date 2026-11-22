import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("claude-code");

export default function Page() {
  return <IntegrationPage slug="claude-code" />;
}

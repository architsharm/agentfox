import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("openai-agents-sdk");

export default function Page() {
  return <IntegrationPage slug="openai-agents-sdk" />;
}

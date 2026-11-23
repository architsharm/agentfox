import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("langgraph");

export default function Page() {
  return <IntegrationPage slug="langgraph" />;
}

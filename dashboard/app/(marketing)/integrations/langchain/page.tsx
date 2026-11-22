import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("langchain");

export default function Page() {
  return <IntegrationPage slug="langchain" />;
}

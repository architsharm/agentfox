import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("autogen");

export default function Page() {
  return <IntegrationPage slug="autogen" />;
}

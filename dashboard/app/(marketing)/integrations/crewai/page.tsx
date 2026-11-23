import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("crewai");

export default function Page() {
  return <IntegrationPage slug="crewai" />;
}

import { IntegrationPage, integrationMetadata } from "@/components/lp/integration";

export const metadata = integrationMetadata("llamaindex");

export default function Page() {
  return <IntegrationPage slug="llamaindex" />;
}

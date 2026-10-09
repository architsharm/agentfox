import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { Card, Empty, Header } from "@/components/kit";
import { ProtectWizard } from "@/components/product/agent/ProtectWizard";

export const metadata: Metadata = appPageMetadata("Protect agent");
export const dynamic = "force-dynamic";

export default async function Protect({ params }: { params: Promise<{ slug: string }> }) {
  const { slug: raw } = await params;
  const slug = decodeURIComponent(raw);
  const [state, tools] = await Promise.all([
    safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/protection`, null),
    safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/tools`, { tools: [] }),
  ]);
  return (
    <>
      <Header back={{ href: `/app/agents/${encodeURIComponent(slug)}`, label: slug }} title={`Protect ${slug}`} />
      <Card>
        {state ? (
          <ProtectWizard
            initial={state}
            tools={tools.tools || []}
          />
        ) : (
          <Empty>This agent could not be loaded.</Empty>
        )}
      </Card>
    </>
  );
}

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
  const [state, tools, posture] = await Promise.all([
    safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/protection`, null),
    safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/tools`, { tools: [] }),
    safeApi<any>(`/api/agents/${encodeURIComponent(slug)}/posture`, null),
  ]);
  const name = posture?.agent?.name || slug;
  return (
    <>
      <Header back={{ href: `/app/agents/${encodeURIComponent(slug)}`, label: name }} title={`Protect ${name}`} />
      <Card>
        {state ? (
          <ProtectWizard
            initial={{ ...state, name }}
            tools={tools.tools || []}
          />
        ) : (
          <Empty>This agent could not be loaded.</Empty>
        )}
      </Card>
    </>
  );
}

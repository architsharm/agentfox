import type { Metadata } from "next";
import { appPageMetadata } from "@/lib/site";
import { safeApi } from "@/lib/product/api";
import { Card, Empty, Header, ModePill } from "@/components/kit";
import { Act } from "@/components/kit/Act";
import { LadderEditor } from "@/components/product/policies/LadderEditor";

export const metadata: Metadata = appPageMetadata("Approval limit");
export const dynamic = "force-dynamic";

export default async function BusinessRulePage({ params }: { params: Promise<{ key: string }> }) {
  const { key: raw } = await params;
  const key = decodeURIComponent(raw);
  const [rule, tools] = await Promise.all([
    safeApi<any>(`/api/business/rules/${encodeURIComponent(key)}`, null),
    safeApi<any>("/api/tools", { tools: [] }),
  ]);
  if (!rule)
    return (
      <>
        <Header back={{ href: "/app/policies", label: "Policies" }} title={key} />
        <Card>
          <Empty>No such approval limit.</Empty>
        </Card>
      </>
    );
  return (
    <>
      <Header
        back={{ href: "/app/policies", label: "Policies" }}
        title={rule.name}
        meta={<ModePill mode={rule.enabled ? rule.mode : null} />}
        actions={
          <Act url={`/api/business/rules/${encodeURIComponent(key)}/mode`} body={{ mode: rule.mode === "enforce" ? "observe" : "enforce" }} className={rule.mode === "enforce" ? "k-btn" : "k-btn-primary"}>
            {rule.mode === "enforce" ? "Switch to watching" : "Start enforcing"}
          </Act>
        }
      />
      <Card>
        <LadderEditor rule={rule} tools={(tools.tools || []).map((t: any) => t.key).filter((k: string) => !k.startsWith("redteam."))} />
      </Card>
    </>
  );
}

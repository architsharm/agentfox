import Link from "next/link";
import { Card, href } from "@/components/kit";
import { safeApi } from "@/lib/product/api";
import { projectHref } from "@/lib/product/project";
import { agentRuleCounts } from "@/lib/product/libraries";

type Applied = { id: string; effect: string; mode: string; agents: { slug: string }[] };

/**
 * The rules applied to this agent, one click away: from its Controls and Access tabs,
 * which say what it may do but not which rules decide it. Opens Policies → Applied
 * rules filtered to the agent, where each rule opens its own page.
 */
export async function AgentRules({ slug, name }: { slug: string; name: string }) {
  const data = await safeApi<{ rules: Applied[] } | null>("/api/policies/applied", null);
  const counts = data ? agentRuleCounts(data.rules || [], slug) : null;
  return (
    <Card
      title="Rules on this agent"
      action={<Link href={href("/app/policies", { agent: slug })}>Applied rules</Link>}
    >
      <p className="k-muted" style={{ margin: 0 }}>
        {counts === null
          ? `The rules applied to ${name} are listed in Policies.`
          : counts.total === 0
            ? `No rule applies to ${name} yet.`
            : `${counts.total} ${counts.total === 1 ? "rule applies" : "rules apply"} to ${name}: ${counts.acting} ${counts.acting === 1 ? "acts" : "act"} now, ${counts.total - counts.acting} only ${counts.total - counts.acting === 1 ? "watches" : "watch"}.`}{" "}
        <Link href={projectHref(slug, "activity", { tab: "rules" })}>Which fired</Link>
      </p>
    </Card>
  );
}

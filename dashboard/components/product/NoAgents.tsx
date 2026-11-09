import Link from "next/link";
import { Empty } from "@/components/kit";
import { noAgents } from "@/lib/product/proposedSystems";

/** A page with no agents to show: pointing at the ones waiting under Proposed, when there are some. */
export function NoAgents({ proposed }: { proposed: number }) {
  const m = noAgents(proposed);
  return (
    <Empty action={<Link href={m.href} className="k-btn-primary">{m.action}</Link>}>{m.text}</Empty>
  );
}

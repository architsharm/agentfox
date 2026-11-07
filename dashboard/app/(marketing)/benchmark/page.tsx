import type { Metadata } from "next";

import { Benchmark } from "@/components/lp/Benchmark";
import { publicPageMetadata } from "@/lib/site";

export const dynamic = "force-dynamic";

export const metadata: Metadata = publicPageMetadata({
  title: "Benchmark",
  description:
    "AgentFox against LLM Guard, NeMo Guardrails, Prompt Guard 2 and others on public datasets, each at its default setting, including where it loses.",
  path: "/benchmark",
});

export default function Page() {
  return <Benchmark />;
}

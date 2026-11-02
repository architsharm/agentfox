import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Benchmark } from "@/components/lp/Benchmark";
import { VARIANTS, VARIANT_SLUGS, isVariant } from "@/lib/lp/variants";

export function generateStaticParams() {
  return VARIANT_SLUGS.map((variant) => ({ variant }));
}

export const metadata: Metadata = {
  title: "Benchmark",
  description: "AgentFox measured against LLM Guard, NeMo Guardrails, Prompt Guard 2 and others on the same data.",
  robots: { index: false },
};

export default async function Page({ params }: { params: Promise<{ variant: string }> }) {
  const { variant } = await params;
  if (!isVariant(variant)) notFound();
  return <Benchmark v={VARIANTS[variant]} />;
}

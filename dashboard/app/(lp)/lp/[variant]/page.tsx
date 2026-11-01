import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Landing } from "@/components/lp/Landing";
import { Production } from "@/components/lp/Production";
import { VARIANTS, VARIANT_SLUGS, isVariant } from "@/lib/lp/variants";

export function generateStaticParams() {
  return VARIANT_SLUGS.map((variant) => ({ variant }));
}

export async function generateMetadata({ params }: { params: Promise<{ variant: string }> }): Promise<Metadata> {
  const { variant } = await params;
  if (!isVariant(variant)) return {};
  const v = VARIANTS[variant];
  return { title: { absolute: `AgentFox: ${v.headline}` }, description: v.sub, robots: { index: false } };
}

export default async function Page({ params }: { params: Promise<{ variant: string }> }) {
  const { variant } = await params;
  if (!isVariant(variant)) notFound();
  if (variant === "production") return <Production />;
  return <Landing v={VARIANTS[variant]} />;
}

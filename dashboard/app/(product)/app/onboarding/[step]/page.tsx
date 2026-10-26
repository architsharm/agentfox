import { Suspense } from "react";
import { notFound } from "next/navigation";
import { OnboardingFlow } from "@/components/product/onboarding/OnboardingFlow";
import { isStep } from "@/lib/product/onboarding/steps";
import { showDevTools } from "../devtools";

export const metadata = { title: "Set up AgentFox" };

/** One onboarding step: /app/onboarding/{connect,structure,test,protect,retest}. */
export default async function OnboardingStepPage({ params }: { params: Promise<{ step: string }> }) {
  const { step } = await params;
  if (!isStep(step)) notFound();
  return (
    <Suspense>
      <OnboardingFlow step={step} devTools={await showDevTools()} />
    </Suspense>
  );
}

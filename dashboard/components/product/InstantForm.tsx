"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

/**
 * A GET filter form that applies as soon as a field changes: the chips beside it
 * apply on click, so a dropdown that waited for a "Show" or "Apply" button was the
 * one filter on the page that behaved differently. Empty fields are dropped from
 * the URL. Without JavaScript the `noscript` button still submits it as a plain form.
 */
export function InstantForm({
  action,
  className,
  submitLabel = "Show",
  children,
}: {
  action: string;
  className?: string;
  submitLabel?: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const go = (form: HTMLFormElement) => {
    const qs = new URLSearchParams();
    for (const [k, v] of new FormData(form).entries()) if (typeof v === "string" && v) qs.set(k, v);
    const s = qs.toString();
    router.push(s ? `${action}?${s}` : action, { scroll: false });
  };
  return (
    <form
      action={action}
      method="GET"
      className={className}
      onChange={(e) => go(e.currentTarget)}
      onSubmit={(e) => {
        e.preventDefault();
        go(e.currentTarget);
      }}
    >
      {children}
      <noscript>
        <button type="submit" className="k-btn">
          {submitLabel}
        </button>
      </noscript>
    </form>
  );
}

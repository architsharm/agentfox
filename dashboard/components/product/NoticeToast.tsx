"use client";

/**
 * The result of a form post, as a toast: plain words, gone after a few seconds,
 * and taken out of the URL so a reload does not show it again. An error stays
 * until it is dismissed.
 *
 * Render it unconditionally with the page's `review_notice` / `review_error`:
 *   <NoticeToast notice={sp.review_notice} error={sp.review_error} />
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { NOTICE_MS, noticeText, withoutNoticeParams } from "@/lib/product/notice";

export function NoticeToast({ notice, error }: { notice?: string | null; error?: string | null }) {
  const router = useRouter();
  // Held in state: once the params are stripped the page re-renders without them,
  // and the toast must outlive that.
  const [ok, setOk] = useState(() => noticeText(notice));
  const [bad, setBad] = useState(() => noticeText(error));

  useEffect(() => {
    if (notice) setOk(noticeText(notice));
    if (error) setBad(noticeText(error));
    if (!notice && !error) return;
    const clean = withoutNoticeParams(window.location.href);
    if (clean) router.replace(clean, { scroll: false });
  }, [notice, error, router]);

  useEffect(() => {
    if (!ok) return;
    const t = window.setTimeout(() => setOk(""), NOTICE_MS);
    return () => window.clearTimeout(t);
  }, [ok]);

  return (
    <div className="k-toasts">
      <div aria-live="polite" role="status">
        {ok && (
          <div className="k-toast">
            <span>{ok}</span>
            <button type="button" className="k-toast-x" aria-label="Dismiss" onClick={() => setOk("")}>
              ×
            </button>
          </div>
        )}
      </div>
      <div aria-live="assertive" role="alert">
        {bad && (
          <div className="k-toast k-toast-bad">
            <span>{bad}</span>
            <button type="button" className="k-toast-x" aria-label="Dismiss" onClick={() => setBad("")}>
              ×
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

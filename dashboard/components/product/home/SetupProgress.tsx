import Link from "next/link";

/**
 * One line at the top of Home while setup is unfinished: how far along, and the
 * single next step. It used to be a note at the very bottom of the page, under
 * the inventory — the one thing a new user needs most, placed where only a
 * returning user would scroll to.
 */
export function SetupProgress({ onboarding }: { onboarding: any }) {
  const { completed, total, next } = onboarding || {};
  if (!next || !total || completed >= total) return null;
  const pctDone = Math.round((completed / total) * 100);
  return (
    <div className="setup-strip">
      <div className="setup-strip-text">
        <span className="small muted">
          Setup {completed} of {total}
        </span>
        <span>
          <strong>Next:</strong> {next.title}
        </span>
      </div>
      <div className="setup-strip-bar" aria-hidden>
        <span style={{ width: `${pctDone}%` }} />
      </div>
      <Link href="/app/start" className="btn-primary">
        Continue setup →
      </Link>
    </div>
  );
}

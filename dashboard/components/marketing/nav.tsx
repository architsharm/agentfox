import Link from "next/link";
import { cookies } from "next/headers";
import { BrandLockup } from "@/components/marketing/brand";
import { SESSION_COOKIE } from "@/lib/product/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { ScrollReveal } from "@/components/marketing/motion";
import { NavMenu } from "@/components/marketing/menu";
import { FLAT, GROUPS, SECONDARY } from "@/lib/marketing/nav";

/**
 * The public navigation bar.
 *
 * Sticky and translucent rather than fixed-and-scroll-aware: the same effect without a
 * client component and a scroll listener on every public page. Links point only at
 * pages a signed-out visitor can actually open, because a nav row that bounces someone
 * to a sign-in wall is worse than no row.
 */

// Three in-page anchors and three real pages. The anchors are what a visitor who
// wants to know what this does actually needs; the pages are the two things that
// need no account plus the source.
/* Four of the nine pages were reachable only from the footer, and "Open source"
   was a mislabelled anchor into a pricing block on the home page. These are the
   pages, named the way they are titled. */
/* The header row is two dropdowns and one link, and the lists behind them
   live in lib/marketing/nav.ts along with the footer's, the sitemap's and llms.txt's.
   Four files used to keep their own copy of the same information
   architecture and the failure was always the same: a page was added and
   three of them never heard about it.

   Bare labels are the thing being fixed here. A menu that says "Discovery /
   Grants / Guardrails" makes a visitor open three pages to find out which
   one they wanted; each item carries a sentence, so the menu explains the
   product instead. */

export const REPO = "https://github.com/architsharm/agentfox";

/**
 * Reads the session cookie, which makes this async and keeps it a Server
 * Component. The reason is item one of a list of things wrong with the old
 * structure: a signed-in visitor who reached the public site had a "Sign in"
 * button in front of them and no way back to their own dashboard. It is a UX
 * branch, not a security one — the nav renders nothing that is not already
 * public either way.
 */
export async function MarketingNav() {
  const signedIn = Boolean((await cookies()).get(SESSION_COOKIE)?.value);
  return (
    <>
      {/* Mounted from the nav because it is the one component on every
          marketing page and there is no marketing-only layout to hang it
          from. It renders nothing; it turns on the scroll-reveal that the
          stylesheet keeps switched off until a script says otherwise, so a
          page with no JavaScript is fully visible rather than fully blank. */}
      <ScrollReveal />
    <header className="mk-nav">
      <div className="mk-wrap mk-nav-inner">
        <Link href="/" className="mk-brand" aria-label="AgentFox home">
          <BrandLockup size={26} />
        </Link>
        {/* Two dropdowns then two links, which is the shape of every header a
            visitor has already used. GitHub is not one of them: it leaves the
            site, and an outbound link sitting in a row of internal pages reads
            as a page until you click it. It belongs with the other actions on
            the right. */}
        <nav className="mk-nav-links" aria-label="Main">
          {GROUPS.map((group) => (
            <NavMenu key={group.label} group={group} />
          ))}
          {FLAT.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="mk-nav-cta">
          {/* The theme control belongs here, not only behind a sign-in: the public
              pages are the ones a visitor meets first, and the choice they make
              here is the one they keep after signing in — same key, same control. */}
          {/* The playground button is gone from here: the playground is now a
              link in the nav row itself, and one action offered twice in one
              52px bar is one action too many. */}
          <a
            className="mk-nav-gh"
            href={REPO}
            target="_blank"
            rel="noreferrer"
            aria-label="Source on GitHub"
          >
            <svg width="17" height="17" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
            </svg>
          </a>
          <ThemeToggle compact />
          <Link href="/playground" className="mk-btn mk-btn-primary mk-nav-try">
            Try it
          </Link>
          <Link
            href={signedIn ? "/app" : "/login"}
            className="mk-btn mk-btn-outline"
            style={{ padding: "8px 14px" }}
          >
            {signedIn ? "Dashboard" : "Sign in"}
          </Link>
        </div>
      </div>

      <details className="mk-menu">
        <summary aria-label="Menu">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </summary>
        {/* On a phone this is the entire navigation, so it carries every
            page rather than a curated few — grouped the same way the
            dropdowns are, so the two do not disagree about what the product
            is made of. */}
        <div className="mk-menu-panel">
          {GROUPS.map((group) =>
            group.sections.map((section, i) => (
              <div key={`${group.label}-${section.heading ?? i}`} className="mk-burger-group">
                <p>{section.heading ?? group.label}</p>
                {section.items.map((item) => (
                  <Link key={item.href} href={item.href}>
                    {item.label}
                  </Link>
                ))}
              </div>
            )),
          )}
          {[...FLAT, ...SECONDARY].map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
          <a href={REPO} target="_blank" rel="noreferrer">
            GitHub
          </a>
        </div>
      </details>
    </header>
    </>
  );
}

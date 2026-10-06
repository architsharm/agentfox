import Link from "next/link";

/**
 * Was a bare "Sign out" text link — no avatar, name, email, or workspace shown
 * anywhere, in a product that is clearly multi-user. `<details>` gives a real
 * dropdown with zero client JS, consistent with the rest of this shell.
 */
export function AccountMenu({
  email,
  workspace,
  role,
}: {
  email: string;
  workspace?: string | null;
  role?: string;
}) {
  const initial = (email || "?").trim()[0]?.toUpperCase() || "?";
  return (
    <details className="account-menu">
      <summary>
        <span className="avatar">{initial}</span>
        <span className="account-summary">
          <span className="account-email">{email}</span>
          {workspace && <span className="account-workspace">{workspace}</span>}
        </span>
      </summary>
      <div className="account-menu-body">
        <div className="account-menu-row">
          <span className="muted small">Signed in as</span>
          <span className="small mono">{email}</span>
        </div>
        {workspace && (
          <div className="account-menu-row">
            <span className="muted small">Workspace</span>
            <span className="small mono">{workspace}</span>
          </div>
        )}
        {role && (
          <div className="account-menu-row">
            <span className="muted small">Role</span>
            <span className="small">{role}</span>
          </div>
        )}
        <Link href="/app/start?tab=connect" className="account-menu-row" style={{ display: "block" }}>
          Connect a source
        </Link>
        <Link href="/app/start?tab=tokens" className="account-menu-row" style={{ display: "block" }}>
          API tokens
        </Link>
        {/* The way back out to the public site. A signed-in visitor had no route to
            it at all while the dashboard lived at "/": every URL that served the
            marketing page also served them the app. */}
        <Link href="/" className="account-menu-row" style={{ display: "block" }}>
          Public site
        </Link>
        <form action="/api/auth/logout" method="POST">
          <button type="submit" className="account-menu-signout">
            Sign out
          </button>
        </form>
      </div>
    </details>
  );
}

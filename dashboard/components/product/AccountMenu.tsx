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
  const label = workspaceLabel(workspace);
  const isId = Boolean(workspace && label !== workspace);
  return (
    <details className="account-menu">
      <summary>
        <span className="avatar">{initial}</span>
        <span className="account-summary">
          <span className="account-email">{email}</span>
          {label && <span className="account-workspace">{label}</span>}
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
            <span className="small">{label}</span>
          </div>
        )}
        {isId && (
          <div className="account-menu-row">
            <span className="muted small">Workspace ID</span>
            <span className="small mono">{workspace}</span>
          </div>
        )}
        {role && (
          <div className="account-menu-row">
            <span className="muted small">Role</span>
            <span className="small">{role}</span>
          </div>
        )}
        {/* Connections and API keys live in Settings; the menu is who you are and the way out. */}
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

/**
 * The workspace as a name. /api/me answers with the GitHub login when GitHub is
 * connected and otherwise the raw tenant id ("org_default"), which is an internal
 * key, not something a person named. The id stays in the menu for support.
 */
export function workspaceLabel(workspace?: string | null): string {
  if (!workspace) return "";
  if (workspace === "org_default") return "Default workspace";
  const m = /^org_(.+)$/.exec(workspace);
  if (!m) return workspace;
  const words = m[1].replace(/[_-]+/g, " ").trim();
  return words ? `${words[0].toUpperCase()}${words.slice(1)} workspace` : workspace;
}

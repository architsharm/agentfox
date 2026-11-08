/**
 * Sign-in providers besides GitHub: Google and Microsoft, both plain OAuth 2.0 with
 * OpenID userinfo. GitHub keeps its own routes (api/auth/github/*) because its grant
 * also connects repositories; these only answer "who is this".
 *
 * A provider is offered on /login only when its client id and secret are set, so a
 * deployment that has not registered an app with Google or Microsoft shows nothing
 * it cannot finish.
 */

export type OAuthProvider = {
  id: "google" | "microsoft";
  label: string;
  authorizeUrl: string;
  tokenUrl: string;
  userinfoUrl: string;
  scope: string;
  clientIdEnv: string;
  clientSecretEnv: string;
};

export const OAUTH_PROVIDERS: Record<OAuthProvider["id"], OAuthProvider> = {
  google: {
    id: "google",
    label: "Google",
    authorizeUrl: "https://accounts.google.com/o/oauth2/v2/auth",
    tokenUrl: "https://oauth2.googleapis.com/token",
    userinfoUrl: "https://openidconnect.googleapis.com/v1/userinfo",
    scope: "openid email profile",
    clientIdEnv: "GOOGLE_CLIENT_ID",
    clientSecretEnv: "GOOGLE_CLIENT_SECRET",
  },
  microsoft: {
    id: "microsoft",
    label: "Microsoft",
    // `common`: work, school and personal Microsoft accounts.
    authorizeUrl: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    tokenUrl: "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    userinfoUrl: "https://graph.microsoft.com/oidc/userinfo",
    scope: "openid email profile",
    clientIdEnv: "MICROSOFT_CLIENT_ID",
    clientSecretEnv: "MICROSOFT_CLIENT_SECRET",
  },
};

export function oauthProvider(id: string): OAuthProvider | null {
  return Object.prototype.hasOwnProperty.call(OAUTH_PROVIDERS, id)
    ? OAUTH_PROVIDERS[id as OAuthProvider["id"]]
    : null;
}

export function oauthCredentials(p: OAuthProvider): { clientId: string; clientSecret: string } | null {
  const clientId = process.env[p.clientIdEnv];
  const clientSecret = process.env[p.clientSecretEnv];
  return clientId && clientSecret ? { clientId, clientSecret } : null;
}

/** Which sign-in buttons this deployment can finish. GitHub needs only its client id
 *  to start; the callback reports a missing secret itself. */
export function configuredSignIns(): { github: boolean; google: boolean; microsoft: boolean } {
  return {
    github: Boolean(process.env.GITHUB_CLIENT_ID),
    google: Boolean(oauthCredentials(OAUTH_PROVIDERS.google)),
    microsoft: Boolean(oauthCredentials(OAUTH_PROVIDERS.microsoft)),
  };
}

export const oauthStateCookie = (id: OAuthProvider["id"]) => `${id}_oauth_state`;
export const oauthCallbackPath = (id: OAuthProvider["id"]) => `/api/auth/${id}/callback`;

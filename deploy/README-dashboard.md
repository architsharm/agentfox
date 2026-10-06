# Deploying the control-plane UI so strangers can sign up

The API is already live on Vercel against Neon. This deploys the UI that people
actually sign in to, on Render (or Fly). Nothing here needs its own database: the UI
is a pure client of the API, and the API owns the only Postgres connection.

What a visitor gets once this is up: sign in with GitHub, which creates their own
organisation, stores their GitHub grant, lists their repositories, scans one for
ungoverned agent code, and issues them an API token their agents authenticate with.

> **Status, 2026-09-20.** The UI is already live on Vercel at
> `https://guardrails-nometria.vercel.app`, with GitHub sign-in, the repo list and
> the repo scan all working, and the playground fixed (see step 4 — the origin was not
> allowed, so every visitor saw "Failed to fetch"). A second copy now runs on Render at
> `https://nometria-dashboard.onrender.com` as a backup; its sign-in returns 503 until the
> three secrets below are set on it, and its callback URL is added to the OAuth app.
> The Neon migration in step 1b has been run: the database is at revision `d5e2a9c14f03`
> and the Findings page works again. `scripts/deploy_smoke.py` checks all of this against a
> live deployment in one command.

## 1. Secrets the two deployments must share

Two values must be byte-identical on the API (Vercel) and the UI (Render or Fly),
and one exists only on the API.

| Value | Where | What breaks without it |
|---|---|---|
| `NOMETRIA_SERVICE_AUTH_SECRET` | both | Sign-in fails at the provisioning step. Outside development the gateway **refuses to start** while it is unset or the published `dev-insecure-service-secret`, which would let anyone who reads the source mint owner tokens. Must be byte-identical on both. |
| `NOMETRIA_TOKEN_ENCRYPTION_KEY` | API only | Connecting GitHub returns 503. It fails closed rather than storing the access token unencrypted. |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | UI only | Sign-in returns 503, or the callback fails. |

Generate the two you control:

```bash
python3 -c "import secrets;print('service secret:', secrets.token_urlsafe(48))"
```

```bash
python3 -c "from cryptography.fernet import Fernet;print('encryption key:', Fernet.generate_key().decode())"
```

Check what the API already has, without printing values:

```bash
vercel env ls production
```

Set anything missing on the API, then redeploy it so the new environment is picked up:

```bash
vercel env add NOMETRIA_SERVICE_AUTH_SECRET production
```

```bash
vercel env add NOMETRIA_TOKEN_ENCRYPTION_KEY production
```

## 1b. Migrate Neon first — the API cannot do it itself

The serverless deployment ships a prebuilt wheel that does not bundle `migrations/`, so
`alembic upgrade head` never runs there. The API on Vercel is already running this week's
code, which expects tables and columns that only a migration creates: `change_proposals`,
`job_schedules`, and the `fingerprint`, `occurrences` and `last_seen_at` columns on
findings. Until Neon is migrated, any request that records a finding or lists proposals
fails, and sign-in is not the thing that will look broken.

The database is at revision `b3f8e29a71c4`, one behind. Note that `change_proposals` and
`job_schedules` already exist, created by `init_db()`'s create_all, so a plain
`alembic upgrade head` fails on CREATE TABLE. Use `deploy/neon-catchup-d5e2a9c14f03.sql`,
which is idempotent, in the Neon SQL editor (Vercel → Storage → guardrails-db → Query,
read-only off). Or, from a checkout against the Neon URL:

```bash
NOMETRIA_DATABASE_URL='<neon url>' uv run alembic upgrade head
```

Then confirm the head revision matches the newest file in `migrations/versions/`:

```bash
NOMETRIA_DATABASE_URL='<neon url>' uv run alembic current
```

## 2. Deploy the UI on Render

1. Render → New → Blueprint → pick this repository. It reads `deploy/render.yaml`.
2. Render prompts for the three secret values marked `sync: false`. Paste them there,
   never into a file in the repository.
3. First build takes a few minutes. It builds `deploy/Dockerfile.dashboard` with
   `./dashboard` as the build context. The blueprint sets `HOSTNAME=0.0.0.0`: without it
   Next binds to the pod name Render injects, and every request 502s while the logs show a
   clean start.
4. Note the hostname it gives you, for example `nometria-dashboard.onrender.com`.

The starter plan matters here: on the free plan the service sleeps, and a cold start
lands a Reddit visitor on a spinner for tens of seconds.

## 3. Point GitHub at the new hostname

In the GitHub OAuth app (Settings → Developer settings → OAuth Apps):

- **Homepage URL:** `https://<your-host>`
- **Authorization callback URL:** `https://<your-host>/api/auth/github/callback`

The callback must match exactly, including the scheme and the path. A mismatch is
the single most common cause of a failed sign-in.

The app requests `repo read:user user:email`. `repo` is what lets the scan download a
private repository. Say so on the login page if you expect security-minded visitors,
because a broad `repo` scope on an unknown startup is a common objection.

## 4. Let the browser reach the playground

The playground page calls the API directly from the visitor's browser, so the API has
to allow that origin:

```bash
vercel env add NOMETRIA_PLAYGROUND_CORS_ORIGIN production
```

The value is comma-separated, so list every host that serves the playground, with no
trailing slashes, then redeploy the API:

```
https://guardrails-nometria.vercel.app,https://guardrails-dashboard-eight.vercel.app,https://nometria-dashboard.onrender.com
```

Appending matters. While this setting took a single origin, adding the standby silently
disabled the primary's playground, and the only symptom was "Failed to fetch" in the
browser while curl against the API looked healthy.

## 5. Verify the whole path

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<your-host>/login
```

Expect 200. Then in a private browser window: sign in with GitHub, land on the
Connect tab, pick a repository, run the scan, and open the API tokens tab to create a
token. If sign-in fails, the error appears on the login page itself, and the useful
detail is in the Render logs for that request.

Check that a new account really is its own tenant: sign in from a second GitHub
account and confirm it sees no agents or findings from the first.

## What is still open after this

- **No invite flow.** One GitHub identity means one new organisation, and its first
  user is the owner. Two colleagues signing up separately get separate tenants that
  cannot see each other's work.
- **No sign-up rate limit.** Anyone with a GitHub account can create a tenant, and
  each scan downloads and unpacks a repository on the API.
- **The proxy spends your provider budget.** Traffic through `/v1/chat/completions`
  and `/v1/messages` calls the model with the server's own keys. The
  `/v1/guard/*` endpoints do not, because the caller keeps making its own model calls.

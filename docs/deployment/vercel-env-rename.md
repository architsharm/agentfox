# Renaming the Vercel environment from `NOMETRIA_*` to `AGENTFOX_*`

The product reads `AGENTFOX_*` first and the pre-rename `NOMETRIA_*` second. That
fallback (stage A, branch `claude/agentfox-rename`) is what keeps production up while
the variables below are renamed by hand. Stage B (branch `claude/agentfox-rename-final`)
deletes the fallback, so **do not merge stage B until every project below shows no
legacy variables in use.**

Nothing here needs a secret value to be read out or pasted anywhere but the Vercel
project it already lives in. Where a step says "same value", copy it inside Vercel.

## Order

1. Merge stage A to `main` (with its rebuilt `api/vendor` and
   `demo/redteam-live-lang/vendor` wheels) and let all three projects redeploy.
   Nothing changes yet: every `NOMETRIA_*` variable keeps working.
2. For each project below, **add** each `AGENTFOX_*` variable with the same value as its
   `NOMETRIA_*` twin, in the same environments. Do not delete anything yet.
3. **Redeploy** each project (Deployments → latest → Redeploy). Vercel only applies
   environment changes to new deployments.
4. **Confirm nothing legacy is in use:**
   - Runtime logs (Deployments → the new deployment → Logs, after one request so the
     function has started): there must be no line starting
     `Deprecated pre-rename (Nometria) settings in use:` (gateway, demo) and no
     `NOMETRIA_… is deprecated` (dashboard). If there is, it names the variable.
   - Or locally, against a checkout with the same environment: `agentfox doctor`
     shows `legacy names … ok`. Its `warn` line separates names *in use* from names
     *set but not read* (shadowed by a new twin, or never read, like the Neon
     integration's own variables).
   - Names only, no values: `vercel env ls production | grep NOMETRIA_` and
     `vercel env ls preview | grep NOMETRIA_`.
5. **Delete** the old `NOMETRIA_*` variables (and switch the Neon integration prefix,
   below), redeploy, and check step 4 again — now `vercel env ls` should list none.
6. **Merge stage B.**

Rolling back at any point before step 6 is just re-adding the old variable: stage A
reads it again on the next deploy.

### Values that must be copied, never regenerated

- `TOKEN_ENCRYPTION_KEY`: a new value makes every stored GitHub access token and source
  credential undecryptable.
- `AUDIT_SIGNING_KEY`: a new value means checkpoints signed before the change no longer
  verify.
- `SERVICE_AUTH_SECRET`: must be byte-identical on `guardrails-api` and
  `guardrails-dashboard` (and the Render dashboard, if it is still running). A new value
  is acceptable only if it is changed on all of them in the same step.

If one of these was created as a **Sensitive** variable, Vercel will not show its value.
Use Edit on the existing variable to change only its *name* to the `AGENTFOX_*` one, if
your Vercel UI allows that, and redeploy (stage A is already reading `AGENTFOX_*` first,
so this is safe in one step). If neither copying nor renaming is possible, leave the old
variable in place and do not merge stage B until you have the value from wherever it was
generated.

## guardrails-api (Root Directory `api/`)

The gateway reads every setting as `AGENTFOX_<NAME>` (`src/agentfox/core/config.py`,
`Settings`), so the rule is mechanical: **every `NOMETRIA_<NAME>` becomes
`AGENTFOX_<NAME>`**, except the Neon integration's own variables (next section). The
ones this project is known to set:

| Add | Same value as | Environments |
|---|---|---|
| `AGENTFOX_SERVICE_AUTH_SECRET` | `NOMETRIA_SERVICE_AUTH_SECRET` | Production, Preview (wherever the old one is) |
| `AGENTFOX_AUDIT_SIGNING_KEY` | `NOMETRIA_AUDIT_SIGNING_KEY` | Production, Preview |
| `AGENTFOX_TOKEN_ENCRYPTION_KEY` | `NOMETRIA_TOKEN_ENCRYPTION_KEY` | Production, Preview |
| `AGENTFOX_DATABASE_URL` | `NOMETRIA_DATABASE_URL` | Production, Preview |
| `AGENTFOX_ENVIRONMENT` | `NOMETRIA_ENVIRONMENT` | Production, Preview |
| `AGENTFOX_AUTH_MODE` | `NOMETRIA_AUTH_MODE` | Production, Preview |
| `AGENTFOX_EVIDENCE_DIR` | `NOMETRIA_EVIDENCE_DIR` | Production, Preview |
| `AGENTFOX_CRON_SECRET` | `NOMETRIA_CRON_SECRET` | Production (Vercel Cron only runs there) |
| `AGENTFOX_PLAYGROUND_CORS_ORIGIN` | `NOMETRIA_PLAYGROUND_CORS_ORIGIN` | Production, Preview |

"Environments" means: give the new variable exactly the environments the old one has
(the Environments column of `vercel env ls`, or the project's Settings → Environment
Variables page). Production is required for every row; add Preview wherever the old one is in
Preview, or preview deployments lose the setting at stage B.

Any other `NOMETRIA_<NAME>` the list shows (for example `NOMETRIA_ALLOW_EGRESS`,
`NOMETRIA_SHOWCASE_ENABLED`, `NOMETRIA_GITHUB_WEBHOOK_SECRET`,
`NOMETRIA_ANTHROPIC_API_KEY`, `NOMETRIA_DEFAULT_PROVIDER`) follows the same rule.
`CRON_SECRET` (no prefix) is Vercel's own and stays as it is.

### The Neon integration (`NOMETRIA_DATABASE_*`)

The Neon integration was connected with the custom prefix `NOMETRIA_DATABASE`, so it
generates `NOMETRIA_DATABASE_DATABASE_URL`, `NOMETRIA_DATABASE_POSTGRES_URL`,
`NOMETRIA_DATABASE_PGHOST` and the rest (prefix + Neon's own names).

**The gateway reads none of them.** The only database variable `core/config.py` reads is
`<PREFIX>DATABASE_URL`, i.e. `AGENTFOX_DATABASE_URL` (falling back to
`NOMETRIA_DATABASE_URL`), and it must carry the `postgresql+psycopg://` scheme, since the
deployment installs psycopg 3. That is the hand-set variable in the table above; it is not
one the integration creates. So for this project:

- Required: `AGENTFOX_DATABASE_URL`, same value as `NOMETRIA_DATABASE_URL`.
- Optional, for a clean `vercel env ls`: change the integration's prefix. Vercel →
  Storage → the database → Projects → `guardrails-api` → disconnect, then Connect Project
  again with the custom prefix `AGENTFOX_DATABASE` and the same environments. This only
  rewrites the generated variables (`AGENTFOX_DATABASE_POSTGRES_URL`, …); it does not
  touch the database or its credentials, and the gateway does not read them either way.
  Note the new prefix makes Neon generate `AGENTFOX_DATABASE_DATABASE_URL`, not
  `AGENTFOX_DATABASE_URL`, so it does not replace the hand-set variable.
- Leaving the integration on the old prefix is harmless to the gateway: those names are
  reported by `agentfox doctor` as "set but not read" and never in the startup warning.
  Stage B does not depend on them.

## guardrails-dashboard

The dashboard reads (`dashboard/lib/env.ts`, `AGENTFOX_<NAME>` then `NOMETRIA_<NAME>`):

| Add | Same value as | Environments | Read by |
|---|---|---|---|
| `AGENTFOX_API_URL` | `NOMETRIA_API_URL` | Production, Preview | every server-side call to the gateway |
| `AGENTFOX_SERVICE_AUTH_SECRET` | `NOMETRIA_SERVICE_AUTH_SECRET` | Production, Preview | GitHub sign-in; must equal the API's |
| `AGENTFOX_PLAYGROUND_API_URL` | `NOMETRIA_PLAYGROUND_API_URL` | if set | the public playground page |
| `AGENTFOX_SITE_URL` | `NOMETRIA_SITE_URL` | if set | canonical URL in page metadata |
| `AGENTFOX_SELF_HOSTED` | `NOMETRIA_SELF_HOSTED` | if set | "run `agentfox serve`" hints |
| `AGENTFOX_API_TOKEN` | `NOMETRIA_API_TOKEN` | if set | static token for server-side reads |
| `AGENTFOX_USER` | `NOMETRIA_USER` | if set | development identity header only |

`GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` have no prefix and stay as they are.

After stage A the dashboard sends `X-AgentFox-User` and `X-AgentFox-Service-Secret`. The
gateway in the same commit accepts both spellings, so deploy order between the two
projects does not matter as long as both run stage A or later.

If the Render dashboard (`nometria-dashboard`, `deploy/render.yaml`) is still running, it
needs the same three: `AGENTFOX_API_URL`, `AGENTFOX_SERVICE_AUTH_SECRET` (same value as
the API's), and, as before, `GITHUB_CLIENT_*`. Render secrets are `sync: false`, so add
them in the Render dashboard; a blueprint sync does not.

## guardrails-redteam-lang (Root Directory `demo/redteam-live-lang/`)

This project runs the same `agentfox` package (from its own vendored wheel), so the
gateway rule applies: every `NOMETRIA_<NAME>` becomes `AGENTFOX_<NAME>` with the same
value and environments. Per `demo/redteam-live-lang/README.md` it sets the service auth
secret, token encryption key, audit signing key, evidence dir, environment and auth mode:

| Add | Same value as |
|---|---|
| `AGENTFOX_SERVICE_AUTH_SECRET` | `NOMETRIA_SERVICE_AUTH_SECRET` |
| `AGENTFOX_TOKEN_ENCRYPTION_KEY` | `NOMETRIA_TOKEN_ENCRYPTION_KEY` |
| `AGENTFOX_AUDIT_SIGNING_KEY` | `NOMETRIA_AUDIT_SIGNING_KEY` |
| `AGENTFOX_EVIDENCE_DIR` | `NOMETRIA_EVIDENCE_DIR` |
| `AGENTFOX_ENVIRONMENT` | `NOMETRIA_ENVIRONMENT` |
| `AGENTFOX_AUTH_MODE` | `NOMETRIA_AUTH_MODE` |
| `AGENTFOX_DEMO_MODEL` | `NOMETRIA_DEMO_MODEL` (only if set) |

These are this project's own values, not the API's. `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` have no prefix and stay.

**The Neon integration here *is* read.** `demo/kit/env.py` derives the database URL from
the integration's `<prefix>_POSTGRES_URL` (stage A looks for `AGENTFOX_DATABASE_POSTGRES_URL`,
`AGENTFOX_DATABASE_DATABASE_URL`, then the `NOMETRIA_DATABASE_*` pair), so for this project
the prefix change is required before stage B: Vercel → Storage → the demo's database →
Projects → `guardrails-redteam-lang` → disconnect, then Connect Project with the custom
prefix `AGENTFOX_DATABASE`, same environments, and redeploy. Do not create an
`AGENTFOX_DATABASE_URL` by hand here: if one is set, the kit uses it as-is, and it would
need the `postgresql+psycopg://` scheme.

## GitHub Actions secrets

`.github/workflows/monitors.yml` calls the job runner every 30 minutes with two
repository secrets (Settings → Secrets and variables → Actions). They already use the
new names; check they exist (`gh secret list`):

| Secret | Value |
|---|---|
| `AGENTFOX_API_URL` | the API's base URL, e.g. `https://guardrails-api.vercel.app` |
| `AGENTFOX_CRON_SECRET` | the same value as the API's `AGENTFOX_CRON_SECRET` (or Vercel's `CRON_SECRET`) |

Without them the workflow logs "not set; nothing to run" and exits successfully, so a
missing secret is silent: look at a recent run of *Run monitors*. If either still exists
under a `NOMETRIA_` name, add it under the new name and delete the old one; nothing reads
it. No other workflow uses a project secret (`ci`, `release` and `publish-images` use only
`GITHUB_TOKEN`).

## Checklist

- [ ] Stage A merged; three projects redeployed from it.
- [ ] guardrails-api: `AGENTFOX_*` added for every `NOMETRIA_*` (table above, plus any
      extra the list shows), same environments, `TOKEN_ENCRYPTION_KEY` and
      `AUDIT_SIGNING_KEY` copied, not regenerated.
- [ ] guardrails-dashboard: `AGENTFOX_API_URL`, `AGENTFOX_SERVICE_AUTH_SECRET` (same as the
      API's) and any optional ones set.
- [ ] guardrails-redteam-lang: `AGENTFOX_*` added; Neon integration reconnected with prefix
      `AGENTFOX_DATABASE`.
- [ ] Render dashboard (if running): `AGENTFOX_API_URL`, `AGENTFOX_SERVICE_AUTH_SECRET`.
- [ ] All redeployed; no `Deprecated pre-rename` / `is deprecated` lines in runtime logs.
- [ ] Old `NOMETRIA_*` variables deleted (optionally the API's Neon prefix changed);
      redeployed; `vercel env ls production | grep NOMETRIA_` and the same for preview
      print nothing (or only the API's untouched Neon variables, if you kept them).
- [ ] GitHub Actions: `AGENTFOX_API_URL` and `AGENTFOX_CRON_SECRET` present; last *Run
      monitors* run actually called the runner.
- [ ] Merge stage B.

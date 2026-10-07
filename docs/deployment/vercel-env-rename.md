# Moving production from `NOMETRIA_*` to `AGENTFOX_*`

The hosted deployment still holds its secrets only under the pre-rename `NOMETRIA_*`
names. They are Sensitive variables in Vercel, so nobody can read or rename them. This
procedure replaces them with **fresh** values under the `AGENTFOX_*` names. The data
the old keys protect moves to the new keys while both are set. Then the old names are
deleted, and rename stage B (`claude/agentfox-rename-final`) can merge.

What makes this work:

- The release on `claude/key-rotation` reads `AGENTFOX_*` first and `NOMETRIA_*` second.
  It also contains a one-time bridge in `core/config.py`. When `AGENTFOX_TOKEN_ENCRYPTION_KEY`
  and `NOMETRIA_TOKEN_ENCRYPTION_KEY` are both set and differ, the `NOMETRIA_` value
  becomes the *previous* encryption key. `AUDIT_SIGNING_KEY` works the same way. Old
  data stays readable, and new data uses the new key.
- The job runner then rotates by itself. It re-encrypts every stored secret and re-signs
  the audit checkpoints with the new keys
  ([key-rotation.md](key-rotation.md) explains how).
- `/api/version` reports `key_rotation` states (never keys), so you can confirm from
  outside that nothing still needs an old key before you delete it.
- `SERVICE_AUTH_SECRET` and `CRON_SECRET` protect no stored data. The new values simply
  take precedence.

Projects involved:

| Project | What | URL |
|---|---|---|
| `guardrails-api` (Vercel, Root Directory `api/`) | the gateway | `https://guardrails-api.vercel.app` |
| `guardrails-dashboard` (Vercel) | the dashboard | `https://guardrails-nometria.vercel.app` |
| `guardrails-redteam-lang` (Vercel, Root Directory `demo/redteam-live-lang/`) | the red-team demo, with its own database | |
| GitHub `architsharm/agentfox` | `.github/workflows/monitors.yml` calls the job runner every 30 minutes | |

Do the steps in order. Nothing is deleted until step 8, and up to then a rollback means
removing the `AGENTFOX_*` variable you added and redeploying.

## 1. Generate the values

```bash
TOKEN_KEY=$(openssl rand -base64 32 | tr '+/' '-_')   # AGENTFOX_TOKEN_ENCRYPTION_KEY
AUDIT_KEY=$(openssl rand -hex 32)                     # AGENTFOX_AUDIT_SIGNING_KEY
SERVICE_SECRET=$(openssl rand -hex 32)                # AGENTFOX_SERVICE_AUTH_SECRET
CRON_KEY=$(openssl rand -hex 32)                      # AGENTFOX_CRON_SECRET
```

Three of these are `openssl rand -hex 32`. The encryption key is the exception: it must
be a Fernet key (32 bytes, url-safe base64, 44 characters ending in `=`). A 64-character
hex string is rejected by `cryptography`, and every encrypt and decrypt would fail. If
that happens, `/api/version` shows `"token_encryption": "misconfigured"` and
`agentfox doctor` names the variable. Keep all four values in your password manager:
the signing key in particular is needed to verify evidence packages later.

Generate a **separate** set for the red-team demo in step 4. It has its own database and
must not share keys with the gateway.

## 2. guardrails-api

Vercel → `guardrails-api` → Settings → Environment Variables. Add each variable below
for **Production**, and also for **Preview** if the old `NOMETRIA_` twin is set for
Preview. Mark the secrets Sensitive. Leave every `NOMETRIA_*` variable in place.

| Variable | Value | Sensitive |
|---|---|---|
| `AGENTFOX_TOKEN_ENCRYPTION_KEY` | `$TOKEN_KEY` | yes |
| `AGENTFOX_AUDIT_SIGNING_KEY` | `$AUDIT_KEY` | yes |
| `AGENTFOX_SERVICE_AUTH_SECRET` | `$SERVICE_SECRET` (the same value on `guardrails-dashboard`, step 4) | yes |
| `AGENTFOX_CRON_SECRET` | `$CRON_KEY` | yes |
| `AGENTFOX_DATABASE_URL` | Neon console → the `guardrails-api` database → Connect → connection string, with `postgresql://` replaced by `postgresql+psycopg://`. Keep the query string (`?sslmode=require…`). | yes |
| `AGENTFOX_ENVIRONMENT` | `production` | no |
| `AGENTFOX_AUTH_MODE` | `token` | no |
| `AGENTFOX_EVIDENCE_DIR` | `/tmp/agentfox-evidence` | no |

Also check Vercel's own **`CRON_SECRET`** (no prefix). Vercel Cron sends it as
`Authorization: Bearer …`, and the gateway accepts it as well as `AGENTFOX_CRON_SECRET`.
If it exists, leave it. If it does not, add it with the value `$CRON_KEY`; without it,
Vercel's own cron, and its Run button in step 6, gets a 401.

Copy any other `NOMETRIA_<NAME>` the project has to `AGENTFOX_<NAME>`, for example
`PLAYGROUND_CORS_ORIGIN`, `ALLOW_EGRESS`, `SHOWCASE_ENABLED`, `DEFAULT_PROVIDER`. Plain
values can be revealed in the UI. If one of them is Sensitive (for example
`GITHUB_WEBHOOK_SECRET` or a model API key), issue a new value at its source and set
that. For the GitHub webhook secret, the source is the repository's webhook settings.

From the CLI instead (production only; it prompts or reads the value from stdin):

```bash
mkdir -p ~/tmp/vercel-api && cd ~/tmp/vercel-api && vercel link --yes --project guardrails-api
printf '%s' "$TOKEN_KEY"      | vercel env add AGENTFOX_TOKEN_ENCRYPTION_KEY production
printf '%s' "$AUDIT_KEY"      | vercel env add AGENTFOX_AUDIT_SIGNING_KEY production
printf '%s' "$SERVICE_SECRET" | vercel env add AGENTFOX_SERVICE_AUTH_SECRET production
printf '%s' "$CRON_KEY"       | vercel env add AGENTFOX_CRON_SECRET production
printf '%s' 'postgresql+psycopg://…?sslmode=require' | vercel env add AGENTFOX_DATABASE_URL production
printf '%s' production              | vercel env add AGENTFOX_ENVIRONMENT production
printf '%s' token                   | vercel env add AGENTFOX_AUTH_MODE production
printf '%s' /tmp/agentfox-evidence  | vercel env add AGENTFOX_EVIDENCE_DIR production
vercel env ls production            # names only; nothing prints a value
```

### Why these plain values

- **`AGENTFOX_ENVIRONMENT=production`.** Production refuses the published development
  secrets (`assert_production_secrets` in `core/config.py` runs in `create_app`), and
  that check only applies outside `development`/`dev`/`test`/`testing`/`local`. The live
  gateway does not reveal the exact name. Its 401 comes from the explicit-`auth_mode`
  branch, which prints the mode and not the environment. In the code, any non-development
  name behaves identically: `is_development` and `header_identity_allowed` only test
  membership in that set. So `production` is correct whatever the old value was. To see
  the old value, open `NOMETRIA_ENVIRONMENT` in the same settings page; it is a plain
  variable unless someone marked it Sensitive.
- **`AGENTFOX_AUTH_MODE=token`.** Observed directly. An unauthenticated
  `curl https://guardrails-api.vercel.app/api/agents` returns 401 with *"this deployment
  sets auth_mode='token', so API tokens are required and the X-AgentFox-User header is
  not accepted"*. That sentence is only produced when `auth_mode` is set explicitly to
  that value (`platform/identity/operators.py`, `_why_header_refused`).
- **`AGENTFOX_EVIDENCE_DIR=/tmp/agentfox-evidence`.** A Vercel function can only write
  under `/tmp`. Without this setting, an installed wheel writes evidence under
  `~/.agentfox/var/evidence` (`state_root()` in `core/config.py`), which is not writable
  there. `/tmp` is per instance and temporary, which is acceptable: a package is built
  and downloaded in the same flow. The live value cannot be seen from outside. To find
  the directory production actually used, run this in the Neon SQL editor:
  `select path from evidence_packages order by built_at desc limit 3;`. If it shows a
  different `/tmp/…` directory, use that.

## 3. GitHub Actions secret

```bash
gh secret set AGENTFOX_CRON_SECRET --repo architsharm/agentfox --body "$CRON_KEY"
gh secret list --repo architsharm/agentfox     # AGENTFOX_API_URL must be there too
```

If `AGENTFOX_API_URL` is missing:
`gh secret set AGENTFOX_API_URL --repo architsharm/agentfox --body https://guardrails-api.vercel.app`.
Delete any leftover `NOMETRIA_*` secret, which nothing reads:
`gh secret delete NOMETRIA_CRON_SECRET --repo architsharm/agentfox`.

## 4. The dashboard and the red-team demo

### guardrails-dashboard

| Variable | Value |
|---|---|
| `AGENTFOX_API_URL` | `https://guardrails-api.vercel.app` |
| `AGENTFOX_SERVICE_AUTH_SECRET` | `$SERVICE_SECRET`, the same value as the API |
| `AGENTFOX_API_TOKEN` | a newly issued token (below) |
| any other `NOMETRIA_<NAME>` (`PLAYGROUND_API_URL`, `SITE_URL`, `SELF_HOSTED`, `USER`) | the same value, as `AGENTFOX_<NAME>` |

`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` have no prefix and stay as they are.

Issue the token from a checkout, against the production database. Export the **new**
signing key too. The command writes an audit entry, and if that entry lands on a
checkpoint, it must be signed with the production key and not the development default:

```bash
export AGENTFOX_DATABASE_URL='postgresql+psycopg://…?sslmode=require'   # as in step 2
export AGENTFOX_AUDIT_SIGNING_KEY="$AUDIT_KEY"
uv run agentfox admin users list                       # pick an owner's email
uv run agentfox admin auth issue <owner-email> --name dashboard --days 365
```

The token is printed once (`nom_api_…`). Paste it into `AGENTFOX_API_TOKEN` as a
Sensitive variable. You can revoke the old one later with
`uv run agentfox admin auth tokens` and `uv run agentfox admin auth revoke <id>`.

If the Render dashboard (`nometria-dashboard`) is ever brought back, it needs the same
three variables.

### guardrails-redteam-lang

Generate a separate set (step 1) and add:

| Variable | Value |
|---|---|
| `AGENTFOX_TOKEN_ENCRYPTION_KEY` | a new Fernet key (`openssl rand -base64 32 \| tr '+/' '-_'`) |
| `AGENTFOX_AUDIT_SIGNING_KEY` | `openssl rand -hex 32` |
| `AGENTFOX_SERVICE_AUTH_SECRET` | `openssl rand -hex 32` |
| `AGENTFOX_ENVIRONMENT` | `production`, or the revealed value of `NOMETRIA_ENVIRONMENT` |
| `AGENTFOX_AUTH_MODE` | `token`, or the revealed value of `NOMETRIA_AUTH_MODE` |
| `AGENTFOX_EVIDENCE_DIR` | `/tmp/agentfox-evidence`, or the revealed value of `NOMETRIA_EVIDENCE_DIR` |
| `AGENTFOX_DEMO_MODEL` | the value of `NOMETRIA_DEMO_MODEL`, only if set |

`AGENTFOX_ORG_ID` is already renamed. `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` have no
prefix and stay.

Then reconnect the database under the new prefix: Vercel → Storage → the demo's Neon
database → Projects → `guardrails-redteam-lang` → Disconnect, then Connect Project with
custom prefix **`AGENTFOX_DATABASE`** and the same environments. This only renames the
generated variables (`AGENTFOX_DATABASE_POSTGRES_URL`, …). `demo/kit/env.py` reads that
name first. Do not create `AGENTFOX_DATABASE_URL` by hand here.

The demo has no job runner. Its cold start (`web.py`, `_rotate_keys_if_configured`)
runs the rotation itself, while the bridge sees both names.

## 5. Merge `claude/key-rotation` and let it deploy

Merge the PR. Both vendored wheels (`api/vendor`, `demo/redteam-live-lang/vendor`) are
rebuilt on that branch, and all three projects redeploy from `main`. The redeploy is
also what applies the variables from steps 2 to 4: Vercel only reads environment
changes into new deployments. After it:

```bash
curl -s https://guardrails-api.vercel.app/health | jq .status          # "ok"
curl -s https://guardrails-api.vercel.app/api/version | jq .key_rotation
# {"token_encryption": "pending", "audit_signing": "pending"}   data still on the old keys
# ("complete" already, if there was nothing encrypted or checkpointed)
```

If the gateway does not come up, the runtime log names the problem. It refuses to
start on a published secret. A `misconfigured` encryption key means it is not a
Fernet key; regenerate it as in step 1.

## 6. Run the rotation

Any job-runner call does it. Use whichever is quickest:

```bash
gh workflow run monitors.yml --repo architsharm/agentfox
gh run watch --repo architsharm/agentfox    # the log shows the runner's JSON response
```

or Vercel → `guardrails-api` → Settings → Cron Jobs → `/api/internal/jobs/run` → Run, or
directly:

```bash
curl -s -X POST -H "Authorization: Bearer $CRON_KEY" \
  https://guardrails-api.vercel.app/api/internal/jobs/run | jq .key_rotation
```

`key_rotation` in that response is the job's outcome, in counts and states only, for
example `{"status": "done", "token_encryption": "complete", "audit_signing":
"complete", "reencrypted": 3, "undecryptable": 0, "resigned": 12, "chains_not_rotated": 0}`.
It is `null` when there was nothing to do, or when a rotation with the same keys
already ran in the last hour. A rotation that could not finish is retried hourly, or
on the next call after any key changes.

For the red-team demo, open its URL once after the deploy so a cold start runs.

## 7. Confirm

```bash
curl -s https://guardrails-api.vercel.app/api/version | jq .key_rotation
# {"token_encryption": "complete", "audit_signing": "complete"}
```

The answer is cached for a minute. Do not continue while either value says `pending`.
In that case, look at `undecryptable` and `chains_not_rotated` in step 6's output:

- `undecryptable > 0`: some value was not encrypted with `NOMETRIA_TOKEN_ENCRYPTION_KEY`
  either. It is left untouched. Reconnect that integration after step 8; that
  overwrites the value.
- `chains_not_rotated > 0`: a tenant's chain did not verify, so its checkpoints were not
  re-signed. The most likely cause is a checkpoint signed with the development default
  by a local CLI. Add `AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS=dev-insecure-checkpoint-key`,
  redeploy, run step 6 again, and remove that variable once the state reads `complete`.
  [key-rotation.md](key-rotation.md#when-rotation-cannot-finish) has the details.

## 8. Delete every `NOMETRIA_*` variable

On each project:

```bash
cd ~/tmp/vercel-api   # linked in step 2; `vercel link --yes --project <name>` for the others
vercel env ls production | grep NOMETRIA_
vercel env rm NOMETRIA_TOKEN_ENCRYPTION_KEY production --yes   # repeat for every name listed
vercel env ls preview | grep NOMETRIA_                          # and remove those too
```

If `guardrails-api` still has the Neon integration on the `NOMETRIA_DATABASE` prefix,
reconnect it with prefix `AGENTFOX_DATABASE`, as for the demo. The gateway reads only
`AGENTFOX_DATABASE_URL` from step 2, so this only clears the names.

Redeploy all three projects, then:

```bash
curl -s https://guardrails-api.vercel.app/api/version | jq .key_rotation
# {"token_encryption": "not_configured", "audit_signing": "not_configured"}
```

`not_configured` here means no previous key is set any more: everything is on the
new keys. Sign in to the dashboard once to confirm the GitHub flow, which uses the new
service secret. Then open a connected repository, which decrypts its token with the
new key.

## 9. Merge stage B

`claude/agentfox-rename-final` removes every `NOMETRIA_*` fallback and this bridge. It
keeps the permanent `*_PREVIOUS` key rotation. Merge it once step 8 shows no
`NOMETRIA_` names on any project.

## Checklist

- [ ] Four values generated; the encryption key is a Fernet key.
- [ ] guardrails-api: the eight `AGENTFOX_*` variables set, `CRON_SECRET` present, other
      `NOMETRIA_<NAME>` copied.
- [ ] GitHub: `AGENTFOX_CRON_SECRET` updated, `AGENTFOX_API_URL` present.
- [ ] guardrails-dashboard: `AGENTFOX_API_URL`, `AGENTFOX_SERVICE_AUTH_SECRET` (same as the
      API), new `AGENTFOX_API_TOKEN`.
- [ ] guardrails-redteam-lang: its own fresh values; Neon reconnected as `AGENTFOX_DATABASE`.
- [ ] `claude/key-rotation` merged and deployed; `/health` ok.
- [ ] Rotation run; `/api/version` → `complete`, `complete`.
- [ ] Every `NOMETRIA_*` deleted; redeployed; `/api/version` → `not_configured`, `not_configured`.
- [ ] Stage B merged.

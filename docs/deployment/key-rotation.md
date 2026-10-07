# Rotating the encryption and audit signing keys

Two AgentFox keys protect data that outlives a deploy. Changing either one without
rotating would lock you out of data that already exists, so each has a `_PREVIOUS`
companion and a rotation command.

| Key | Protects | Previous keys |
|---|---|---|
| `AGENTFOX_TOKEN_ENCRYPTION_KEY` | Every secret stored at rest (the table below) | `AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS` |
| `AGENTFOX_AUDIT_SIGNING_KEY` | The signatures on audit-chain checkpoints | `AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS` |

`AGENTFOX_SERVICE_AUTH_SECRET` and `AGENTFOX_CRON_SECRET` protect no stored data. To
rotate one, set the new value everywhere it is used (the gateway and the dashboard for
the service secret; the gateway, Vercel's `CRON_SECRET` and the caller of
`/api/internal/jobs/run` for the cron secret) and redeploy.

## What the encryption key covers

| Column | Holds |
|---|---|
| `github_connections.access_token_encrypted` | A connected GitHub account's OAuth token |
| `github_connections.webhook_secret_encrypted` | That connection's push-webhook secret |
| `source_connections.credential_encrypted` | A grounding source's password or bearer token |
| `alert_channels.url_encrypted` | A tenant's Slack incoming-webhook URL |
| `probe_targets.auth_header_ciphertext` | The `Authorization` header live probes send |
| `agent_signing_keys.key_encrypted` | An agent's inter-agent message-signing key |

The list lives in `agentfox.platform.keys.rotation.ENCRYPTED_FIELDS`, and a test fails
when an encrypted column is added without being listed there.

## How it works

- **While a previous key is set**, reads keep working. Decryption tries the current key,
  then each previous key. Checkpoint verification (`agentfox report verify`,
  `/api/audit/verify`, the compliance status) accepts a checkpoint signed by any
  configured key. Anything new is encrypted or signed with the current key only.
- **Rotation** (`agentfox admin keys rotate`, or the `keys.rotate` job) moves everything
  onto the current key:
  1. Each encrypted column, inside its own savepoint (so each column changes completely
     or not at all): a value that only a previous key decrypts is re-encrypted with the
     current key. A value that no configured key decrypts is reported by row id and
     left exactly as it is.
  2. Each tenant's audit chain, inside its own savepoint: the whole chain is verified
     under every configured key first. Only an intact chain has its previous-key
     checkpoints re-signed. Re-signing a tampered chain would launder the tampering.
     Then one `audit.key_rotated` entry records the old and new key fingerprints and
     the counts, and a checkpoint at the new head is signed with the current key.
  3. Nothing changes on a second run, and no entry is written when nothing changed.
- **Fingerprints** are the first 8 hex characters of the key's SHA-256. They appear in
  checkpoints (`key_id`), the audit entry and `agentfox admin keys status`, so you can
  tell keys apart without ever seeing one. `/api/version` shows only states.

## Rotating a key

1. Generate the new key.
   - Encryption key (a Fernet key: 32 url-safe base64 bytes):
     `openssl rand -base64 32 | tr '+/' '-_'`.
     A hex string from `openssl rand -hex 32` is **not** a valid Fernet key.
     `agentfox doctor` and `/api/version` report it as `misconfigured`.
   - Signing key: `openssl rand -hex 32`.
2. Set the new value as the key, and the old value as the previous key:

   ```bash
   AGENTFOX_TOKEN_ENCRYPTION_KEY=<new>
   AGENTFOX_TOKEN_ENCRYPTION_KEY_PREVIOUS=<old>
   AGENTFOX_AUDIT_SIGNING_KEY=<new>
   AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS=<old>
   ```

   Several retired keys can be listed, comma-separated.
3. Restart or redeploy. Everything keeps working, and new writes use the new key.
4. Rotate. Either run it yourself:

   ```bash
   agentfox admin keys rotate --dry-run   # what would change
   agentfox admin keys rotate
   ```

   or let the job runner do it. Every `/api/internal/jobs/run` call (and
   `agentfox admin jobs run-due`) enqueues one `keys.rotate` job while a previous key
   still protects something. That check costs nothing when no previous key is set.
   The cron response includes a `key_rotation` summary of what the job did.
5. Confirm:

   ```bash
   agentfox admin keys status
   curl -s https://<gateway>/api/version | jq .key_rotation
   ```

   Wait until both keys show `complete`, then remove the `_PREVIOUS` variables and
   redeploy. The states then show `not_configured`, which means there is nothing to
   rotate.

| State | Meaning |
|---|---|
| `not_configured` | No previous key is set. Nothing to rotate. |
| `pending` | Some value or checkpoint still needs a previous key. Do not remove it yet. |
| `complete` | A previous key is set, and nothing needs it any more. It can be removed. |
| `misconfigured` | A key cannot be used (for example, not a Fernet key). `agentfox admin keys status` names the variable. |

## When rotation cannot finish

- **`undecryptable` rows.** No configured key decrypts these values. They were written
  under a key you no longer have, or they are corrupt. Rotation leaves them as they
  are. Add the missing key to `_PREVIOUS` if you have it. Otherwise reconnect that
  integration (GitHub, the source, the Slack channel, the probe target), which
  overwrites the value.
- **A chain reported `chain_broken` or `unverifiable_checkpoints`.** The chain did not
  verify, so its checkpoints were not re-signed and the state stays `pending`. Run
  `agentfox report verify` to see the first break. A checkpoint signed by a key that
  is not configured looks the same as a forged one. A common cause is a local CLI that
  wrote to the production database without the production signing key, so it signed
  with the published development default. If that is what happened, add
  `dev-insecure-checkpoint-key` to `AGENTFOX_AUDIT_SIGNING_KEY_PREVIOUS` for the
  rotation and remove it afterwards. Whenever you point the CLI at a production
  database, export that deployment's `AGENTFOX_AUDIT_SIGNING_KEY` as well.
- The job runner retries a rotation that could not finish at most once an hour.

## Evidence packages

Packages exported before a rotation carry signatures from the old key. To verify
one, give the bundled verifier every key involved, comma-separated:

```bash
AGENTFOX_AUDIT_KEY="<new>,<old>" python3 verify_chain.py
```

## The red-team demo

`demo/redteam-live-lang/web.py` runs the rotation on cold start when a previous key is
set, because that deployment has no job runner of its own. For a local demo database,
run it once yourself:

```bash
cd demo/redteam-live-lang
AGENTFOX_DATABASE_URL="sqlite:///$(pwd)/demo.db" agentfox admin keys rotate
```

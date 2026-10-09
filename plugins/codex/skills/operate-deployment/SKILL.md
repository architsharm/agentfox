---
name: operate-deployment
description: Covers running AgentFox as a service. It starts the gateway and dashboard locally, deploys with Docker Compose, hardens authentication and secrets for production, issues operator tokens, applies database migrations in the right order, and checks runtime health. Use for "run the server", "open the dashboard", "deploy agentfox", "production checklist", "upgrade the database", or auth/token questions.
---

# Operate a deployment

> Commands below are written as `agentfox …`. If `agentfox` isn't on PATH, see
> [Running the CLI](../../AGENTS.md#running-the-cli).

## Local: gateway and dashboard

In a Claude Code session with the browser pane, prefer the repo's `.claude/launch.json`
entries (`gateway` on 8080, `dashboard` on 3000). Its paths point at the main checkout, so
adjust them in a worktree. Otherwise run these as background processes, never inline:

```bash
AGENTFOX_PLAYGROUND_CORS_ORIGIN=http://localhost:3000 agentfox serve --port 8080
(cd dashboard && npm ci && AGENTFOX_API_URL=http://127.0.0.1:8080 npm run dev)
```

- The API docs are at `http://127.0.0.1:8080/docs`.
- The dashboard is at `http://localhost:3000`. Start with `/start`, `/findings`, `/agents` and
  `/policies`.
- In development, API calls can use `X-AgentFox-User: admin@example.com`.

## Self-host: Docker Compose

```bash
export HF_TOKEN=…              # build secret for model weights; ask the user to set it, never write it
export AGENTFOX_SERVICE_AUTH_SECRET="$(openssl rand -hex 32)"
export AGENTFOX_AUDIT_SIGNING_KEY="$(openssl rand -hex 32)"   # the user keeps a copy
docker compose -f deploy/docker-compose.yml up --build
```

Services: `db` (Postgres 16), `opa` (8181, optional), `gateway` (8080), `dashboard` (3000).
The defaults are egress off, the echo provider, observe mode, and fail-open. Outside
development the gateway refuses to start while either secret is unset or a published value.

The image loads no demo data. Create the first operator, then sign in on `/login` with
"Self-hosted? Sign in with an API token" (GitHub OAuth is optional: `GITHUB_CLIENT_ID` and
`GITHUB_CLIENT_SECRET`):

```bash
docker compose -f deploy/docker-compose.yml exec gateway \
  agentfox admin users create you@example.com --role owner --token
```

Demo data only on request: `docker compose … exec gateway agentfox admin seed`.

## Production hardening checklist

Go through every line with the user. `agentfox doctor` and `agentfox admin auth status` verify
several of them.

| # | Check | How |
|---|---|---|
| 1 | Dev auth header refused | `AGENTFOX_ENVIRONMENT=production`, `AGENTFOX_AUTH_MODE=token` (or `oidc`); `agentfox admin auth status` |
| 2 | Postgres, not SQLite | `AGENTFOX_DATABASE_URL=postgresql+psycopg://…`, `[postgres]` extra |
| 3 | Secrets changed from dev defaults | `AGENTFOX_AUDIT_SIGNING_KEY` and `AGENTFOX_SERVICE_AUTH_SECRET` (the gateway refuses to start outside development without them; `agentfox doctor` checks), `AGENTFOX_TOKEN_ENCRYPTION_KEY`, `AGENTFOX_CRON_SECRET` |
| 4 | Fail mode deliberate | `AGENTFOX_FAIL_MODE=closed` for high-risk agents; know that `open` lets requests through on detector timeout |
| 5 | Egress intentional | `AGENTFOX_ALLOW_EGRESS=true` only when a real provider is configured |
| 6 | Detectors as expected | `agentfox doctor` lists them; add extras for Presidio or classifiers |
| 7 | Operator tokens, not shared logins | First operator: `agentfox admin users create <email> --role owner`; then `agentfox admin auth issue <email> --days 90` (shown once; the user stores it) |
| 8 | Migrations current | `agentfox admin db current` = head; `agentfox admin db upgrade` |
| 9 | Audit checkpoints scheduled | `agentfox admin checkpoint` on a timer; jobs runner via `/api/internal/jobs/run` with the cron secret |

Reference: [reference/config.md](../../reference/config.md).

## Upgrades: order matters

The wheel does not bundle `migrations/`, and the hosted API and demo share one database.
So: **run `agentfox admin db upgrade` against the target DB first, then deploy the new code.** The
reverse order has taken production down with `UndefinedColumn` before. `db downgrade` is
destructive (BLK); every migration ships a tested downgrade, but data in dropped columns is
gone.

## Health

`GET /api/health` returns liveness. `GET /metrics` gives Prometheus metrics.
`agentfox doctor` gives a runtime self-check. `GET /api/reliability` shows circuit breakers
and the fallback chain.

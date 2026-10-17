-- Catch-up for the hosted Neon database, revision c4a71e8b2d16.
--
-- Run this BEFORE the code that needs it reaches production, or immediately after.
-- The public playground now keeps each sandbox in the shared database instead of one
-- server process, so any instance can serve any sandbox. Two things follow:
--
--   * a new table, which init_db()'s create_all would add on its own, and
--   * a change create_all CANNOT make: users.email stops being globally unique and
--     becomes unique per tenant. Without it, creating a sandbox fails, because a
--     sandbox seeds its own world and its fixture users collide with the real ones.
--
-- Until this runs, sandbox creation answers 503 naming this migration rather than
-- failing obscurely. Everything else on the deployment is unaffected.
--
-- Run it in the Neon SQL editor (Vercel -> Storage -> guardrails-db -> Query, with
-- read-only off), or from a checkout:
--   AGENTFOX_DATABASE_URL='<neon url>' uv run alembic upgrade head
-- Afterwards: select version_num from alembic_version;  -- expect c4a71e8b2d16

BEGIN;

CREATE TABLE IF NOT EXISTS playground_sandboxes (
  id           VARCHAR(64)  NOT NULL PRIMARY KEY,
  expires_at   TIMESTAMPTZ  NOT NULL,
  last_used_at TIMESTAMPTZ  NOT NULL,
  trace_ids    JSON         NOT NULL,
  created_at   TIMESTAMPTZ  NOT NULL,
  updated_at   TIMESTAMPTZ  NOT NULL,
  org_id       VARCHAR(64)  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_playground_sandboxes_expires_at ON playground_sandboxes (expires_at);
CREATE INDEX IF NOT EXISTS ix_playground_sandboxes_org_id ON playground_sandboxes (org_id);

-- users.email: globally unique -> unique per tenant.
DROP INDEX IF EXISTS ix_users_email;
ALTER TABLE users DROP CONSTRAINT IF EXISTS ux_users_org_email;
ALTER TABLE users ADD CONSTRAINT ux_users_org_email UNIQUE (org_id, email);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

UPDATE alembic_version SET version_num = 'c4a71e8b2d16' WHERE version_num = 'd5e2a9c14f03';

COMMIT;

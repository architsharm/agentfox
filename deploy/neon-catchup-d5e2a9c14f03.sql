-- One-off catch-up for the hosted Neon database, 2026-09-18.
--
-- Why this exists rather than `alembic upgrade head`: the serverless deployment
-- cannot run migrations (its wheel does not bundle `migrations/`), and `init_db()`
-- had already created the *tables* this revision adds via create_all. So the plain
-- migration fails on CREATE TABLE while the columns it adds to existing tables —
-- findings.fingerprint above all — are still missing, which is why the Findings page
-- returned a 500 in production while Agents worked.
--
-- Every statement is IF NOT EXISTS, so running it twice is safe, and the final
-- UPDATE moves alembic_version to the revision the code expects.
--
-- Run it in the Neon SQL editor (Vercel → Storage → guardrails-db → Query, with
-- read-only off), or locally:
--   AGENTFOX_DATABASE_URL='<neon url>' uv run alembic upgrade head
-- Verify afterwards:
--   select version_num from alembic_version;  -- expect d5e2a9c14f03

BEGIN;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64);
ALTER TABLE findings ADD COLUMN IF NOT EXISTS occurrences INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX IF NOT EXISTS ix_findings_fingerprint ON findings (fingerprint);
CREATE INDEX IF NOT EXISTS ix_feedback_decision_actor ON guardrail_feedback (decision_id, actor);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS available_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS schedule_id VARCHAR(40);
CREATE INDEX IF NOT EXISTS ix_jobs_schedule_id ON jobs (schedule_id);
ALTER TABLE policy_canaries ADD COLUMN IF NOT EXISTS max_block_rate_drop DOUBLE PRECISION DEFAULT 0.15 NOT NULL;
ALTER TABLE policy_canaries ADD COLUMN IF NOT EXISTS min_dwell_seconds INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE policy_canaries ADD COLUMN IF NOT EXISTS last_advanced_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX IF NOT EXISTS ix_proposals_status_created ON change_proposals (status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_proposals_open_fingerprint ON change_proposals (org_id, fingerprint) WHERE fingerprint IS NOT NULL AND status IN ('proposed', 'proven', 'approved', 'canary', 'applied');
UPDATE alembic_version SET version_num='d5e2a9c14f03' WHERE version_num='b3f8e29a71c4';
COMMIT;

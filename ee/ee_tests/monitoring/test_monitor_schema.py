"""The schema: a database that has not run the migration still works, and the migration
does not fight what startup already added."""

from __future__ import annotations

import sqlalchemy as sa


def test_a_database_before_the_monitor_migration_still_serves_github_connections(
    tmp_path, monkeypatch
):
    from agentfox.core.config import reset_settings_cache
    from agentfox.core.db import downgrade_db, init_db, reset_engine, upgrade_db

    url = f"sqlite:///{tmp_path / 'pre.db'}"
    monkeypatch.setenv("AGENTFOX_DATABASE_URL", url)
    reset_settings_cache()
    reset_engine()
    try:
        upgrade_db("b8d3f6a2c915")  # the revision before monitors
        inspector = sa.inspect(sa.create_engine(url))
        assert not inspector.has_table("monitors")
        columns = {c["name"] for c in inspector.get_columns("github_connections")}
        assert "webhook_secret_encrypted" not in columns

        init_db(stamp=False)  # what startup does
        init_db(stamp=False)
        inspector = sa.inspect(sa.create_engine(url))
        assert inspector.has_table("monitors") and inspector.has_table("alert_channels")
        columns = {c["name"] for c in inspector.get_columns("github_connections")}
        assert "webhook_secret_encrypted" in columns

        upgrade_db("head")  # and the migration does not fight it
        downgrade_db("b8d3f6a2c915")
        inspector = sa.inspect(sa.create_engine(url))
        assert not inspector.has_table("monitors")
        upgrade_db("head")
        assert sa.inspect(sa.create_engine(url)).has_table("monitors")
    finally:
        reset_settings_cache()
        reset_engine()

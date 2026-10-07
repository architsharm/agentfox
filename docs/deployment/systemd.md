# Run the gateway with systemd

*Contributed by [@PandaHUN777](https://github.com/PandaHUN777) in [#30](https://github.com/architsharm/agentfox/pull/30).*

This guide runs the Python gateway as a systemd user service. It does not install the dashboard or configure TLS; put a reverse proxy in front of the loopback listener for remote access. It was tested on Ubuntu 26.04.1 LTS with Python 3.14.

## Install and keep state separate

Install Python venv support and OpenSSL, then install AgentFox in a dedicated virtual environment:

```bash
sudo apt install python3-venv openssl
mkdir -p ~/.local/opt/agentfox ~/.local/share/agentfox/evidence ~/.config/agentfox ~/.config/systemd/user
python3 -m venv ~/.local/opt/agentfox/venv
~/.local/opt/agentfox/venv/bin/pip install "agentfox[postgres] @ git+https://github.com/architsharm/agentfox.git"
chmod 700 ~/.config/agentfox ~/.local/share/agentfox ~/.local/share/agentfox/evidence
```

Keep the SQLite database at `~/.local/share/agentfox/agentfox.db` (the unit sets the state directory) and evidence files in the separate `~/.local/share/agentfox/evidence/` directory. The signing key belongs in the protected environment file below, not in the database: a database copy alone must not be enough to forge signed checkpoints. Keep the key customer-held and back it up separately from the database.

Create the environment file with the two required secrets. Its directory and file should be readable only by the service account:

```bash
umask 077
cat > ~/.config/agentfox/agentfox.env <<EOF
AGENTFOX_ENVIRONMENT=production
AGENTFOX_SERVICE_AUTH_SECRET=$(openssl rand -hex 32)
AGENTFOX_AUDIT_SIGNING_KEY=$(openssl rand -hex 32)
EOF
```

`AGENTFOX_ENVIRONMENT=production` makes `/api` require an API token. Outside development the gateway refuses to start while `AGENTFOX_SERVICE_AUTH_SECRET` (which authenticates the dashboard's sign-in call; give a dashboard the same value) or `AGENTFOX_AUDIT_SIGNING_KEY` is unset or still a published default. Without the environment line the gateway runs in development, where an unauthenticated request acts as whichever user it names.

If you use PostgreSQL, add `AGENTFOX_DATABASE_URL=...` to that file. Settings are read as `AGENTFOX_*`; the pre-rename `NOMETRIA_*` names are no longer read, so rename them in an existing environment file (a startup warning and `agentfox doctor` name any that are left).

## Add the user units

Create `~/.config/systemd/user/agentfox.service`:

```ini
[Unit]
Description=AgentFox gateway

[Service]
Type=simple
EnvironmentFile=%h/.config/agentfox/agentfox.env
Environment=AGENTFOX_STATE_DIR=%h/.local/share/agentfox
Environment=AGENTFOX_EVIDENCE_DIR=%h/.local/share/agentfox/evidence
ExecStart=%h/.local/opt/agentfox/venv/bin/agentfox serve --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
```

Create `~/.config/systemd/user/agentfox-migrate.service` for explicit, one-shot schema upgrades:

```ini
[Unit]
Description=Upgrade the AgentFox database schema

[Service]
Type=oneshot
EnvironmentFile=%h/.config/agentfox/agentfox.env
Environment=AGENTFOX_STATE_DIR=%h/.local/share/agentfox
Environment=AGENTFOX_EVIDENCE_DIR=%h/.local/share/agentfox/evidence
ExecStart=%h/.local/opt/agentfox/venv/bin/agentfox admin db upgrade
UMask=0077
```

Create `~/.config/systemd/user/agentfox-jobs.service` and `~/.config/systemd/user/agentfox-jobs.timer` for scheduled work. Source monitors, drift, compliance and canary jobs only run when something runs the job runner, and each pass is safe to repeat:

```ini
[Unit]
Description=Run due AgentFox jobs

[Service]
Type=oneshot
EnvironmentFile=%h/.config/agentfox/agentfox.env
Environment=AGENTFOX_STATE_DIR=%h/.local/share/agentfox
Environment=AGENTFOX_EVIDENCE_DIR=%h/.local/share/agentfox/evidence
ExecStart=%h/.local/opt/agentfox/venv/bin/agentfox admin jobs run-due
UMask=0077
```

```ini
[Unit]
Description=Run due AgentFox jobs every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

A cron entry that runs the same command with the same environment works as well.

Load the units, migrate the new database, and start the gateway and the timer:

```bash
systemctl --user daemon-reload
systemctl --user start agentfox-migrate.service
systemctl --user enable --now agentfox.service agentfox-jobs.timer
systemctl --user is-active agentfox.service
curl --fail http://127.0.0.1:8080/health
```

## Load the policy packs and create the first operator

A new database has no policy packs and no operators, and the gateway does not load demo data. Run these once with the service's environment, so they reach the same database:

```bash
set -a; . ~/.config/agentfox/agentfox.env; set +a
export AGENTFOX_STATE_DIR=~/.local/share/agentfox AGENTFOX_EVIDENCE_DIR=~/.local/share/agentfox/evidence
~/.local/opt/agentfox/venv/bin/agentfox init --path ~/.config/agentfox
~/.local/opt/agentfox/venv/bin/agentfox admin users create you@example.com --role owner --token
systemctl --user restart agentfox.service
```

`init` loads the control catalogue and the policy packs; it is idempotent, and `--path` keeps the `agentfox.toml` it writes out of your working directory. `users create --token` prints the operator's API token once; send it to `/api` as `Authorization: Bearer <token>`. `agentfox doctor`, run the same way, should show `authentication` and `secrets` passing.

## Optional settings

Add any of these to the environment file and restart the service:

| Setting | What it does |
| --- | --- |
| `AGENTFOX_ALLOW_EGRESS=true` | Lets findings leave the machine. The webhook and Slack settings below send nothing without it. |
| `AGENTFOX_WEBHOOK_URL`, `AGENTFOX_WEBHOOK_SECRET` | POSTs each new finding at or above `AGENTFOX_WEBHOOK_MIN_SEVERITY` (default `high`) to your endpoint, signed with the secret. |
| `AGENTFOX_SLACK_WEBHOOK_URL` | Posts monitor findings at or above `AGENTFOX_SLACK_MIN_SEVERITY` (default `medium`) to a Slack incoming webhook. |
| `AGENTFOX_GITHUB_WEBHOOK_SECRET` | Verifies GitHub push deliveries, so a connected repository is re-scanned on push as well as on schedule. |
| `AGENTFOX_LIVE_PROBES_ENABLED=false` | Stops scheduled probing of every opted-in deployed agent at once. |
| `AGENTFOX_SHOWCASE_ENABLED` | Leave unset. It runs the public showcase behind the hosted `/live` page and is off by default. |

The listener is loopback-only. Configure TLS and remote access in a reverse proxy rather than exposing port 8080 directly. To start the user service after boot before that account logs in, an administrator can enable lingering once with `sudo loginctl enable-linger <service-user>`.

## Upgrade

Stop the gateway, install the new version into the same virtual environment, run the migration unit, then restart the gateway. The migration unit reads the same environment file and targets the same database as the service:

```bash
systemctl --user stop agentfox.service
~/.local/opt/agentfox/venv/bin/pip install --upgrade "agentfox @ git+https://github.com/architsharm/agentfox.git"
systemctl --user start agentfox-migrate.service
systemctl --user restart agentfox.service
journalctl --user -u agentfox.service -n 50 --no-pager
```

If the migration unit fails, leave the gateway stopped and resolve that error before restarting it. See [Appendix E.2.2](../architecture/threat-model.md#e22-we-hold-the-most-sensitive-text-in-the-company) for why the signing key is customer-held and kept outside the application database.

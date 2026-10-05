# Run the gateway with systemd

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

Create the environment file with a fresh key. Its directory and file should be readable only by the service account:

```bash
umask 077
printf 'NOMETRIA_AUDIT_SIGNING_KEY=%s\n' "$(openssl rand -hex 32)" > ~/.config/agentfox/agentfox.env
```

If you use PostgreSQL, add `NOMETRIA_DATABASE_URL=...` to that file. The `NOMETRIA_` names remain supported for existing deployments.

## Add the user units

Create `~/.config/systemd/user/agentfox.service`:

```ini
[Unit]
Description=AgentFox gateway

[Service]
Type=simple
EnvironmentFile=%h/.config/agentfox/agentfox.env
Environment=AGENTFOX_STATE_DIR=%h/.local/share/agentfox
Environment=NOMETRIA_EVIDENCE_DIR=%h/.local/share/agentfox/evidence
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
Environment=NOMETRIA_EVIDENCE_DIR=%h/.local/share/agentfox/evidence
ExecStart=%h/.local/opt/agentfox/venv/bin/agentfox db upgrade
UMask=0077
```

Load the units, migrate the new database, and start the gateway:

```bash
systemctl --user daemon-reload
systemctl --user start agentfox-migrate.service
systemctl --user enable --now agentfox.service
systemctl --user is-active agentfox.service
curl --fail http://127.0.0.1:8080/health
```

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

If the migration unit fails, leave the gateway stopped and resolve that error before restarting it. See [Appendix E.2.2](appendix-e-threat-model.md#e22-we-hold-the-most-sensitive-text-in-the-company) for why the signing key is customer-held and kept outside the application database.

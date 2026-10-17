"""Vercel entrypoint.

Exposes the same FastAPI app used for self-hosting — Vercel's Python runtime serves an
ASGI app directly, so there is nothing deployment-specific here. Configuration (which
database, which evidence directory, which auth mode) is entirely environment variables,
by the same design that lets one container run in dev, docker-compose, or a VPC without
a rebuild (see dashboard/next.config.mjs for the equivalent reasoning on the frontend).

`agentfox` is installed from the prebuilt wheel checked in at `api/vendor/`, listed
in requirements.txt next to this file (that file explains why a path dependency on
the repo root does not work on Vercel). Root Directory for this Vercel project is
"api", so only what lands in site-packages ships with the function. The wheel is
therefore the deployed code: a change to src/agentfox reaches production only once
the wheel is rebuilt (`uv build --wheel --out-dir api/vendor`) and committed.
"""

from agentfox.apps.gateway.app import app

__all__ = ["app"]

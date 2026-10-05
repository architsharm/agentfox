"""Gateway — inline enforcement (/v1) and control-plane API (/api)."""

from agentfox.gateway.app import app, create_app

__all__ = ["app", "create_app"]

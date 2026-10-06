"""Gateway — inline enforcement (/v1) and control-plane API (/api).

The ASGI app lives at ``agentfox.apps.gateway.app:app``. It is deliberately not imported
here: building it refuses to run a non-development environment on published secrets
(see ``agentfox.core.config.assert_production_secrets``), and that refusal belongs to
the process that *serves* — not to a CLI command such as ``agentfox admin auth issue``
that only imports ``agentfox.apps.gateway.auth`` to mint the token an operator needs.
"""

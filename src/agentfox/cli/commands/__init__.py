"""The CLI's command groups, one module per group.

Each module owns its Typer sub-app (``agents_app``, ``policy_app`` …) and the
commands on it; ``agentfox.cli.main`` mounts them on the root app and then hands
the whole tree to ``agentfox.cli.layout``, which finds commands by CLI name.
"""

"""The capability packs shipped with AgentFox.

Each directory holding a ``pack.yaml`` is a pack: data (policies, controls, ladders,
probes, cases, fixtures) plus optional checks. Nothing imports this package; the
loader in `agentfox.platform.packs` reads it. ``_template/`` is what
``just new-pack`` copies.
"""

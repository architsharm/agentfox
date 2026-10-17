"""The red-team live demos' shared kit: one support-tools agent, its seed and its checks.

`demo/redteam-live/` (CrewAI) and `demo/redteam-live-lang/` (LangChain, deployed on
Vercel) used to carry forked copies of these files. They now share this one
implementation; each demo keeps only its framework-specific code plus thin adapters
(`_env.py`, `support_tools.py`, `seed_demo_agent.py`, `verify_mechanics.py`) that pass
in its agent slug and labels.

  * `env.py`            — which database agentfox uses (call `configure()` first)
  * `support_tools.py`  — the fake dataset, the four tools, grants, `GovernedToolkit`
  * `seed.py`           — registers a demo's agent, grants, tools and policy packs
  * `verify_mechanics.py` — the non-LLM end-to-end checks and scripted fallback

This is the canonical copy. `demo/redteam-live-lang/kit/` is a committed, byte-identical
copy, because that demo's Vercel project has Root Directory `demo/redteam-live-lang`
and nothing outside it is available at deploy time. Edit here, then run
`python scripts/check/demo_kit.py --write`; the check (in `just check`, CI and
tests/repo/test_demo_kit.py) fails when the copy drifts. The CrewAI demo is not
deployed, so its `_env.py` imports this folder directly by putting `demo/` on
`sys.path`.

Nothing here imports agentfox at package import time, so `kit.env.configure()` can run
before agentfox's cached settings are first read.
"""

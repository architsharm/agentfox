"""`auto()` must not claim protection it is not providing.

Found by installing 0.3.1 from PyPI into a third-party project and calling
`agentfox.auto(mode="enforce")` without running `agentfox init` first — which
is exactly what adding one line to an existing application looks like. The
banner said "governing in enforce mode", the canonical prompt injection went
straight through to OpenAI, and the 401 from a deliberately invalid key proved
it had left the process.

The cause is benign: a database that has never been initialised holds no
policies, so no content rule can fire. The behaviour is not. A security tool
that announces protection it is not providing is worse than one that is
absent, because the absent one does not stop anyone looking further.
"""

from __future__ import annotations

from agentfox.autoguard import AutoState


def _state(**kw) -> GuardState:
    return AutoState(agent="a", mode="enforce", environment="development", **kw)


def test_banner_warns_when_no_policy_is_bound() -> None:
    summary = _state(policies_bound=0).summary()
    assert "shipped baseline applies as a fallback" in summary
    assert "in observe" in summary
    # The way out has to be in the message; a warning with no remedy is noise.
    assert "agentfox init" in summary


def test_banner_is_quiet_when_policies_are_bound() -> None:
    """A warning that cries wolf is worse than no warning."""
    assert "fallback" not in _state(policies_bound=3).summary()


def test_banner_is_quiet_when_the_count_is_unknown() -> None:
    """-1 means the count could not be taken, which is not the same as zero.

    Claiming "nothing is enforced" on a failed query would be its own false
    statement, in the other direction.
    """
    assert "fallback" not in _state(policies_bound=-1).summary()


def test_the_warning_does_not_overclaim_either() -> None:
    """Tool-call containment does not depend on a policy being bound, so the
    warning must not tell someone they have no protection at all."""
    summary = _state(policies_bound=0).summary()
    assert "Tool-call containment enforces regardless" in summary

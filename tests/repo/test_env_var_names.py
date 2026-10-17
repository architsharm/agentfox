"""What the product tells people to set is the current name: ``AGENTFOX_<name>``."""

from __future__ import annotations


def test_generated_config_names_the_current_prefix():
    from agentfox.apps.cli.onboarding import _CONFIG_TEMPLATE

    assert "AGENTFOX_*" in _CONFIG_TEMPLATE

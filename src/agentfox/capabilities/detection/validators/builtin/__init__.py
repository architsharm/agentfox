"""Built-in validators, one module per family. Each module registers on import.

Much of this is ported from the Guardrails AI validator repositories
(github.com/guardrails-ai/<name>, Apache-2.0); each ported class names its source
in ``upstream``. See NOTICE at the repository root. The logic is rewritten
against our interface, without the ``guardrails`` package, so nothing here
needs a separate install or reaches the network.
"""

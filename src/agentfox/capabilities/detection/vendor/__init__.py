"""Third-party code vendored into AgentFox, kept close to upstream.

``credential_redactor`` and ``mcp_security`` come from an MIT-licensed open-source
agent governance project (upstream commit c767f83). Each file keeps its upstream
copyright header and lists every local change at the top; the MIT license text is
in ``LICENSE`` beside this file.

These modules are reference tables, not detectors: AgentFox's own detectors
(``detectors/secrets.py``, the MCP scan in ``platform/registry/service.py``) carry
the patterns from here that added coverage, under AgentFox's own entity and finding
types. Nothing in AgentFox imports these modules at request time.
"""

# compliance/catalog

The control catalog: every NOM-* control with its status rule and its draft mappings to
the EU AI Act, NIST AI RMF, ISO/IEC 42001, SOC 2, OWASP LLM Top 10, OWASP Agentic Threats
and MITRE ATLAS; the dated obligation calendar; the threat catalogues coverage is
measured against.

One pack, not one per framework: most controls map to several frameworks, so a split
would copy each control into up to seven packs. Every mapping is a draft until a named
reviewer signs it off.

**What it ships.** `controls/controls.yaml`, `controls/obligations.yaml`,
`controls/threats.yaml`, golden mapping cases.

```bash
agentfox admin catalog validate
agentfox policy packs test compliance/catalog
```

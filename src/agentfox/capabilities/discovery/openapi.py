"""Static analysis for the hosted-API onboarding path.

``discovery.py`` needs source on disk to walk with ``ast`` — a non-starter for a team
whose AI system is a hosted API they call, not code they'd hand over. This module
produces the same ``Site``-shaped output from an OpenAPI document instead: each
operation becomes one governable site, so the rest of the onboarding pipeline (site
grouping, draft agent/policy creation in ``routes/integrations.py``) is reused
unchanged.

Only the *spec document* is ever fetched — never an operation on the live API. That
mirrors ``discovery.scan``'s own "static, never import, never execute" guarantee for a
repo, just for a different kind of target.
"""

from __future__ import annotations

from typing import Any

from agentfox.capabilities.discovery.repo import ScanReport, Site
from agentfox.core import outbound

#: A fetched spec document beyond this is refused outright — a resource-exhaustion
#: guard on server-supplied content, the same shape as the repo-tarball size cap.
_MAX_SPEC_BYTES = 5 * 1024 * 1024

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
#: Mutating methods are worth flagging more prominently than a plain read — not a
#: judgement about the endpoint itself, just a sorting hint for the review UI.
_METHOD_SEVERITY = {
    "get": "info",
    "post": "info",
    "put": "warn",
    "patch": "warn",
    "delete": "warn",
}


class SpecFetchError(ValueError):
    """The spec document could not be fetched or parsed. Never a code-execution
    failure — this module never runs anything from the target, only reads text."""


def fetch_spec(spec_url: str) -> dict[str, Any]:
    """Fetch and parse an OpenAPI document (JSON or YAML) from a URL.

    Only public http(s) addresses are fetched, redirects are re-vetted hop by hop,
    and the connection goes to the address that was checked (`core.outbound`).
    """
    try:
        resp = outbound.guarded_get(spec_url, what="the OpenAPI spec", max_bytes=_MAX_SPEC_BYTES)
    except outbound.OutboundRefused as exc:
        raise SpecFetchError(str(exc)) from exc

    content_type = resp.headers.get("content-type", "")
    looks_like_yaml = "yaml" in content_type or spec_url.lower().endswith((".yaml", ".yml"))

    def _parse_yaml() -> dict[str, Any]:
        import yaml

        try:
            parsed = yaml.safe_load(resp.text)
        except Exception as exc:
            raise SpecFetchError(
                f"the document at that URL is not valid JSON or YAML: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise SpecFetchError("the document did not parse to an OpenAPI object")
        return parsed

    if looks_like_yaml:
        return _parse_yaml()
    try:
        return resp.json()
    except Exception:
        return _parse_yaml()


def scan_spec(spec: dict[str, Any], *, source_label: str = "") -> ScanReport:
    """Turn a parsed OpenAPI document into the same site-shaped output
    ``discovery.scan`` produces from a repo.

    Every operation becomes a ``tool``-kind site — an endpoint is a capability an
    agent (or a human, via this API) can invoke, which is exactly what a ``tool``
    site already means in the repo-scan vocabulary.
    """
    title = (spec.get("info") or {}).get("title") or source_label or "hosted-api"
    report = ScanReport(root=source_label or title)
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        report.errors.append("no `paths` object in the OpenAPI document")
        return report

    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, op in operations.items():
            method_key = str(method).lower()
            if method_key not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            summary = op.get("summary") or op.get("operationId") or f"{method_key.upper()} {path}"
            report.sites.append(
                Site(
                    kind="tool",
                    file=title,
                    line=0,
                    detail=f"{method_key.upper()} {path} — {summary}",
                    provider="hosted_api",
                    governed=False,
                    severity=_METHOD_SEVERITY[method_key],
                )
            )

    report.files_scanned = 1
    report.frameworks = ["hosted_api"]
    return report

"""Generate the docs site's CLI and HTTP reference from the code, and check the docs.

    python scripts/docs_reference.py --write   # regenerate dashboard/lib/reference/*.json
    python scripts/docs_reference.py --check   # exit 1 if they are stale, or if any
                                                # `agentfox ...` printed on a docs page
                                                # names a command or option that does
                                                # not exist

The docs pages render the JSON; nobody types a flag table by hand, so the reference
cannot drift from the CLI it describes. The same check walks every `<code>` and
`<Code>` block under dashboard/app/docs and resolves each invocation against the live
click tree, with the harness checker's resolver, so a renamed command fails CI here
the way it already does for the harness markdown.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "dashboard" / "lib" / "reference"
DOCS = REPO / "dashboard" / "app" / "docs"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


#: Internal tracking codes ("(P3-4, P2-2)", "(P17, NOM-IAM-08)", "I-7 —") mean nothing
#: to a reader of the docs site; they stay in the source, not on the page.
_CODE = r"(?:P\d+(?:-\d+)?|PL-\d+|X-\d+|I-\d+|F\d+(?:\.\d+)?|B\.\d+|NOM-[A-Z]+-\d+|ASI\d+)"
_CODES = re.compile(
    rf"\s*\((?:{_CODE}|Pillars? [\d, ]+)(?:\s*[,/]\s*(?:{_CODE}|Pillars? [\d, ]+))*\)"
)
_LEADING_CODE = re.compile(rf"^{_CODE}\s*[—:-]\s*")


def _clean(text: str | None) -> str:
    text = inspect.cleandoc(text or "").strip()
    return _LEADING_CODE.sub("", _CODES.sub("", text))


def _str_or_none(value: Any) -> str | None:
    # typer leaves a DefaultPlaceholder where nothing was set
    return value if isinstance(value, str) else None


def _param(p: Any) -> dict[str, Any]:
    import click

    is_option = isinstance(p, click.Option)
    default = p.default
    if callable(default) or default in ((), [], None) or repr(default).startswith("<"):
        default = None
    elif isinstance(default, tuple):
        default = list(default)
    elif not isinstance(default, (str, int, float, bool, list)):
        default = str(default)
    choices = list(getattr(p.type, "choices", []) or [])
    return {
        "kind": "option" if is_option else "argument",
        "name": p.name,
        "opts": list(getattr(p, "opts", [])) + list(getattr(p, "secondary_opts", [])),
        "type": "flag" if getattr(p, "is_flag", False) else p.type.name,
        "choices": [str(c) for c in choices],
        "required": bool(p.required),
        "multiple": bool(getattr(p, "multiple", False)),
        "default": default if not getattr(p, "is_flag", False) or default else None,
        "help": _clean(_str_or_none(getattr(p, "help", None))),
    }


def _command(cmd: Any, path: list[str], ctx_cls: Any) -> dict[str, Any]:
    import click

    node: dict[str, Any] = {
        "path": " ".join(path),
        "name": path[-1] if path else "agentfox",
        "summary": _clean(cmd.get_short_help_str(limit=200)) if path else "",
        "help": _clean(_str_or_none(cmd.help)),
        "panel": _str_or_none(getattr(cmd, "rich_help_panel", None)),
        "params": [
            _param(p)
            for p in cmd.params
            if not getattr(p, "hidden", False) and p.name not in ("help",)
        ],
        "default_subcommand": _str_or_none(getattr(cmd, "default_command", None)),
        "commands": [],
    }
    if isinstance(cmd, click.Group):
        ctx = ctx_cls(cmd)
        for name in cmd.list_commands(ctx):
            sub = cmd.get_command(ctx, name)
            if sub is None or getattr(sub, "hidden", False):
                continue
            node["commands"].append(_command(sub, [*path, name], ctx_cls))
    return node


def build_cli() -> dict[str, Any]:
    import click
    import typer.main

    from agentfox.apps.cli.main import app

    root = typer.main.get_command(app)
    tree = _command(root, [], click.Context)
    return {
        "generated_by": "scripts/docs_reference.py",
        "root": tree,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _audience(path: str) -> str:
    if path.startswith("/v1/") or path in ("/health", "/metrics"):
        return "public"
    if (
        path.startswith("/api/playground")
        or path.startswith("/api/public/")
        or path == "/api/waitlist"
    ):
        return "public-unauthenticated"
    if path.startswith("/api/internal/"):
        return "internal"
    return "operator"


def _section(path: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{")]
    if not parts:
        return "platform"
    if parts[0] == "v1":
        return "v1/" + (parts[1] if len(parts) > 1 else "")
    if parts[0] == "api" and len(parts) > 1:
        return parts[1]
    return parts[0]


def _body(spec: dict[str, Any], op: dict[str, Any]) -> dict[str, Any] | None:
    ref = (
        op.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref", "")
    )
    if not ref:
        return None
    model = ref.rsplit("/", 1)[-1]
    schema = spec.get("components", {}).get("schemas", {}).get(model, {})
    required = set(schema.get("required", []))
    fields = []
    for name, prop in (schema.get("properties") or {}).items():
        kind = prop.get("type") or prop.get("$ref", "").rsplit("/", 1)[-1]
        if not kind and prop.get("anyOf"):
            kinds = [a.get("type") or a.get("$ref", "").rsplit("/", 1)[-1] for a in prop["anyOf"]]
            kind = " | ".join(k for k in kinds if k and k != "null")
        fields.append(
            {
                "name": name,
                "type": kind or "any",
                "required": name in required,
                "description": prop.get("description", ""),
            }
        )
    return {"model": model, "fields": fields}


def build_api() -> dict[str, Any]:
    import os
    import tempfile

    # Same as scripts/api_routes.py: a throwaway database, and the app as create_app()
    # builds it, with every router mounted. The OpenAPI document is the source, since
    # included routers are resolved lazily and are not all in `app.routes`.
    os.environ.setdefault("AGENTFOX_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/ref.db")
    from agentfox.gateway.app import create_app

    spec = create_app().openapi()
    routes = []
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            doc = _clean(op.get("description"))
            routes.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "section": _section(path),
                    "audience": _audience(path),
                    "summary": (doc.split("\n\n", 1)[0].replace("\n", " ") if doc else "")
                    or _clean(op.get("summary", "")),
                    "description": doc,
                    "params": [
                        {
                            "name": p.get("name"),
                            "in": p.get("in"),
                            "required": bool(p.get("required")),
                            "type": (p.get("schema") or {}).get("type"),
                        }
                        for p in op.get("parameters", [])
                    ],
                    "body": _body(spec, op),
                }
            )
    routes.sort(key=lambda r: (r["audience"] != "public", r["section"], r["path"], r["method"]))
    return {"generated_by": "scripts/docs_reference.py", "count": len(routes), "routes": routes}


# ---------------------------------------------------------------------------
# Checking the pages
# ---------------------------------------------------------------------------

# <Output> blocks are not checked: they are what the product printed, wrapped where
# the terminal wrapped it, and a wrapped hint is not an invocation.
CODE_BLOCK = re.compile(r"<(code|Code|Terminal)\b[^>]*>(.*?)</\1>", re.S)
CODE_PROP = re.compile(
    r"\b(?:code|command|cmd)=\{?`([^`]*)`\}?|\b(?:code|command|cmd)=\"([^\"]*)\"", re.S
)


def _fragments(tsx: str) -> list[str]:
    out = []
    for _tag, body in CODE_BLOCK.findall(tsx):
        body = re.sub(r"^\s*\{`|`\}\s*$", "", body.strip())
        body = re.sub(r"\{\"\s*\"\}", " ", body)
        out.extend(html.unescape(body).splitlines())
    for a, b in CODE_PROP.findall(tsx):
        out.extend(html.unescape(a or b).splitlines())
    # TaskTable rows: { task: "...", run: "agentfox ..." }
    out.extend(html.unescape(m) for m in re.findall(r'\brun:\s*"([^"]*)"', tsx))
    return out


def check_pages() -> list[str]:
    spec = importlib.util.spec_from_file_location(
        "check_harness", REPO / "harness" / "scripts" / "check_harness.py"
    )
    harness = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(harness)
    for page in sorted(DOCS.rglob("*.tsx")):
        for line in _fragments(page.read_text()):
            harness._check_fragment(page, line)
    return list(harness.errors)


# ---------------------------------------------------------------------------


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, sort_keys=False, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()

    outputs = {OUT / "cli.json": _dump(build_cli()), OUT / "api.json": _dump(build_api())}
    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for path, text in outputs.items():
            path.write_text(text)
        print(f"wrote {', '.join(str(p.relative_to(REPO)) for p in outputs)}")
        return 0

    problems = []
    for path, text in outputs.items():
        if not path.exists() or path.read_text() != text:
            problems.append(
                f"{path.relative_to(REPO)} is stale: run `python scripts/docs_reference.py --write`"
            )
    problems += check_pages()
    if problems:
        print(f"docs drift: {len(problems)} problem(s)")
        for p in sorted(set(problems)):
            print("  -", p)
        return 1
    print("docs reference is current, and every command on the docs pages exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())

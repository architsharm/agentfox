"""`agentfox admin keys` — rotate the encryption and audit signing keys.

Set the new key as ``AGENTFOX_TOKEN_ENCRYPTION_KEY`` / ``AGENTFOX_AUDIT_SIGNING_KEY``
and the old one as ``…_PREVIOUS``, run ``rotate``, check ``status``, then remove the
previous key. Output carries key fingerprints (first 8 hex of the SHA-256), never a
key. See docs/deployment/key-rotation.md.
"""

from __future__ import annotations

from typing import Any

import typer

from agentfox.apps.cli.commands._shared import _emit, _session, console

keys_app = typer.Typer(
    help="Rotate the token encryption and audit signing keys.", no_args_is_help=True
)

_STATE_COLOUR = {
    "complete": "green",
    "not_configured": "dim",
    "pending": "yellow",
    "misconfigured": "red",
}


def _state(value: str) -> str:
    return f"[{_STATE_COLOUR.get(value, 'white')}]{value}[/]"


def _print_report(report: dict[str, Any]) -> None:
    enc, sig = report["token_encryption"], report["audit_signing"]
    console.print(
        f"[bold]token encryption[/]  {_state(enc['state'])}  current "
        f"{enc['current'] or '(unset)'}  previous {', '.join(enc['previous']) or '(none)'}"
    )
    if enc.get("detail"):
        console.print(f"  [red]{enc['detail']}[/]")
    for field in enc["fields"]:
        if not field["rows"] and not field.get("error"):
            continue
        line = (
            f"  {field['field']}: {field['rows']} row(s), {field['on_current_key']} on the "
            f"current key, {field['on_previous_key']} on a previous key"
        )
        if not report["dry_run"]:
            line += f", {field['reencrypted']} re-encrypted"
        if field["undecryptable_ids"]:
            line += (
                f", [red]{len(field['undecryptable_ids'])} undecryptable (left untouched): "
                f"{', '.join(field['undecryptable_ids'])}[/]"
            )
        if field.get("error"):
            line += f"  [red]{field['error']}[/]"
        console.print(line)
    console.print(
        f"[bold]audit signing[/]     {_state(sig['state'])}  current {sig['current']}  "
        f"previous {', '.join(sig['previous']) or '(none)'}"
    )
    for item in sig["chains"]:
        line = (
            f"  chain {item['org_id']}: {item['checkpoints']} checkpoint(s), "
            f"{item['on_current_key']} on the current key, {item['on_previous_key']} on a "
            f"previous key"
        )
        if item["unverifiable"]:
            line += f", [red]{item['unverifiable']} verify under no configured key[/]"
        if not report["dry_run"]:
            line += f", {item['resigned']} re-signed"
        if item["state"] not in ("ok", "rotated"):
            line += f"  [red]{item['state']}[/]"
        console.print(line)


@keys_app.command("status")
def keys_status(as_json: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
    """Fingerprints in use, and whether any data or checkpoint still needs a previous key."""
    from agentfox.platform.keys.rotation import status

    with _session() as session:
        report = status(session)
    if as_json:
        _emit(report, True)
        return
    _print_report(report)
    states = {report["token_encryption"]["state"], report["audit_signing"]["state"]}
    if "pending" in states:
        console.print("[yellow]run `agentfox admin keys rotate` before removing a previous key[/]")
    elif "complete" in states and "misconfigured" not in states:
        console.print("[green]nothing needs a previous key any more; it can be removed[/]")


@keys_app.command("rotate")
def keys_rotate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; change nothing."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Re-encrypt stored secrets and re-sign audit checkpoints under the current keys.

    Values no configured key decrypts are reported and left untouched. A chain that
    fails verification is reported and not re-signed. Safe to run repeatedly.
    """
    from agentfox.platform.keys.rotation import rotate

    with _session() as session:
        report = rotate(session, dry_run=dry_run, actor_type="operator", actor_id="cli")
    if as_json:
        _emit(report, True)
    else:
        _print_report(report)
        enc, sig = report["token_encryption"], report["audit_signing"]
        console.print(
            ("[dim]dry run — nothing changed[/]" if dry_run else "")
            or f"re-encrypted {enc['reencrypted']} value(s), re-signed {sig['resigned']} "
            f"checkpoint(s), wrote {sig['entries_written']} audit entr"
            f"{'y' if sig['entries_written'] == 1 else 'ies'}"
        )
    if report["token_encryption"]["undecryptable"] or report["audit_signing"]["unverifiable"]:
        raise typer.Exit(1)

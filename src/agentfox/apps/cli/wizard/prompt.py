"""The questions `agentfox up` asks, and the two ways they get answered.

`Interactive` asks a person at a terminal. `Scripted` answers from flags and saved
answers and never reads stdin, which is what `--yes`, CI and the tests use. Both take
the same calls, so the wizard has one code path and cannot drift between "what a
person sees" and "what `--yes` does".

Choices are numbered rather than arrow-key driven: no new dependency, and it works the
same over SSH, in a CI log, in a Windows console and in a copied transcript.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from rich.console import Console
from rich.markup import escape


@dataclass(frozen=True)
class Choice:
    """One option. ``note`` explains it; ``disabled`` says why it cannot be picked."""

    key: str
    label: str
    note: str = ""
    disabled: str = ""


class Prompter(Protocol):
    def select(self, question: str, choices: Sequence[Choice], default: str) -> str: ...

    def multiselect(
        self, question: str, choices: Sequence[Choice], defaults: Sequence[str]
    ) -> list[str]: ...

    def text(self, question: str, default: str = "", *, secret: bool = False) -> str: ...

    def confirm(self, question: str, default: bool = True) -> bool: ...


def _selectable(choices: Sequence[Choice], keys: Sequence[str]) -> list[str]:
    allowed = {c.key for c in choices if not c.disabled}
    return [c.key for c in choices if c.key in allowed and c.key in set(keys)]


class Scripted:
    """Answers without asking: the recommended (or saved) default, echoed so a log
    shows what was decided."""

    def __init__(self, console: Console) -> None:
        self.console = console

    def _echo(self, question: str, answer: str) -> None:
        self.console.print(f"  [dim]{escape(question)}[/] {escape(answer)}")

    def select(self, question: str, choices: Sequence[Choice], default: str) -> str:
        label = next((c.label for c in choices if c.key == default), default)
        self._echo(question, label)
        return default

    def multiselect(
        self, question: str, choices: Sequence[Choice], defaults: Sequence[str]
    ) -> list[str]:
        picked = _selectable(choices, defaults)
        labels = [c.label for c in choices if c.key in picked]
        self._echo(question, ", ".join(labels) or "nothing")
        return picked

    def text(self, question: str, default: str = "", *, secret: bool = False) -> str:
        self._echo(question, "••••" if secret and default else default or "—")
        return default

    def confirm(self, question: str, default: bool = True) -> bool:
        self._echo(question, "yes" if default else "no")
        return default


class Interactive:
    """Asks at the terminal. Every question has a default; Enter accepts it."""

    def __init__(self, console: Console) -> None:
        self.console = console

    def _ask(self, prompt: str, *, secret: bool = False) -> str:
        return self.console.input(prompt, password=secret).strip()

    def _render(self, choices: Sequence[Choice], marks: dict[str, str]) -> None:
        for i, choice in enumerate(choices, 1):
            mark = marks.get(choice.key, "   ")
            if choice.disabled:
                self.console.print(
                    f"   [dim]{i:>2}. {mark} {escape(choice.label)} — {escape(choice.disabled)}[/]"
                )
                continue
            note = f"  [dim]{escape(choice.note)}[/]" if choice.note else ""
            self.console.print(f"   {i:>2}. {mark} [bold]{escape(choice.label)}[/]{note}")

    def _index(self, raw: str, choices: Sequence[Choice]) -> Choice | None:
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        for choice in choices:
            if raw.lower() in (choice.key.lower(), choice.label.lower()):
                return choice
        return None

    def select(self, question: str, choices: Sequence[Choice], default: str) -> str:
        self.console.print(f"\n[bold cyan]?[/] [bold]{escape(question)}[/]")
        self._render(
            choices, {c.key: "[cyan]›[/]  " if c.key == default else "   " for c in choices}
        )
        while True:
            raw = self._ask("   [dim]number, Enter for the marked one:[/] ")
            if not raw:
                return default
            choice = self._index(raw, choices)
            if choice is None:
                self.console.print(f"   [yellow]pick 1–{len(choices)}[/]")
            elif choice.disabled:
                self.console.print(f"   [yellow]{escape(choice.disabled)}[/]")
            else:
                return choice.key

    def multiselect(
        self, question: str, choices: Sequence[Choice], defaults: Sequence[str]
    ) -> list[str]:
        picked = set(_selectable(choices, defaults))
        self.console.print(f"\n[bold cyan]?[/] [bold]{escape(question)}[/]")
        while True:
            # Escaped: Rich reads a bare "[x]" as a markup tag and prints nothing.
            marks = {c.key: "[green]\\[x][/]" if c.key in picked else "\\[ ]" for c in choices}
            self._render(choices, marks)
            raw = self._ask(
                "   [dim]numbers to toggle (e.g. 2 5), a = all, n = none, Enter to continue:[/] "
            )
            if not raw:
                return [c.key for c in choices if c.key in picked]
            if raw.lower() in ("a", "all"):
                picked = set(_selectable(choices, [c.key for c in choices]))
                continue
            if raw.lower() in ("n", "none"):
                picked.clear()
                continue
            for word in raw.replace(",", " ").split():
                choice = self._index(word, choices)
                if choice is None:
                    self.console.print(f"   [yellow]no option {escape(word)}[/]")
                elif choice.disabled:
                    self.console.print(
                        f"   [yellow]{escape(choice.label)}: {escape(choice.disabled)}[/]"
                    )
                else:
                    picked ^= {choice.key}

    def text(self, question: str, default: str = "", *, secret: bool = False) -> str:
        shown = (
            (" [dim](saved, Enter keeps it)[/]" if secret else f" [dim]({escape(default)})[/]")
            if default
            else ""
        )
        raw = self._ask(f"\n[bold cyan]?[/] [bold]{escape(question)}[/]{shown} ", secret=secret)
        return raw or default

    def confirm(self, question: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            raw = self._ask(
                f"\n[bold cyan]?[/] [bold]{escape(question)}[/] [dim]{hint}[/] "
            ).lower()
            if not raw:
                return default
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False

"""Jedi-backed completion and live call-signature hints."""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Callable, Iterable

import jedi
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter
from prompt_toolkit.document import Document

from ember import signature
from ember.magics import CELL_MAGICS, LINE_MAGICS
from ember.signature import SigInfo
from ember.transform import HELP_RE, MAGIC_RE, SHELL_RE

if TYPE_CHECKING:
    from ember.shell import Shell

jedi.settings.case_insensitive_completion = False
jedi.settings.add_bracket_after_function = False

ICONS = {
    "function": ("ƒ", "function"),
    "class": ("◇", "class"),
    "module": ("▣", "module"),
    "keyword": ("⌘", "keyword"),
    "instance": ("●", "instance"),
    "statement": ("●", "instance"),
    "param": ("○", "instance"),
    "property": ("◦", "instance"),
    "path": ("⌁", "path"),
    "magic": ("✦", "magic"),
}

_PATH_MAGICS = ("run", "cd", "ls", "load", "edit", "writefile", "save")
_WORD_CHAR = re.compile(r"[\w.]")


def _jedi_source(text: str) -> str:
    """Blank out shell-syntax lines so jedi sees valid Python with the same geometry."""
    out = []
    for line in text.split("\n"):
        if MAGIC_RE.match(line) or SHELL_RE.match(line) or HELP_RE.match(line):
            indent = len(line) - len(line.lstrip())
            out.append(" " * indent + "pass")
        else:
            out.append(line)
    return "\n".join(out)


class EmberCompleter(Completer):
    def __init__(self, shell: Shell):
        self.shell = shell
        self.paths = PathCompleter(expanduser=True)

    def get_completions(self, document: Document, event: CompleteEvent) -> Iterable[Completion]:
        line = document.current_line_before_cursor
        if not event.completion_requested:
            # While typing, only pop up after an identifier char or a dot.
            if not line or not _WORD_CHAR.match(line[-1]):
                return
            word = re.search(r"[\w]*$", line)
            if line[-1] != "." and word and len(word.group()) < 2:
                return

        if m := re.match(r"^\s*(%%?)(\w*)$", line):
            prefix, typed = m.groups()
            table = CELL_MAGICS if prefix == "%%" else LINE_MAGICS
            for name, (_, doc) in sorted(table.items()):
                if name.startswith(typed):
                    yield self._item(prefix + name, -len(prefix + typed), "magic", doc)
            return

        if m := re.match(r"^\s*(?:%(?:" + "|".join(_PATH_MAGICS) + r")\s+|!\s*\S+\s+(?:.*\s)?)(\S*)$", line):
            yield from self._paths(m.group(1), event)
            return

        yield from self._jedi(document)

    def _paths(self, fragment: str, event: CompleteEvent) -> Iterable[Completion]:
        for c in self.paths.get_completions(Document(fragment), event):
            text = fragment[: len(fragment) + c.start_position] + c.text
            yield self._item(text, -len(fragment), "path", "", display=c.display_text)

    def _jedi(self, document: Document) -> Iterable[Completion]:
        try:
            script = jedi.Interpreter(_jedi_source(document.text), [self.shell.ns])
            completions = script.complete(document.cursor_position_row + 1, document.cursor_position_col)
        except Exception:
            return
        word = re.search(r"\w*$", document.current_line_before_cursor).group()
        for c in completions:
            name = c.name_with_symbols
            if name.startswith("_") and not word.startswith("_"):
                continue
            try:
                prefix_len = c.get_completion_prefix_length()
            except Exception:
                prefix_len = len(word)
            kind = c.type if c.type in ICONS else "instance"
            if c.type == "path":
                kind = "path"
            yield self._item(name, -prefix_len, kind, c.type)

    @staticmethod
    def _item(text: str, start: int, kind: str, meta: str, display: str | None = None) -> Completion:
        icon, cls = ICONS.get(kind, ICONS["instance"])
        return Completion(
            text,
            start_position=start,
            display=[(f"class:comp.icon.{cls}", f"{icon} "), ("", display or text)],
            display_meta=meta,
        )


class SignatureHinter:
    """Computes call signatures on a background thread so typing never blocks."""

    def __init__(self, shell: Shell, on_update: Callable[[], None]):
        self.shell = shell
        self.on_update = on_update
        self.current: SigInfo | None = None
        self._request: tuple[str, int, int] | None = None
        self._cond = threading.Condition()
        threading.Thread(target=self._run, name="ember-signatures", daemon=True).start()

    def request(self, document: Document) -> None:
        with self._cond:
            self._request = (document.text, document.cursor_position_row, document.cursor_position_col)
            self._cond.notify()

    def clear(self) -> None:
        with self._cond:
            self._request = None
        self.current = None

    def _run(self) -> None:
        last: tuple[str, int, int] | None = None
        while True:
            with self._cond:
                while self._request is None or self._request == last:
                    self._cond.wait()
                req = last = self._request
            text, row, col = req
            try:
                result = self._compute(text, row, col)
            except Exception:
                result = None
            if result != self.current:
                self.current = result
                self.on_update()

    def _compute(self, text: str, row: int, col: int) -> SigInfo | None:
        line = text.split("\n")[row][:col]
        if "(" not in text or MAGIC_RE.match(line) or SHELL_RE.match(line):
            return None
        sigs = jedi.Interpreter(_jedi_source(text), [self.shell.ns]).get_signatures(row + 1, col)
        return signature.build(sigs[0], text, self.shell.ns) if sigs else None

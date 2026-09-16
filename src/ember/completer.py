"""Jedi-backed completion and live call-signature hints."""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any, Callable, Iterable

import jedi
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter
from prompt_toolkit.document import Document

from ember import signature
from ember.latex import LATEX_SYMBOLS, REVERSE_SYMBOLS, unicode_names
from ember.magics import CELL_MAGICS, LINE_MAGICS
from ember.signature import SigInfo
from ember.transform import HELP_RE, MAGIC_RE, SHELL_RE
from ember.utils import resolve_name

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

_PATH_MAGICS = ("run", "cd", "ls", "load", "edit", "save", "pushd", "bookmark", "logstart", "pfile")
_LATEX = re.compile(r"\\([A-Za-z0-9_^+\-=()]*)$")
_REVERSE_LATEX = re.compile(r"\\([^\x00-\x7f])$")
_UNICODE_NAME = re.compile(r"\\N\{([A-Za-z0-9 \-]*)$")
_SUBSCRIPT = re.compile(r"(?P<expr>[A-Za-z_][\w.]*)\[\s*(?:(?P<quote>['\"])(?P<typed>[^'\"]*))?$")


def _keys_of(obj: Any) -> list[Any] | None:
    from collections.abc import Mapping

    try:
        if isinstance(obj, Mapping):
            return list(obj.keys())
        module = type(obj).__module__.split(".")[0]
        if module == "pandas" and hasattr(obj, "columns"):
            return list(obj.columns)
        if module == "pandas" and type(obj).__name__ == "Series":
            return list(obj.index)
        if module == "numpy" and getattr(getattr(obj, "dtype", None), "names", None):
            return list(obj.dtype.names)
    except Exception:
        return None
    return None
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
        if event.completion_requested and (latex := list(self._latex(line))):
            yield from latex
            return
        if (keys := self._dict_keys(line)) is not None:
            yield from keys
            return
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
            for name, spec in sorted(table.items()):
                if name.startswith(typed):
                    yield self._item(prefix + name, -len(prefix + typed), "magic", spec.doc)
            return

        if m := re.match(r"^\s*(?:%(?:" + "|".join(_PATH_MAGICS) + r")\s+|!\s*\S+\s+(?:.*\s)?)(\S*)$", line):
            yield from self._paths(m.group(1), event)
            return

        yield from self._jedi(document)

    def _latex(self, line: str) -> Iterable[Completion]:
        if m := _UNICODE_NAME.search(line):
            typed = m.group(1).upper()
            shown = 0
            for name, char in unicode_names():
                if name.startswith(typed):
                    yield Completion(char, start_position=-len(m.group(0)), display=[("class:comp.icon.keyword", f"{char}  "), ("", name)])
                    shown += 1
                    if shown >= 200:
                        break
            return
        if m := _REVERSE_LATEX.search(line):
            if name := REVERSE_SYMBOLS.get(m.group(1)):
                yield Completion("\\" + name, start_position=-len(m.group(0)), display=f"\\{name}")
            return
        if m := _LATEX.search(line):
            typed = m.group(1)
            matches = sorted((n for n in LATEX_SYMBOLS if n.startswith(typed)), key=lambda n: (n != typed, len(n), n))
            for name in matches:
                char = LATEX_SYMBOLS[name]
                yield Completion(char, start_position=-len(m.group(0)),
                                 display=[("class:comp.icon.keyword", f"{char}  "), ("", "\\" + name)])

    def _dict_keys(self, line: str) -> Iterable[Completion] | None:
        """Complete `d["k` / `df['co` / `d[` from the live object's keys (None = not a subscript)."""
        m = _SUBSCRIPT.search(line)
        if not m:
            return None
        expr, quote, typed = m.group("expr"), m.group("quote"), m.group("typed") or ""
        try:
            obj = resolve_name(expr, self.shell.ns)
        except LookupError:
            return None
        keys = _keys_of(obj)
        if keys is None:
            return None
        items: list[Completion] = []
        for key in keys[:1000]:
            if quote:
                if not isinstance(key, str) or not key.startswith(typed):
                    continue
                text = key.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote + "]"
                items.append(self._item(text, -len(typed), "instance", type(key).__name__, display=repr(key)))
            else:
                items.append(self._item(repr(key) + "]", 0, "instance", type(key).__name__, display=repr(key)))
        return items

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

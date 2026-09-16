"""A compact implementation of IPython's `lib.pretty` printer API (`_repr_pretty_(p, cycle)`)."""

from __future__ import annotations

import io
from contextlib import contextmanager
from typing import Any, Callable, Iterator

Printer = Callable[[Any, "RepresentationPrinter", bool], None]

CANARY = "_ipython_canary_method_should_not_exist_"


def get_real_method(obj: Any, name: str) -> Callable | None:
    """Look a protocol method up on the type, guarding against objects that claim every attribute."""
    if isinstance(obj, type):
        return None
    try:
        if hasattr(type(obj), "__getattr__") and hasattr(obj, CANARY):
            return None
    except Exception:
        return None
    method = getattr(type(obj), name, None)
    if method is None or not callable(method):
        return None
    return lambda *args, **kw: method(obj, *args, **kw)


class RepresentationPrinter:
    def __init__(self, output: io.StringIO | None = None, max_width: int = 79, newline: str = "\n",
                 max_seq_length: int = 1000, type_printers: dict[type, Printer] | None = None,
                 deferred_printers: dict[tuple[str, str], Printer] | None = None):
        self.output = output or io.StringIO()
        self.max_width = max_width
        self.newline = newline
        self.max_seq_length = max_seq_length
        self.type_printers = type_printers or {}
        self.deferred_printers = deferred_printers or {}
        self.indentation = 0
        self._line_len = 0
        self._stack: list[int] = []

    # ── low level ─────────────────────────────────────────────────────────

    def text(self, obj: str) -> None:
        obj = str(obj)
        self.output.write(obj)
        if "\n" in obj:
            self._line_len = len(obj) - obj.rfind("\n") - 1
        else:
            self._line_len += len(obj)

    def breakable(self, sep: str = " ") -> None:
        if self._line_len >= self.max_width:
            self.break_()
        else:
            self.text(sep)

    def break_(self) -> None:
        self.output.write(self.newline + " " * self.indentation)
        self._line_len = self.indentation

    def begin_group(self, indent: int = 0, open: str = "") -> None:
        if open:
            self.text(open)
        self.indentation += indent

    def end_group(self, dedent: int = 0, close: str = "") -> None:
        self.indentation -= dedent
        if close:
            self.text(close)

    @contextmanager
    def group(self, indent: int = 0, open: str = "", close: str = "") -> Iterator[None]:
        self.begin_group(indent, open)
        try:
            yield
        finally:
            self.end_group(indent, close)

    @contextmanager
    def indent(self, indent: int) -> Iterator[None]:
        self.indentation += indent
        try:
            yield
        finally:
            self.indentation -= indent

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self.output.getvalue()

    # ── high level ────────────────────────────────────────────────────────

    def _printer_for(self, obj: Any) -> Printer | None:
        for cls in type(obj).__mro__:
            if cls in self.type_printers:
                return self.type_printers[cls]
            key = (cls.__module__, cls.__name__)
            if key in self.deferred_printers:
                printer = self.deferred_printers.pop(key)
                self.type_printers[cls] = printer
                return printer
        return None

    def pretty(self, obj: Any) -> None:
        cycle = id(obj) in self._stack
        self._stack.append(id(obj))
        try:
            if (printer := self._printer_for(obj)) is not None:
                printer(obj, self, cycle)
                return
            if (method := get_real_method(obj, "_repr_pretty_")) is not None:
                method(self, cycle)
                return
            if type(obj) in (list, tuple, set, frozenset):
                self._sequence(obj, cycle)
            elif type(obj) is dict:
                self._dict(obj, cycle)
            else:
                self.text(repr(obj))
        finally:
            self._stack.pop()

    def _sequence(self, obj: Any, cycle: bool) -> None:
        open_, close = {list: ("[", "]"), tuple: ("(", ")"), set: ("{", "}"), frozenset: ("frozenset({", "})")}[type(obj)]
        if cycle:
            self.text(open_ + "..." + close)
            return
        if not obj and type(obj) is set:
            self.text("set()")
            return
        with self.group(1, open_, close):
            for i, item in enumerate(obj):
                if i >= self.max_seq_length:
                    self.text(",")
                    self.breakable()
                    self.text("...")
                    break
                if i:
                    self.text(",")
                    self.breakable()
                self.pretty(item)
            if type(obj) is tuple and len(obj) == 1:
                self.text(",")

    def _dict(self, obj: dict, cycle: bool) -> None:
        if cycle:
            self.text("{...}")
            return
        with self.group(1, "{", "}"):
            for i, (key, value) in enumerate(obj.items()):
                if i:
                    self.text(",")
                    self.breakable()
                self.pretty(key)
                self.text(": ")
                self.pretty(value)


PrettyPrinter = RepresentationPrinter


def pretty(obj: Any, verbose: bool = False, max_width: int = 79, newline: str = "\n", max_seq_length: int = 1000,
           type_printers: dict | None = None, deferred_printers: dict | None = None) -> str:
    printer = RepresentationPrinter(None, max_width, newline, max_seq_length, type_printers, deferred_printers)
    printer.pretty(obj)
    return printer.getvalue()


def pprint(obj: Any, verbose: bool = False, max_width: int = 79, newline: str = "\n", max_seq_length: int = 1000) -> None:
    print(pretty(obj, verbose, max_width, newline, max_seq_length))

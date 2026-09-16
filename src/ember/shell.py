"""The execution engine: namespace, cell execution, output capture and cell chrome."""

from __future__ import annotations

import ast
import asyncio
import builtins
import difflib
import importlib
import inspect
import linecache
import os
import shutil
import sys
import time
import types
from contextlib import contextmanager
from types import CodeType, TracebackType
from typing import Any, Iterator

from rich.console import Console, RenderableType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ember import display
from ember.magics import CELL_MAGICS, LINE_MAGICS, MagicError, _stream
from ember.output import RailState, RailWriter, Spinner, format_duration
from ember.theme import Theme, get_theme
from ember.transform import API, transform

FLAGS = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT


class AutoReloader:
    def __init__(self) -> None:
        self.enabled = False
        self.mtimes: dict[str, float] = {}
        self._skip = tuple({sys.prefix, sys.base_prefix, sys.exec_prefix, display.PKG_DIR})

    def _modules(self) -> Iterator[tuple[str, types.ModuleType, str]]:
        for name, mod in list(sys.modules.items()):
            file = getattr(mod, "__file__", None)
            if not file or not file.endswith(".py") or file.startswith(self._skip) or "site-packages" in file:
                continue
            yield name, mod, file

    def snapshot(self) -> None:
        self.mtimes = {}
        for name, _, file in self._modules():
            try:
                self.mtimes[name] = os.path.getmtime(file)
            except OSError:
                pass

    def check(self) -> list[str]:
        reloaded = []
        for name, mod, file in self._modules():
            try:
                mtime = os.path.getmtime(file)
            except OSError:
                continue
            old = self.mtimes.get(name)
            self.mtimes[name] = mtime
            if old is not None and mtime > old:
                try:
                    importlib.reload(mod)
                    reloaded.append(name)
                except Exception:
                    pass
        return reloaded


class EmberAPI:
    """Exposed to user code as `__ember__`; transformed shell syntax calls into this."""

    def __init__(self, shell: Shell):
        self._shell = shell

    def magic(self, name: str, args: str) -> Any:
        if name not in LINE_MAGICS:
            close = difflib.get_close_matches(name, LINE_MAGICS, n=1)
            raise MagicError(f"unknown magic %{name}" + (f" — did you mean %{close[0]}?" if close else ""))
        return LINE_MAGICS[name][0](self._shell, args)

    def cell_magic(self, name: str, args: str, body: str) -> Any:
        if name not in CELL_MAGICS:
            close = difflib.get_close_matches(name, CELL_MAGICS, n=1)
            raise MagicError(f"unknown cell magic %%{name}" + (f" — did you mean %%{close[0]}?" if close else ""))
        return CELL_MAGICS[name][0](self._shell, args, body)

    def shell(self, cmd: str, capture: bool = False) -> list[str] | None:
        try:
            cmd = cmd.format_map(self._shell.ns)
        except Exception:
            pass
        return _stream(self._shell, cmd, capture=capture)

    def inspect(self, expr: str, level: int) -> None:
        try:
            obj = eval(expr, self._shell.ns)
        except NameError:
            raise MagicError(f"{expr} is not defined") from None
        except AttributeError as e:
            raise MagicError(str(e)) from None
        self._shell.print(display.render_inspect(expr, obj, level, self._shell.theme))


class Shell:
    def __init__(self, theme: str | None = None):
        self.theme: Theme = get_theme(theme)
        self.In: list[str] = [""]
        self.Out: dict[int, Any] = {}
        self.count = 0
        self.last_duration: float | None = None
        self.last_ok = True
        self.last_traceback: TracebackType | None = None
        self.next_input = ""
        self.prev_dir: str | None = None
        self.suppress_footer = False
        self.current_filename = "<cell>"
        self.autoreload = AutoReloader()
        self.loop = asyncio.new_event_loop()

        self.module = types.ModuleType("__main__")
        self.ns: dict[str, Any] = self.module.__dict__
        self.ns.update({"__builtins__": builtins, "In": self.In, "Out": self.Out, API: EmberAPI(self)})
        self.initial_names = set(self.ns)
        sys.modules["__main__"] = self.module
        if "" not in sys.path:
            sys.path.insert(0, "")

        self.ui = self._make_console(sys.__stdout__)
        self._out: Console | None = None
        self._spinner: Spinner | None = None

    # ── consoles ──────────────────────────────────────────────────────────

    def _make_console(self, file, width: int | None = None) -> Console:
        return Console(
            file=file,
            theme=self.theme.rich_theme,
            width=width,
            highlight=True,
            force_terminal=sys.__stdout__.isatty() or None,
        )

    @property
    def width(self) -> int:
        return shutil.get_terminal_size((100, 24)).columns

    def set_theme(self, name: str) -> None:
        self.theme = get_theme(name)
        self.ui = self._make_console(sys.__stdout__)
        if self._out is not None:
            self._out = self._make_console(self._out.file, self._out.width)

    def print(self, renderable: RenderableType | str, end: str = "\n") -> None:
        (self._out or self.ui).print(renderable, end=end)

    def pause_output(self) -> None:
        """Stop the spinner before handing the terminal to something interactive."""
        if self._spinner:
            self._spinner.stop()

    def _ansi(self, *parts: tuple[str, str]) -> str:
        with self.ui.capture() as cap:
            self.ui.print(Text.assemble(*parts), end="")
        return cap.get()

    # ── execution ─────────────────────────────────────────────────────────

    def run_code(self, code: CodeType) -> Any:
        if code.co_flags & inspect.CO_COROUTINE:
            return self.loop.run_until_complete(eval(code, self.ns))
        return eval(code, self.ns)

    def execute(self, source: str, filename: str) -> Any:
        """Execute (already transformed) source; return the value of a trailing expression."""
        tree = ast.parse(source, filename=filename)
        last = None
        if tree.body and isinstance(tree.body[-1], ast.Expr) and not source.rstrip().endswith(";"):
            last = ast.Expression(tree.body.pop().value)
        if tree.body:
            self.run_code(compile(tree, filename, "exec", flags=FLAGS))
        if last is not None:
            return self.run_code(compile(last, filename, "eval", flags=FLAGS))
        return None

    @contextmanager
    def _capture(self) -> Iterator[RailState]:
        real_out, real_err = sys.__stdout__, sys.__stderr__
        state = RailState(self._ansi(("│ ", "ember.border")))
        spinner = Spinner(
            real_out,
            state,
            lambda frame, elapsed: self._ansi(
                ("╰─ ", "ember.border"), (frame, "ember.accent"), (" running ", "ember.muted"),
                (format_duration(elapsed), "ember.faint"), ("  ctrl+c to interrupt", "ember.faint"),
            ),
        )
        out = RailWriter(real_out, state, spinner)
        err = RailWriter(real_err, state, spinner)
        saved = sys.stdout, sys.stderr, builtins.input
        real_input = builtins.input

        def _input(prompt: object = "") -> str:
            spinner.stop()
            return real_input(prompt)

        sys.stdout, sys.stderr, builtins.input = out, err, _input
        self._out = self._make_console(out, width=max(20, self.width - 2))
        self._spinner = spinner
        spinner.start()
        try:
            yield state
        finally:
            spinner.stop()
            sys.stdout, sys.stderr, builtins.input = saved
            self._out = None
            self._spinner = None
            if not state.at_line_start:
                real_out.write("\n")
            if state.wrote:
                real_out.write(state.prefix.rstrip() + "\n")  # breathing room above the footer
            real_out.flush()

    def run_cell(self, source: str) -> None:
        source = source.rstrip().lstrip("\n")
        if not source.strip():
            return
        if source.strip() in ("exit", "quit"):
            raise SystemExit(0)

        self.count += 1
        n = self.count
        self.In.append(source)
        self.ns["_i"] = source
        self.suppress_footer = False
        filename = self.current_filename = f"<cell-{n}>"
        lines = [ln + "\n" for ln in source.splitlines()]
        for name in (filename, display.cell_label(n)):
            linecache.cache[name] = (len(source), None, lines, name)

        self.echo(source)
        result: Any = None
        error: str | None = None
        start = time.perf_counter()
        with self._capture():
            try:
                if self.autoreload.enabled and (reloaded := self.autoreload.check()):
                    self.print(Text(f"↻ reloaded {', '.join(reloaded)}", style="ember.faint"))
                result = self.execute(transform(source), filename)
                if result is not None:
                    self._store(n, result)
                    self.print(display.render_value(result))
            except SystemExit:
                raise
            except MagicError as e:
                error = "failed"
                self.print(Text.assemble(("✗ ", "ember.err"), (str(e), "ember.fg")))
            except BaseException as e:
                error = type(e).__name__
                if not isinstance(e, KeyboardInterrupt):
                    sys.last_type, sys.last_value, sys.last_traceback = type(e), e, e.__traceback__
                    self.last_traceback = e.__traceback__
                assert self._out is not None
                self.print(display.render_exception(type(e), e, e.__traceback__, self.theme, self._out.width))
        elapsed = time.perf_counter() - start
        self.last_duration, self.last_ok = elapsed, error is None
        if not self.suppress_footer:
            self.footer(n, elapsed, result, error)

    def _store(self, n: int, value: Any) -> None:
        self.Out[n] = value
        ns = self.ns
        ns["___"], ns["__"], ns["_"] = ns.get("__"), ns.get("_"), value
        ns[f"_{n}"] = value

    # ── chrome ────────────────────────────────────────────────────────────

    def echo(self, source: str) -> None:
        grid = Table.grid(padding=0)
        grid.add_column(width=2, no_wrap=True)
        grid.add_column(ratio=1)
        stripped = source.lstrip()
        if stripped.startswith("!") and "\n" not in stripped:
            body: RenderableType = Text.assemble(("!", "ember.accent.bold"), (stripped[1:], "ember.fg"))
        else:
            body = Syntax(source, "python", theme=self.theme.syntax_theme, background_color="default", word_wrap=True)
        grid.add_row(Text("❯", style="ember.accent.bold"), body)
        self.ui.print(grid)

    def footer(self, n: int, elapsed: float, result: Any, error: str | None) -> None:
        parts: list[tuple[str, str]] = [("╰─ ", "ember.border")]
        if error:
            parts += [("✗ ", "ember.err.bold"), (error, "ember.err")]
        else:
            parts += [("✓ ", "ember.ok")]
        if error:
            parts += [(" · ", "ember.faint")]
        parts += [(format_duration(elapsed), "ember.muted")]
        if result is not None and not error:
            parts += [(" · ", "ember.faint"), (display.describe(result), "ember.muted"), (" · ", "ember.faint"), (f"Out[{n}]", "ember.faint")]
        self.ui.print(Text.assemble(*parts))
        self.ui.print("\n")

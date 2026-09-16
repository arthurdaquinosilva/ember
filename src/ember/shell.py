"""The execution engine: namespace, cell execution, output capture and cell chrome."""

from __future__ import annotations

import ast
import asyncio
import builtins
import difflib
import hashlib
import inspect
import keyword
import linecache
import os
import pdb
import re
import shutil
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path
from types import CodeType, TracebackType
from typing import Any, Callable, ClassVar, Iterator

from rich.console import Console, RenderableType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ember import display, inputhooks, ipython
from ember.autoreload import AutoReloader
from ember.config import Profile, Settings
from ember.history import HistoryManager
from ember.ipython.display import display as display_function
from ember.ipython.shell import EmberInteractiveShell, ExecutionInfo, ExecutionResult
from ember.magics import CELL_MAGICS, LINE_MAGICS, MagicError
from ember.output import RailState, RailWriter, Spinner, format_duration
from ember.theme import PALETTES, Theme, get_theme
from ember.transform import API, strip_prompts, transform
from ember.utils import SList, expand_vars


class EmberAPI:
    """Exposed to user code as `__ember__`; transformed shell syntax calls into this."""

    def __init__(self, shell: Shell):
        self._shell = shell

    def _lookup(self, table: dict, name: str, prefix: str):
        spec = table.get(name)
        if spec is None:
            close = difflib.get_close_matches(name, table, n=1)
            raise MagicError(f"unknown magic {prefix}{name}" + (f" — did you mean {prefix}{close[0]}?" if close else ""))
        return spec

    def magic(self, name: str, args: str) -> Any:
        spec = self._lookup(LINE_MAGICS, name, "%")
        shell = self._shell
        shell.current_magic = name
        if spec.expand:
            args = expand_vars(args, shell.ns)
        return spec.fn(shell, args)

    def cell_magic(self, name: str, args: str, body: str) -> Any:
        spec = self._lookup(CELL_MAGICS, name, "%%")
        shell = self._shell
        shell.current_magic = name
        if spec.expand:
            args = expand_vars(args, shell.ns)
        return spec.fn(shell, args, body)

    def shell(self, cmd: str, capture: bool = False) -> SList | None:
        if capture:
            return self._shell.getoutput(cmd)
        self._shell.system(cmd)
        return None

    def inspect(self, expr: str, level: int) -> None:
        try:
            obj = eval(expr, self._shell.ns)
        except NameError:
            raise MagicError(f"{expr} is not defined") from None
        except AttributeError as e:
            raise MagicError(str(e)) from None
        self._shell.print(display.render_inspect(expr, obj, level, self._shell.theme))

    def psearch(self, pattern: str) -> None:
        from ember.magics.namespace import psearch

        self._shell.print(psearch(self._shell, pattern))


class Shell:
    active: ClassVar[Shell | None] = None

    def __init__(self, settings: Settings | None = None, profile: Profile | None = None):
        self.settings = settings or Settings()
        self.profile = profile
        self.theme: Theme = get_theme(self.settings.theme)
        self.In: list[str] = [""]
        self.Out: dict[int, Any] = {}
        self.count = 0
        self.last_duration: float | None = None
        self.last_ok = True
        self.last_exception: BaseException | None = None
        self.next_input = ""
        self.prev_dir: str | None = None
        self.suppress_footer = False
        self.current_filename = "<cell>"
        self.current_magic = ""
        self.exit_requested = False
        self.doctest_mode = False
        self.starting_dir = os.getcwd()
        self.dir_history: list[str] = [self.starting_dir]
        self.dir_stack: list[str] = []
        self.aliases: dict[str, str] = {}
        self.bg_processes: list[Any] = []
        self.logger: Any = None
        self.float_format = ""
        self.inputhook: Callable | None = None
        self.gui: str | None = None
        self.autoreload = AutoReloader()
        self.autoreload.mode = self.settings.autoreload
        self.loop = asyncio.new_event_loop()
        self.history = HistoryManager(profile.history_db if profile else None)
        self.api = EmberAPI(self)
        self.ipy = EmberInteractiveShell(self)

        self.module = types.ModuleType("__main__")
        self.ns: dict[str, Any] = self.module.__dict__
        self.ns.update({
            "__builtins__": builtins, "In": self.In, "Out": self.Out, "_ih": self.In, "_oh": self.Out,
            "_dh": self.dir_history, API: self.api, "get_ipython": ipython.get_ipython, "display": display_function,
        })
        self.initial_names = set(self.ns)
        sys.modules["__main__"] = self.module
        if "" not in sys.path:
            sys.path.insert(0, "")

        self.ui = self._make_console(sys.__stdout__)
        self._out: Console | None = None
        self._spinner: Spinner | None = None
        self._display_sink: list[Any] | None = None
        self._last_displayed: Any = None
        self._depth = 0
        Shell.active = self
        ipython.install(self.ipy)
        if self.settings.precision:
            self._apply_precision(self.settings.precision)

    # ── consoles & settings ───────────────────────────────────────────────

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

    @property
    def compile_flags(self) -> int:
        return ast.PyCF_ALLOW_TOP_LEVEL_AWAIT if self.settings.autoawait != "off" else 0

    def set_theme(self, name: str) -> None:
        self.set_setting("theme", name)

    def set_setting(self, name: str, value: Any) -> None:
        if isinstance(value, str) or not isinstance(value, (list, dict)):
            value = self.settings.validate(name, value)
        if name == "theme":
            if value not in PALETTES:
                raise ValueError(f"unknown theme {value!r} — try: {', '.join(PALETTES)}")
            self.theme = get_theme(value)
            self.ui = self._make_console(sys.__stdout__)
            if self._out is not None:
                self._out = self._make_console(self._out.file, self._out.width)
        elif name == "precision":
            self._apply_precision(value)
        elif name == "autoreload":
            self.autoreload.mode = value
            if value:
                self.autoreload.snapshot()
        elif name == "gui":
            self.enable_gui(value or None)
        setattr(self.settings, name, value)

    def _apply_precision(self, fmt: str) -> None:
        fmt = fmt.strip()
        digits: int | None = None
        if not fmt:
            self.float_format = ""
        elif fmt.isdigit():
            digits = int(fmt)
            self.float_format = f"%.{digits}f"
        elif "%" in fmt:
            try:
                fmt % 3.14159
            except (TypeError, ValueError):
                raise ValueError(f"invalid float format {fmt!r}") from None
            self.float_format = fmt
        else:
            raise ValueError("precision must be a number of digits or a %-format like %.3e")
        if "numpy" in sys.modules:
            try:
                sys.modules["numpy"].set_printoptions(precision=8 if digits is None else digits)
            except Exception:
                pass

    # ── output ────────────────────────────────────────────────────────────

    def print(self, renderable: RenderableType | str, end: str = "\n") -> None:
        if self._display_sink is not None:
            self._display_sink.append(renderable)
            return
        (self._out or self.ui).print(renderable, end=end)

    def render(self, value: Any) -> RenderableType:
        if self.doctest_mode:
            return Text(repr(value))
        return display.render_value(value, self.float_format, self.ipy.display_formatter.plain)

    def render_display(self, obj: Any) -> RenderableType | None:
        from ember.ipython.pretty import get_real_method

        if (method := get_real_method(obj, "_ipython_display_")) is not None:
            method()
            return None
        return self.render(obj)

    def print_value(self, value: Any) -> None:
        if value is not None:
            self.print(self.render(value))

    @contextmanager
    def capture_displays(self, sink: list[Any] | None) -> Iterator[None]:
        if sink is None:
            yield
            return
        saved, self._display_sink = self._display_sink, sink
        try:
            yield
        finally:
            self._display_sink = saved

    def page(self, renderable: RenderableType) -> None:
        if not sys.__stdout__.isatty():
            self.print(renderable)
            return
        self.pause_output()
        with self.ui.pager(styles=True):
            self.ui.print(renderable)

    def pause_output(self) -> None:
        """Stop the spinner before handing the terminal to something interactive."""
        if self._spinner:
            self._spinner.stop()

    def _ansi(self, *parts: tuple[str, str]) -> str:
        with self.ui.capture() as cap:
            self.ui.print(Text.assemble(*parts), end="")
        return cap.get()

    # ── namespace helpers ─────────────────────────────────────────────────

    def user_vars(self) -> dict[str, Any]:
        return {k: v for k, v in self.ns.items() if not k.startswith("_") and k not in self.initial_names}

    def xdel(self, name: str) -> None:
        obj = self.ns.pop(name)
        for key, value in list(self.Out.items()):
            if value is obj:
                del self.Out[key]
        for key in [k for k in self.ns if re.fullmatch(r"_+|_\d+", k)]:
            if self.ns[key] is obj:
                del self.ns[key]

    def clear_output_cache(self) -> None:
        self.Out.clear()
        for key in [k for k in self.ns if re.fullmatch(r"_{1,3}|_\d+", k)]:
            del self.ns[key]

    def _automagic(self, name: str) -> bool:
        return (
            self.settings.automagic
            and name in LINE_MAGICS
            and name not in self.ns
            and not hasattr(builtins, name)
            and not keyword.iskeyword(name)
        )

    def transform(self, source: str) -> str:
        def apply(transformers: list, text: str) -> str:
            if not transformers:
                return text
            lines = [ln + "\n" for ln in text.split("\n")]
            for t in transformers:
                lines = t(lines)
            return "".join(lines).removesuffix("\n")

        source = apply(self.ipy.input_transformers_cleanup, source)
        source = transform(source, self._automagic)
        return apply(self.ipy.input_transformers_post, source)

    def system(self, cmd: str) -> int:
        from ember.magics.osm import run_command

        return run_command(self, expand_vars(cmd, self.ns))  # type: ignore[return-value]

    def getoutput(self, cmd: str) -> SList:
        from ember.magics.osm import run_command

        return run_command(self, expand_vars(cmd, self.ns), capture=True)  # type: ignore[return-value]

    # ── gui ───────────────────────────────────────────────────────────────

    def enable_gui(self, name: str | None) -> None:
        gui = inputhooks.normalize_gui(name)
        if gui in (None, "", "none", "headless", "inline", "agg"):
            self.inputhook, self.gui = None, None
            self.settings.gui = ""
            return
        self.inputhook = inputhooks.make_hook(gui, self)
        self.gui = gui
        self.settings.gui = gui

    def enable_matplotlib(self, name: str | None = None) -> tuple[str | None, str]:
        import matplotlib

        if name:
            key = name.lower()
            gui = inputhooks.normalize_gui(key)
            backend = inputhooks.GUI_BACKEND.get(key) or inputhooks.GUI_BACKEND.get(gui or "") or name
        else:
            backend = matplotlib.get_backend()
        import matplotlib.pyplot as plt

        plt.switch_backend(backend)
        backend = matplotlib.get_backend()
        gui = inputhooks.BACKEND_GUI.get(backend.lower())
        self.enable_gui(gui)
        plt.ion()
        self.settings.matplotlib = backend
        return gui, backend

    # ── debugging & errors ────────────────────────────────────────────────

    def debugger(self) -> pdb.Pdb:
        debugger = pdb.Pdb()
        debugger.prompt = "(ember-pdb) "
        return debugger

    def post_mortem(self, tb: TracebackType | None) -> None:
        tb = display._user_tb(tb)
        if tb is None:
            raise MagicError("no user frames to debug")
        self.pause_output()
        debugger = self.debugger()
        debugger.reset()
        debugger.interaction(None, tb)

    def show_exception(self, error: BaseException, mode: str | None = None) -> None:
        if isinstance(error, MagicError):
            self.print(Text.assemble(("✗ ", "ember.err"), (str(error), "ember.fg")))
            return
        mode = mode or ("plain" if self.doctest_mode else self.settings.xmode)
        width = (self._out or self.ui).width
        self.print(display.render_exception(type(error), error, error.__traceback__, self.theme, width, mode))

    # ── execution ─────────────────────────────────────────────────────────

    def _run_coroutine(self, coro: Any) -> Any:
        runner = self.settings.autoawait
        if runner == "trio":
            import trio  # type: ignore[import-not-found]

            async def main() -> Any:
                return await coro

            return trio.run(main)
        if runner == "curio":
            import curio  # type: ignore[import-not-found]

            return curio.run(coro)
        return self.loop.run_until_complete(coro)

    def run_code(self, code: CodeType, ns: dict[str, Any] | None = None) -> Any:
        ns = self.ns if ns is None else ns
        if code.co_flags & inspect.CO_COROUTINE:
            return self._run_coroutine(eval(code, ns))
        return eval(code, ns)

    def execute(
        self,
        source: str,
        filename: str,
        interactivity: str | None = None,
        on_value: Callable[[Any], None] | None = None,
    ) -> Any:
        """Execute (already transformed) source.

        Expression statements chosen by `interactivity` (last_expr · all · last · none ·
        last_expr_or_assign) are passed to `on_value`; the last such value is returned."""
        mode = interactivity or self.settings.ast_node_interactivity
        tree = ast.parse(source, filename=filename)
        for transformer in self.ipy.ast_transformers:
            tree = ast.fix_missing_locations(transformer.visit(tree))
        body = tree.body
        if not body:
            return None
        last = len(body) - 1
        if mode == "all":
            shown = {i for i, node in enumerate(body) if isinstance(node, ast.Expr)}
        elif mode == "none":
            shown = set()
        elif mode == "last_expr_or_assign":
            shown = {last} if isinstance(body[last], (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign)) else set()
        else:
            shown = {last} if isinstance(body[last], ast.Expr) else set()
        if source.rstrip().endswith(";"):
            shown.discard(last)

        flags = self.compile_flags
        pending: list[ast.stmt] = []
        result: Any = None

        def flush() -> None:
            if pending:
                module = ast.Module(body=list(pending), type_ignores=[])
                pending.clear()
                self.run_code(compile(module, filename, "exec", flags=flags))

        for i, node in enumerate(body):
            if i not in shown:
                pending.append(node)
                continue
            if isinstance(node, ast.Expr):
                flush()
                value = self.run_code(compile(ast.Expression(node.value), filename, "eval", flags=flags))
            else:
                pending.append(node)
                flush()
                target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else getattr(node, "target", None)
                value = self.ns.get(target.id) if isinstance(target, ast.Name) else None
            result = value
            if on_value is not None and value is not None:
                on_value(value)
        flush()
        return result

    @contextmanager
    def _capture(self) -> Iterator[RailState]:
        real_out, real_err = sys.__stdout__, sys.__stderr__
        plain = self.doctest_mode
        state = RailState("" if plain else self._ansi(("│ ", "ember.border")))
        spinner = Spinner(
            real_out,
            state,
            lambda frame, elapsed: self._ansi(
                ("╰─ ", "ember.border"), (frame, "ember.accent"), (" running ", "ember.muted"),
                (format_duration(elapsed), "ember.faint"), ("  ctrl+c to interrupt", "ember.faint"),
            ),
        )
        out = RailWriter(real_out, state, spinner, spacer=not plain)
        err = RailWriter(real_err, state, spinner, spacer=not plain)
        saved = sys.stdout, sys.stderr, builtins.input
        real_input = builtins.input

        def _input(prompt: object = "") -> str:
            spinner.stop()
            return real_input(prompt)

        sys.stdout, sys.stderr, builtins.input = out, err, _input
        self._out = self._make_console(out, width=max(20, self.width - (0 if plain else 2)))
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
            if state.wrote and not plain:
                real_out.write(state.prefix.rstrip() + "\n")  # breathing room above the footer
            real_out.flush()

    def _display_result(self, value: Any) -> None:
        n = self.count
        self._last_displayed = value
        self.Out[n] = value
        ns = self.ns
        ns["___"], ns["__"], ns["_"] = ns.get("__"), ns.get("_"), value
        ns[f"_{n}"] = value
        if self.settings.history_log_output or self.logger is not None:
            try:
                text = repr(value)[:5000]
            except Exception:
                text = None
            if text is not None:
                if self.settings.history_log_output:
                    self.history.store_output(n, text)
                if self.logger is not None:
                    self.logger.log_output(text)
        self.print(self.render(value))

    def run_cell(self, raw: str, store_history: bool = True, silent: bool = False) -> ExecutionResult:
        info = ExecutionInfo(raw, store_history, silent)
        result = ExecutionResult(info)

        if self._depth > 0 or silent:
            # Nested (e.g. get_ipython().run_cell inside a cell) or silent: no chrome, no history.
            self._depth += 1
            try:
                result.result = self.execute(self.transform(strip_prompts(raw)), "<ember-run_cell>",
                                             on_value=None if silent else self.print_value)
            except (SystemExit, KeyboardInterrupt):
                raise
            except BaseException as e:
                result.error_in_exec = e
                if not silent:
                    self.show_exception(e)
            finally:
                self._depth -= 1
            return result

        source = strip_prompts(raw).rstrip().lstrip("\n")
        if not source.strip():
            return result
        stripped = source.strip()
        if stripped in ("exit", "quit"):
            raise SystemExit(0)
        from ember.magics.history import Macro

        macro = self.ns.get(stripped) if stripped.isidentifier() else None
        code_source = macro.value if isinstance(macro, Macro) else source

        self.count += 1
        n = result.execution_count = self.count
        self.In.append(source)
        ns = self.ns
        ns["_iii"], ns["_ii"], ns["_i"] = ns.get("_ii", ""), ns.get("_i", ""), ns.get("_i00", "")
        ns["_i00"] = ns[f"_i{n}"] = source
        self.suppress_footer = False
        self._last_displayed = None
        digest = hashlib.sha1(code_source.encode()).hexdigest()[:12]
        filename = self.current_filename = f"<ipython-input-{n}-{digest}>"
        lines = [ln + "\n" for ln in code_source.splitlines()]
        for name in (filename, display.cell_label(n)):
            linecache.cache[name] = (len(code_source), None, lines, name)

        translated = self.transform(code_source)
        if store_history:
            self.history.store_input(n, translated, source)
        if self.logger is not None:
            self.logger.log_input(source, translated)

        self.echo(source)
        error: str | None = None
        start = time.perf_counter()
        self._depth += 1
        try:
            with self._capture():
                self.ipy.events.trigger("pre_execute")
                self.ipy.events.trigger("pre_run_cell", info)
                try:
                    if self.autoreload.enabled:
                        from ember.magics.core import _report_reload

                        _report_reload(self, *self.autoreload.check())
                    result.result = self.execute(translated, filename, on_value=self._display_result)
                except SystemExit:
                    raise
                except MagicError as e:
                    error = "failed"
                    result.error_in_exec = e
                    self.show_exception(e)
                except BaseException as e:
                    error = type(e).__name__
                    result.error_in_exec = e
                    if not isinstance(e, KeyboardInterrupt):
                        sys.last_type, sys.last_value, sys.last_traceback = type(e), e, e.__traceback__
                        self.last_exception = e
                    self.show_exception(e)
                    if self.settings.pdb and not isinstance(e, (KeyboardInterrupt, SyntaxError)):
                        try:
                            self.post_mortem(e.__traceback__)
                        except MagicError:
                            pass
                self.autoreload.record_new()
                self.ipy.events.trigger("post_execute")
                self.ipy.events.trigger("post_run_cell", result)
        finally:
            self._depth -= 1
        elapsed = time.perf_counter() - start
        self.last_duration, self.last_ok = elapsed, error is None
        if self.doctest_mode:
            self.ui.print()
        elif not self.suppress_footer:
            self.footer(n, elapsed, self._last_displayed, error)
        if self.exit_requested:
            raise SystemExit(0)
        return result

    # ── startup & shutdown ────────────────────────────────────────────────

    def run_startup_code(self, source: str, filename: str) -> None:
        self._depth += 1
        try:
            self.execute(self.transform(source), filename, on_value=self.print_value)
        except SystemExit:
            pass
        except BaseException as e:
            self.ui.print(Text(f"⚠ error in {filename}", style="ember.warn"))
            self.show_exception(e)
        finally:
            self._depth -= 1

    def startup(self, warnings: list[str] | None = None, run_files: bool = True) -> None:
        """Aliases, exec_lines, startup files, extensions, %store autorestore and GUI integration."""
        from ember.magics.history import restore_store
        from ember.magics.osm import DEFAULT_ALIASES, define_alias

        for warning in warnings or []:
            self.ui.print(Text(f"⚠ {warning}", style="ember.warn"))
        for name, command in {**DEFAULT_ALIASES, **self.settings.aliases}.items():
            try:
                define_alias(self, name, command)
            except MagicError as e:
                self.ui.print(Text(f"⚠ alias {name}: {e}", style="ember.warn"))
        if self.autoreload.enabled:
            self.autoreload.snapshot()
        if run_files:
            self._run_startup_files()
        if self.settings.store_autorestore and self.profile is not None:
            restore_store(self, quiet=True)
        try:
            if self.settings.matplotlib:
                self.enable_matplotlib(self.settings.matplotlib)
            elif self.settings.gui:
                self.enable_gui(self.settings.gui)
        except Exception as e:
            self.ui.print(Text(f"⚠ gui integration failed: {e}", style="ember.warn"))
        self.ipy.events.trigger("shell_initialized", self.ipy)

    def _run_startup_files(self) -> None:
        for line in self.settings.exec_lines:
            self.run_startup_code(line, "<exec_lines>")
        files: list[Path] = []
        if self.profile and self.profile.startup_dir.is_dir():
            files += sorted(p for p in self.profile.startup_dir.iterdir() if p.suffix in (".py", ".ipy"))
        files += [Path(f).expanduser() for f in self.settings.exec_files]
        for path in files:
            try:
                self.run_startup_code(path.read_text(), str(path.resolve()))
            except OSError as e:
                self.ui.print(Text(f"⚠ can't read {path}: {e}", style="ember.warn"))
        for ext in self.settings.extensions:
            try:
                if msg := self.ipy.extension_manager.load_extension(ext):
                    self.ui.print(Text(f"⚠ extension {ext}: {msg}", style="ember.warn"))
            except Exception as e:
                self.ui.print(Text(f"⚠ extension {ext} failed: {type(e).__name__}: {e}", style="ember.warn"))

    def close(self) -> None:
        self.history.end_session()
        if self.logger is not None:
            self.logger.close()
        for proc in self.bg_processes:
            if proc.poll() is None:
                proc.terminate()

    # ── chrome ────────────────────────────────────────────────────────────

    def echo(self, source: str) -> None:
        if self.doctest_mode:
            for i, line in enumerate(source.split("\n")):
                self.ui.print(Text.assemble((">>> " if i == 0 else "... ", "ember.faint"), (line, "ember.fg")))
            return
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
            parts += [("✗ ", "ember.err.bold"), (error, "ember.err"), (" · ", "ember.faint")]
        else:
            parts += [("✓ ", "ember.ok")]
        parts += [(format_duration(elapsed), "ember.muted")]
        if result is not None and not error:
            parts += [(" · ", "ember.faint"), (display.describe(result), "ember.muted"), (" · ", "ember.faint"), (f"Out[{n}]", "ember.faint")]
        self.ui.print(Text.assemble(*parts))
        self.ui.print("\n")

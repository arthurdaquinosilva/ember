"""The object `get_ipython()` returns: IPython's InteractiveShell API, backed by ember."""

from __future__ import annotations

import importlib
import inspect
import sys
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from rich.text import Text

from ember.ipython.pretty import RepresentationPrinter
from ember.utils import SList, Struct

if TYPE_CHECKING:
    from ember.shell import Shell

EVENTS = ("pre_execute", "pre_run_cell", "post_execute", "post_run_cell", "shell_initialized")


class EventManager:
    def __init__(self, shell: Shell):
        self.shell = shell
        self.callbacks: dict[str, list[Callable]] = {e: [] for e in EVENTS}

    def register(self, event: str, function: Callable) -> None:
        if event not in self.callbacks:
            raise KeyError(f"unknown event {event!r} — available: {', '.join(EVENTS)}")
        if not callable(function):
            raise TypeError("need a callable")
        if function not in self.callbacks[event]:
            self.callbacks[event].append(function)

    def unregister(self, event: str, function: Callable) -> None:
        try:
            self.callbacks[event].remove(function)
        except ValueError:
            raise ValueError(f"function {function!r} is not registered as a {event} callback") from None

    def trigger(self, event: str, *args: Any, **kwargs: Any) -> None:
        for fn in list(self.callbacks[event]):
            try:
                fn(*args, **kwargs)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                name = getattr(fn, "__qualname__", repr(fn))
                self.shell.print(Text(f"⚠ {event} callback {name} failed: {type(e).__name__}: {e}", style="ember.warn"))


@dataclass
class ExecutionInfo:
    raw_cell: str
    store_history: bool = False
    silent: bool = False
    shell_futures: bool = True
    cell_id: str | None = None


@dataclass
class ExecutionResult:
    info: ExecutionInfo
    execution_count: int | None = None
    error_before_exec: BaseException | None = None
    error_in_exec: BaseException | None = None
    result: Any = None

    @property
    def success(self) -> bool:
        return self.error_before_exec is None and self.error_in_exec is None

    def raise_error(self) -> None:
        if self.error_before_exec is not None:
            raise self.error_before_exec
        if self.error_in_exec is not None:
            raise self.error_in_exec


class BaseFormatter:
    def __init__(self) -> None:
        self.type_printers: dict[type, Callable] = {}
        self.deferred_printers: dict[tuple[str, str], Callable] = {}
        self.enabled = True

    def for_type(self, typ: Any, func: Callable | None = None) -> Callable | None:
        if isinstance(typ, str):
            module, _, name = typ.rpartition(".")
            return self.for_type_by_name(module, name, func)
        old = self.type_printers.get(typ)
        if func is not None:
            self.type_printers[typ] = func
        return old

    def for_type_by_name(self, type_module: str, type_name: str, func: Callable | None = None) -> Callable | None:
        key = (type_module, type_name)
        old = self.deferred_printers.get(key)
        if func is not None:
            self.deferred_printers[key] = func
        return old

    def pop(self, typ: Any, default: Any = inspect.Parameter.empty) -> Any:
        if isinstance(typ, str):
            key = tuple(typ.rsplit(".", 1))
            if key in self.deferred_printers:
                return self.deferred_printers.pop(key)  # type: ignore[arg-type]
        elif typ in self.type_printers:
            return self.type_printers.pop(typ)
        if default is inspect.Parameter.empty:
            raise KeyError(f"no registered printer for {typ!r}")
        return default

    def lookup(self, obj: Any) -> Callable | None:
        for cls in type(obj).__mro__:
            if cls in self.type_printers:
                return self.type_printers[cls]
            key = (cls.__module__, cls.__name__)
            if key in self.deferred_printers:
                self.type_printers[cls] = self.deferred_printers.pop(key)
                return self.type_printers[cls]
        return None


class PlainTextFormatter(BaseFormatter):
    """`text/plain` printers: `for_type(cls, lambda obj, p, cycle: p.text(...))`."""

    format_type = "text/plain"

    def __init__(self) -> None:
        super().__init__()
        self.max_width = 79
        self.max_seq_length = 1000
        self.float_precision = ""

    def has_printer(self, obj: Any) -> bool:
        return self.lookup(obj) is not None

    def __call__(self, obj: Any) -> str:
        printer = RepresentationPrinter(max_width=self.max_width, max_seq_length=self.max_seq_length,
                                        type_printers=self.type_printers, deferred_printers=self.deferred_printers)
        printer.pretty(obj)
        return printer.getvalue()


class DisplayFormatter:
    def __init__(self) -> None:
        self.plain = PlainTextFormatter()
        self.formatters: dict[str, BaseFormatter] = {"text/plain": self.plain}
        for mime in ("text/html", "text/markdown", "text/latex", "image/png", "image/jpeg", "image/svg+xml",
                     "application/json", "application/javascript", "application/pdf"):
            self.formatters[mime] = BaseFormatter()
        self.active_types = list(self.formatters)

    def format(self, obj: Any, include: Any = None, exclude: Any = None) -> tuple[dict, dict]:
        return {"text/plain": self.plain(obj)}, {}


class ExtensionManager:
    BUILTIN = {"autoreload", "storemagic"}

    def __init__(self, ip: EmberInteractiveShell):
        self.ip = ip
        self.loaded: set[str] = set()

    def load_extension(self, module_str: str) -> str | None:
        if module_str in self.loaded:
            return "already loaded"
        if module_str in self.BUILTIN:
            self.loaded.add(module_str)
            return None
        mod = importlib.import_module(module_str)
        for hook in ("load_ember_extension", "load_ipython_extension"):
            if hasattr(mod, hook):
                getattr(mod, hook)(self.ip)
                self.loaded.add(module_str)
                return None
        return "no load function"

    def unload_extension(self, module_str: str) -> str | None:
        if module_str not in self.loaded:
            return "not loaded"
        if module_str in sys.modules and module_str not in self.BUILTIN:
            mod = sys.modules[module_str]
            for hook in ("unload_ember_extension", "unload_ipython_extension"):
                if hasattr(mod, hook):
                    getattr(mod, hook)(self.ip)
                    break
            else:
                return "no unload function"
        self.loaded.discard(module_str)
        return None

    def reload_extension(self, module_str: str) -> None:
        if module_str in self.loaded and module_str not in self.BUILTIN:
            self.unload_extension(module_str)
            importlib.reload(sys.modules[module_str])
        self.load_extension(module_str)


class EmberInteractiveShell:
    """What `get_ipython()` returns inside ember."""

    def __init__(self, shell: Shell):
        self._shell = shell
        self.events = EventManager(shell)
        self.display_formatter = DisplayFormatter()
        self.extension_manager = ExtensionManager(self)
        self.input_transformers_cleanup: list[Callable[[list[str]], list[str]]] = []
        self.input_transformers_post: list[Callable[[list[str]], list[str]]] = []
        self.ast_transformers: list[Any] = []
        self.config = Struct()
        self.kernel = None
        self.exit_now = False

    def __repr__(self) -> str:
        return "<ember.EmberInteractiveShell>"

    # ── namespace ─────────────────────────────────────────────────────────

    @property
    def user_ns(self) -> dict[str, Any]:
        return self._shell.ns

    @property
    def user_global_ns(self) -> dict[str, Any]:
        return self._shell.ns

    @property
    def user_ns_hidden(self) -> dict[str, Any]:
        return {k: self._shell.ns.get(k) for k in self._shell.initial_names}

    @property
    def execution_count(self) -> int:
        return self._shell.count + 1

    @property
    def history_manager(self):
        return self._shell.history

    @property
    def profile(self) -> str:
        return self._shell.profile.name if self._shell.profile else "default"

    @property
    def profile_dir(self) -> Struct:
        p = self._shell.profile
        return Struct(location=str(p.config_dir) if p else "", startup_dir=str(p.startup_dir) if p else "")

    @property
    def ipython_dir(self) -> str:
        p = self._shell.profile
        return str(p.config_dir) if p else ""

    @property
    def starting_dir(self) -> str:
        return self._shell.starting_dir

    def push(self, variables: dict | str | list, interactive: bool = True) -> None:
        if isinstance(variables, dict):
            self._shell.ns.update(variables)
            return
        names = variables.replace(",", " ").split() if isinstance(variables, str) else list(variables)
        frame = sys._getframe(1)
        for name in names:
            try:
                self._shell.ns[name] = eval(name, frame.f_globals, frame.f_locals)
            except Exception:
                print(f"Could not get variable {name} from {frame.f_code.co_name}")

    def del_var(self, varname: str, by_name: bool = False) -> None:
        self._shell.xdel(varname)

    def drop_by_id(self, variables: dict) -> None:
        for name, obj in variables.items():
            if name in self._shell.ns and self._shell.ns[name] is obj:
                del self._shell.ns[name]

    # ── magics ────────────────────────────────────────────────────────────

    def run_line_magic(self, magic_name: str, line: str, _stack_depth: int = 1) -> Any:
        return self._shell.api.magic(magic_name, line)

    def run_cell_magic(self, magic_name: str, line: str, cell: str) -> Any:
        return self._shell.api.cell_magic(magic_name, line, cell)

    def magic(self, arg_s: str) -> Any:
        name, _, rest = arg_s.lstrip("%").partition(" ")
        return self.run_line_magic(name, rest)

    def find_line_magic(self, magic_name: str) -> Callable | None:
        from ember.magics import LINE_MAGICS

        spec = LINE_MAGICS.get(magic_name)
        return (lambda line: spec.fn(self._shell, line)) if spec else None

    def find_cell_magic(self, magic_name: str) -> Callable | None:
        from ember.magics import CELL_MAGICS

        spec = CELL_MAGICS.get(magic_name)
        return (lambda line, cell: spec.fn(self._shell, line, cell)) if spec else None

    def find_magic(self, magic_name: str, magic_kind: str = "line") -> Callable | None:
        return self.find_cell_magic(magic_name) if magic_kind == "cell" else self.find_line_magic(magic_name)

    def register_magics(self, *objs: Any) -> None:
        from ember.magics import register_user_magic

        for obj in objs:
            if isinstance(obj, type):
                try:
                    instance = obj(shell=self)
                except Exception:
                    instance = obj(shell=None)  # real IPython Magics reject a non-traitlets parent
                    instance.shell = self
            else:
                instance = obj
            table = getattr(instance, "magics", None) or {}
            for kind in ("line", "cell"):
                for name, method in table.get(kind, {}).items():
                    fn = getattr(instance, method) if isinstance(method, str) else method
                    register_user_magic(kind, name, fn)

    def register_magic_function(self, func: Callable, magic_kind: str = "line", magic_name: str | None = None) -> None:
        from ember.magics import register_user_magic

        register_user_magic(magic_kind, magic_name or func.__name__, func)

    def define_magic(self, magic_name: str, func: Callable) -> None:
        from ember.magics import register_user_magic

        register_user_magic("line", magic_name, lambda line: func(self, line))

    # ── execution ─────────────────────────────────────────────────────────

    def run_cell(self, raw_cell: str, store_history: bool = False, silent: bool = False,
                 shell_futures: bool = True, cell_id: str | None = None) -> ExecutionResult:
        return self._shell.run_cell(raw_cell, store_history=store_history, silent=silent)

    def ex(self, cmd: str) -> None:
        exec(cmd, self._shell.ns)

    def ev(self, expr: str) -> Any:
        return eval(expr, self._shell.ns)

    def system(self, cmd: str) -> None:
        self._shell.system(cmd)

    system_raw = system_piped = system

    def getoutput(self, cmd: str, split: bool = True, depth: int = 0) -> SList | str:
        out = self._shell.getoutput(cmd)
        return out if split else out.n

    def safe_execfile(self, fname: str, *where: Any, exit_ignore: bool = False, raise_exceptions: bool = False,
                      shell_futures: bool = False) -> None:
        self._shell.api.magic("run", f"-i {fname}")

    safe_execfile_ipy = safe_execfile

    def set_next_input(self, text: str, replace: bool = False) -> None:
        self._shell.next_input = text

    def ask_exit(self) -> None:
        self.exit_now = True
        self._shell.exit_requested = True

    def showtraceback(self, exc_tuple: Any = None, filename: Any = None, tb_offset: Any = None,
                      exception_only: bool = False, running_compiled_code: bool = False) -> None:
        etype, value, tb = exc_tuple or sys.exc_info()
        if value is not None:
            self._shell.show_exception(value)

    def showsyntaxerror(self, filename: Any = None, running_compiled_code: bool = False) -> None:
        self.showtraceback()

    def enable_gui(self, gui: str | None = None) -> None:
        self._shell.enable_gui(gui)

    def enable_matplotlib(self, gui: str | None = None) -> tuple[str | None, str]:
        return self._shell.enable_matplotlib(gui)

    def mktempfile(self, data: str | None = None, prefix: str = "ember_edit_") -> str:
        with tempfile.NamedTemporaryFile("w", prefix=prefix, suffix=".py", delete=False) as f:
            if data:
                f.write(data)
            return f.name

    def write(self, data: str) -> None:
        sys.stdout.write(data)

    def write_err(self, data: str) -> None:
        sys.stderr.write(data)


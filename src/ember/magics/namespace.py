"""Namespace & inspection magics: who/whos, xdel, reset, precision, page, pinfo family, psearch."""

from __future__ import annotations

import fnmatch
import inspect
import re
from typing import TYPE_CHECKING, Any

from rich import box
from rich.columns import Columns
from rich.pretty import Pretty
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ember.display import short_path
from ember.magics import MagicError, line_magic, parse_args
from ember.utils import SList, plural, resolve_name

if TYPE_CHECKING:
    from ember.shell import Shell

_TYPE_TESTS = {
    "function": lambda v: inspect.isfunction(v) or inspect.isbuiltin(v),
    "builtin_function_or_method": inspect.isbuiltin,
    "class": inspect.isclass,
    "type": inspect.isclass,
    "module": inspect.ismodule,
    "method": inspect.ismethod,
}


def _matches_types(value: Any, types: list[str]) -> bool:
    if not types:
        return True
    for t in types:
        test = _TYPE_TESTS.get(t)
        if (test and test(value)) or type(value).__name__ == t:
            return True
    return False


def _filtered(shell: Shell, args: str) -> dict[str, Any]:
    types = args.replace(",", " ").split()
    return {k: v for k, v in sorted(shell.user_vars().items()) if _matches_types(v, types)}


@line_magic("who", doc="list user variables, optionally by type (%who int str)")
def m_who(shell: Shell, args: str):
    names = list(_filtered(shell, args))
    if not names:
        shell.print(Text("no variables match" if args.strip() else "no variables defined", style="ember.faint"))
        return
    shell.print(Columns([Text(n, style="ember.fg") for n in names], padding=(0, 3)))


@line_magic("who_ls", doc="return a sorted list of user variable names (optionally by type)")
def m_who_ls(shell: Shell, args: str):
    return SList(_filtered(shell, args))


@line_magic("whos", "vars", doc="table of user variables with types and values")
def m_whos(shell: Shell, args: str):
    items = _filtered(shell, args)
    if not items:
        shell.print(Text("no variables match" if args.strip() else "no variables defined", style="ember.faint"))
        return
    table = Table(box=box.SIMPLE_HEAD, border_style="ember.border", header_style="ember.accent.bold", show_edge=False, pad_edge=False)
    table.add_column("name", style="ember.fg.bold", no_wrap=True)
    table.add_column("type", style="ember.class", no_wrap=True)
    table.add_column("info", style="ember.muted", overflow="ellipsis", no_wrap=True, max_width=80)
    for name, value in items.items():
        if inspect.ismodule(value):
            info = short_path(getattr(value, "__file__", None) or "built-in")
        elif inspect.isfunction(value) or inspect.isclass(value):
            try:
                info = f"{name}{inspect.signature(value)}"
            except (TypeError, ValueError):
                info = ""
        else:
            shape = getattr(value, "shape", None)
            try:
                info = f"shape {shape}" if isinstance(shape, tuple) else repr(value)
            except Exception:
                info = "<repr failed>"
            info = info.replace("\n", " ")
        table.add_row(name, type(value).__name__, info[:200])
    shell.print(table)


@line_magic("xdel", doc="delete a variable and every reference ember holds to it (Out, _, _N)")
def m_xdel(shell: Shell, args: str):
    name = args.strip()
    if not name:
        raise MagicError("usage: %xdel name")
    if name not in shell.ns:
        raise MagicError(f"{name} is not defined")
    shell.xdel(name)


@line_magic("reset", doc="clear variables: %reset · %reset in|out|dhist (-f accepted)")
def m_reset(shell: Shell, args: str):
    opts, rest = parse_args(args, "fs")
    targets = rest.split()
    if not targets:
        names = list(shell.user_vars())
        for k in names:
            del shell.ns[k]
        shell.clear_output_cache()
        shell.print(Text(f"cleared {plural(len(names), 'variable')}", style="ember.muted"))
        return
    for target in targets:
        if target == "out":
            shell.clear_output_cache()
        elif target == "in":
            del shell.In[1:]
            for k in [k for k in shell.ns if re.fullmatch(r"_i+|_i\d+", k)]:
                del shell.ns[k]
        elif target == "dhist":
            del shell.dir_history[:]
        else:
            raise MagicError(f"unknown reset target {target!r} (use in, out or dhist)")
        shell.print(Text(f"cleared {target}", style="ember.muted"))


@line_magic("reset_selective", doc="delete variables whose names match a regex")
def m_reset_selective(shell: Shell, args: str):
    _, pattern = parse_args(args, "f")
    if not pattern:
        raise MagicError("usage: %reset_selective regex")
    regex = re.compile(pattern)
    names = [k for k in shell.user_vars() if regex.search(k)]
    for k in names:
        shell.xdel(k)
    shell.print(Text(f"deleted {plural(len(names), 'variable')}", style="ember.muted"))


@line_magic("precision", doc="float display precision: %precision 3 · %precision %.2e · %precision (reset)", expand=False)
def m_precision(shell: Shell, args: str):
    fmt = args.strip()
    try:
        shell.set_setting("precision", fmt)
    except ValueError as e:
        raise MagicError(str(e)) from None
    return shell.float_format or "%r"


# ── inspection ─────────────────────────────────────────────────────────────


def _lookup(shell: Shell, expr: str) -> Any:
    expr = expr.strip()
    if not expr:
        raise MagicError("which object?")
    try:
        return eval(expr, shell.ns)
    except NameError:
        raise MagicError(f"{expr} is not defined") from None
    except AttributeError as e:
        raise MagicError(str(e)) from None


@line_magic("pinfo", doc="inspect an object (same as obj?)", expand=False)
def m_pinfo(shell: Shell, args: str):
    shell.api.inspect(args.strip(), 1)


@line_magic("pinfo2", doc="inspect an object with source (same as obj??)", expand=False)
def m_pinfo2(shell: Shell, args: str):
    shell.api.inspect(args.strip(), 2)


@line_magic("pdef", doc="show a callable's signature", expand=False)
def m_pdef(shell: Shell, args: str):
    obj = _lookup(shell, args)
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        raise MagicError("no signature available") from None
    name = getattr(obj, "__name__", args.strip())
    shell.print(Syntax(f"{name}{sig}", "python", theme=shell.theme.syntax_theme, background_color="default", word_wrap=True))


@line_magic("pdoc", doc="show an object's docstring", expand=False)
def m_pdoc(shell: Shell, args: str):
    doc = inspect.getdoc(_lookup(shell, args))
    shell.print(Text(doc, style="ember.muted") if doc else Text("no docstring", style="ember.faint"))


@line_magic("psource", doc="show an object's source code", expand=False)
def m_psource(shell: Shell, args: str):
    obj = _lookup(shell, args)
    try:
        lines, start = inspect.getsourcelines(obj)
    except (TypeError, OSError):
        raise MagicError("source not available") from None
    shell.print(Syntax("".join(lines).rstrip(), "python", theme=shell.theme.syntax_theme, background_color="default",
                       line_numbers=True, start_line=max(start, 1)))


@line_magic("pfile", doc="show the whole file an object is defined in", expand=False)
def m_pfile(shell: Shell, args: str):
    obj = _lookup(shell, args)
    try:
        path = inspect.getsourcefile(obj) or inspect.getfile(obj)
    except TypeError:
        raise MagicError("no file for this object") from None
    shell.page(Syntax.from_path(path, theme=shell.theme.syntax_theme, background_color="default", line_numbers=True))


@line_magic("page", doc="show an object's pretty repr in a pager (-r for plain repr)", expand=False)
def m_page(shell: Shell, args: str):
    opts, expr = parse_args(args, "r")
    obj = _lookup(shell, expr)
    shell.page(Text(repr(obj)) if opts.get("r") else Pretty(obj, indent_guides=True, expand_all=True))


@line_magic("psearch", doc="find names by wildcard: %psearch os.*path* [type] [-i] [-a]", expand=False)
def m_psearch(shell: Shell, args: str):
    opts, rest = parse_args(args, "iac")
    parts = rest.split()
    if not parts:
        raise MagicError("usage: %psearch pattern [type] [-i] [-a]")
    shell.print(psearch(shell, parts[0], parts[1:], ignore_case=bool(opts.get("i")), show_all=bool(opts.get("a"))))


def psearch(shell: Shell, pattern: str, types: list[str] | None = None, ignore_case: bool = False, show_all: bool = False):
    prefix, _, leaf = pattern.rpartition(".")
    if "*" in prefix or "?" in prefix:
        raise MagicError("wildcards are only supported in the last part of a name")
    if prefix:
        try:
            space = resolve_name(prefix, shell.ns)
        except LookupError:
            raise MagicError(f"{prefix} is not defined") from None
        candidates = {name: _safe_static(space, name) for name in dir(space)}
    else:
        import builtins

        candidates = {**vars(builtins), **shell.ns}
    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(fnmatch.translate(leaf), flags)
    found = [
        (f"{prefix}.{name}" if prefix else name)
        for name, value in sorted(candidates.items())
        if regex.match(name) and (show_all or not name.startswith("_")) and _matches_types(value, types or [])
    ]
    if not found:
        return Text("no matches", style="ember.faint")
    return Columns([Text(n, style="ember.fg") for n in found], padding=(0, 3))


def _safe_static(obj: Any, name: str) -> Any:
    try:
        return inspect.getattr_static(obj, name)
    except AttributeError:
        return None

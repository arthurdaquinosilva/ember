"""IPython's magic-authoring API (`Magics`, `@magics_class`, `@line_magic`, `magic_arguments`…)."""

from __future__ import annotations

import argparse
import os
from getopt import GetoptError, getopt
from typing import Any, Callable

from ember.magics import MagicError
from ember.utils import Struct, arg_split


class UsageError(MagicError):
    """Raised by magics for bad arguments; shown as a one-line message."""


class TryNext(Exception):
    pass


class StdinNotImplementedError(IOError, NotImplementedError):
    pass


class InputRejected(Exception):
    pass


_MARK = "_ember_magic_marks"


def _marker(kind: str, arg: Any = None):
    def mark(func: Callable, name: str | None) -> Callable:
        marks = getattr(func, _MARK, [])
        for k in (("line", "cell") if kind == "line_cell" else (kind,)):
            marks.append((k, name or func.__name__))
        setattr(func, _MARK, marks)
        return func

    if callable(arg):
        return mark(arg, None)
    return lambda func: mark(func, arg)


def line_magic(arg: Any = None):
    return _marker("line", arg)


def cell_magic(arg: Any = None):
    return _marker("cell", arg)


def line_cell_magic(arg: Any = None):
    return _marker("line_cell", arg)


def magics_class(cls: type) -> type:
    table: dict[str, dict[str, str]] = {"line": {}, "cell": {}}
    for base in reversed(cls.__mro__):
        for attr, value in vars(base).items():
            for kind, name in getattr(value, _MARK, []):
                table[kind][name] = attr
    cls.magics = table
    cls.registered = True
    return cls


def needs_local_scope(func: Callable) -> Callable:
    func.needs_local_scope = True  # type: ignore[attr-defined]
    return func


def no_var_expand(func: Callable) -> Callable:
    func._ipython_bypass_var_expand = True  # type: ignore[attr-defined]
    return func


def output_can_be_silenced(func: Callable) -> Callable:
    return func


class Magics:
    registered = False
    magics: dict[str, dict[str, str]] = {"line": {}, "cell": {}}

    def __init__(self, shell: Any = None, **kwargs: Any):
        self.shell = shell
        self.options_table: dict[str, str] = {}

    def arg_err(self, func: Callable) -> None:
        print("Error in arguments:")
        print(func.__doc__ or "")

    def format_latex(self, strng: str) -> str:
        return strng

    def default_option(self, fn: str, optstr: str) -> None:
        self.options_table[fn] = optstr

    def parse_options(self, arg_str: str, opt_str: str, *long_opts: str, **kw: Any) -> tuple[Struct, Any]:
        """IPython-compatible getopt parsing: returns (Struct of options, remaining args)."""
        mode = kw.get("mode", "string")
        if mode not in ("string", "list"):
            raise ValueError("incorrect mode given: %s" % mode)
        list_all = kw.get("list_all", False)
        posix = kw.get("posix", os.name == "posix")
        strict = kw.get("strict", True)
        preserve_non_opts = kw.get("preserve_non_opts", False)
        remainder = arg_str
        odict: dict[str, Any] = {}
        args: Any = arg_str.split()
        if len(args) >= 1:
            argv = arg_split(arg_str, posix, strict)
            try:
                opts, args = getopt(argv, opt_str, list(long_opts))
            except GetoptError as e:
                raise UsageError(f"{e.msg}\nOptions: {opt_str} {' '.join(long_opts)}") from None
            for o, a in opts:
                if mode == "string" and preserve_non_opts:
                    remainder = remainder.replace(o, "", 1).replace(a, "", 1)
                key = o[2:] if o.startswith("--") else o[1:]
                if key in odict:
                    if isinstance(odict[key], list):
                        odict[key].append(a)
                    else:
                        odict[key] = [odict[key], a]
                else:
                    odict[key] = [a] if list_all else a
        opts_struct = Struct(odict)
        if mode == "string":
            args = remainder.lstrip() if preserve_non_opts else " ".join(args)
        else:
            args = list(args)
        return opts_struct, args


# ── standalone decorators: register straight into ember ─────────────────────


def _register(kind: str, func: Callable, name: str | None = None) -> Callable:
    from ember.magics import register_user_magic

    register_user_magic(kind, name or func.__name__, func)
    return func


def register_line_magic(arg: Any):
    if callable(arg):
        return _register("line", arg)
    return lambda func: _register("line", func, arg)


def register_cell_magic(arg: Any):
    if callable(arg):
        return _register("cell", arg)
    return lambda func: _register("cell", func, arg)


def register_line_cell_magic(arg: Any):
    if callable(arg):
        return _register("line_cell", arg)
    return lambda func: _register("line_cell", func, arg)


# ── IPython.core.magic_arguments ────────────────────────────────────────────


class MagicArgumentParser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise UsageError(message)

    def parse_argstring(self, argstring: str) -> argparse.Namespace:
        return self.parse_args(arg_split(argstring))


def real_name(magic_func: Callable) -> str:
    name = magic_func.__name__
    return name[len("magic_"):] if name.startswith("magic_") else name


def construct_parser(magic_func: Callable) -> MagicArgumentParser:
    kwargs = getattr(magic_func, "argcmd_kwds", {})
    kwargs.setdefault("prog", "%" + real_name(magic_func))
    parser = MagicArgumentParser(**kwargs)
    group: Any = parser
    for kind, args, kw in reversed(getattr(magic_func, "decorators", [])):
        if kind == "argument":
            group.add_argument(*args, **kw)
        elif kind == "group":
            group = parser.add_argument_group(*args, **kw)
        elif kind == "defaults":
            parser.set_defaults(**kw)
    magic_func.__doc__ = (magic_func.__doc__ or "") + "\n" + parser.format_help()
    return parser


def parse_argstring(magic_func: Callable, argstring: str) -> argparse.Namespace:
    return magic_func.parser.parse_argstring(argstring)  # type: ignore[attr-defined]


def _add(kind: str, *args: Any, **kwargs: Any):
    def deco(func: Callable) -> Callable:
        if not hasattr(func, "decorators"):
            func.decorators = []  # type: ignore[attr-defined]
        func.decorators.append((kind, args, kwargs))  # type: ignore[attr-defined]
        return func

    return deco


def argument(*args: Any, **kwargs: Any):
    return _add("argument", *args, **kwargs)


def argument_group(*args: Any, **kwargs: Any):
    return _add("group", *args, **kwargs)


def defaults(**kwargs: Any):
    return _add("defaults", **kwargs)


def kwds(**kwargs: Any):
    def deco(func: Callable) -> Callable:
        func.argcmd_kwds = kwargs  # type: ignore[attr-defined]
        return func

    return deco


def magic_arguments(name: str | None = None):
    def deco(func: Callable) -> Callable:
        if name is not None:
            func.argcmd_name = name  # type: ignore[attr-defined]
        func.parser = construct_parser(func)  # type: ignore[attr-defined]
        return func

    return deco

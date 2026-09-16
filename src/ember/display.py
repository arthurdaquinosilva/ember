"""Turning Python objects, exceptions and introspection into rich renderables."""

from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path
from types import TracebackType
from typing import Any

from rich import box
from rich.console import Group, RenderableType
from rich.json import JSON
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.pretty import Pretty
from rich.protocol import is_renderable
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.traceback import Traceback

from ember.theme import Theme

PKG_DIR = str(Path(__file__).parent)
# Cells use IPython's filename convention so tools that special-case it (line_profiler, …) find the source.
_CELL_FILE = re.compile(r"<ipython-input-(\d+)-[0-9a-f]+>")


def cell_label(n: int) -> str:
    return f"In [{n}]"


class CellTraceback(Traceback):
    """Rich skips source for `<…>` filenames, so cells are relabelled `In [N]`."""

    @classmethod
    def _guess_lexer(cls, filename: str, code: str) -> str:
        if filename.startswith("In ["):
            return "python"
        return super()._guess_lexer(filename, code)


def short_path(path: str | os.PathLike) -> str:
    path = str(path)
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        path = "~" + path[len(home):]
    return path


def describe(value: Any) -> str:
    """A short type/size hint for the cell footer, e.g. 'list · 10 items'."""
    name = type(value).__name__
    try:
        shape = getattr(value, "shape", None)
        if isinstance(shape, tuple):
            return f"{name} · {'×'.join(map(str, shape))}"
        if isinstance(value, (str, bytes)):
            return f"{name} · {len(value)} chars" if isinstance(value, str) else f"{name} · {len(value)} bytes"
        if hasattr(type(value), "__len__") and not isinstance(value, type):
            n = len(value)
            return f"{name} · {n} item{'s' if n != 1 else ''}"
    except Exception:
        pass
    return name


def _is_dataframe(value: Any) -> bool:
    t = type(value)
    return t.__name__ == "DataFrame" and t.__module__.split(".")[0] in ("pandas", "polars")


def dataframe_table(df: Any, max_rows: int = 20) -> RenderableType:
    module = type(df).__module__.split(".")[0]
    table = Table(
        box=box.SIMPLE_HEAD,
        header_style="ember.accent.bold",
        border_style="ember.border",
        show_edge=False,
        pad_edge=False,
    )
    if module == "pandas":
        n_rows, n_cols = df.shape
        head = n_rows > max_rows
        view = df.head(max_rows // 2) if head else df
        tail = df.tail(max_rows // 2) if head else None
        table.add_column(str(df.index.name or ""), style="ember.muted")
        for col in df.columns:
            numeric = str(df[col].dtype).startswith(("int", "float", "uint", "complex"))
            table.add_column(str(col), justify="right" if numeric else "left")

        def add(frame):
            for idx, row in zip(frame.index, frame.itertuples(index=False)):
                table.add_row(str(idx), *(str(v) for v in row))

        add(view)
        if tail is not None:
            table.add_row("⋮", *("⋮" for _ in df.columns), style="ember.faint")
            add(tail)
    else:  # polars
        n_rows, n_cols = df.shape
        for name, dtype in zip(df.columns, df.dtypes):
            table.add_column(f"{name}\n[ember.faint]{dtype}[/]")
        for row in df.head(max_rows).iter_rows():
            table.add_row(*(str(v) for v in row))
    caption = Text(f"{n_rows:,} rows × {n_cols} columns", style="ember.faint")
    return Group(table, caption)


class _FloatRepr:
    """Stands in for a float inside a structure so rich's pretty printer uses %precision."""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        return self.text


def apply_precision(value: Any, fmt: str, depth: int = 0) -> Any:
    """Copy containers, replacing floats with formatted stand-ins (display only)."""
    if isinstance(value, float) and type(value) is float:
        return _FloatRepr(fmt % value)
    if depth > 6:
        return value
    if type(value) in (list, tuple, set, frozenset) and len(value) <= 10_000:
        items = [apply_precision(v, fmt, depth + 1) for v in value]
        return type(value)(items) if type(value) in (list, tuple) else items
    if type(value) is dict and len(value) <= 10_000:
        return {k: apply_precision(v, fmt, depth + 1) for k, v in value.items()}
    return value


def _mime_renderable(bundle: Any) -> RenderableType | None:
    if isinstance(bundle, tuple):
        bundle = bundle[0]
    if not isinstance(bundle, dict):
        return None
    if "text/markdown" in bundle:
        return Markdown(str(bundle["text/markdown"]))
    if "application/json" in bundle:
        return JSON(json.dumps(bundle["application/json"], default=str))
    if "text/plain" in bundle:
        return Text(str(bundle["text/plain"]))
    return None


def render_value(value: Any, precision: str = "", printers: Any = None) -> RenderableType:
    """Pick the richest terminal rendering an object offers.

    Order: registered text/plain printers → DataFrames → rich renderables → `_repr_mimebundle_`
    → `_repr_markdown_` → `_repr_pretty_` → `_repr_json_` → `_repr_latex_` → html-only objects → pretty repr."""
    from ember.ipython.display import html_to_text
    from ember.ipython.pretty import get_real_method

    if printers is not None and printers.lookup(value) is not None:
        try:
            return Text(printers(value))
        except Exception:
            pass
    if _is_dataframe(value):
        try:
            return dataframe_table(value)
        except Exception:
            pass
    if not isinstance(value, (str, bytes)) and is_renderable(value):
        return value

    def call(name: str, *args: Any) -> Any:
        method = get_real_method(value, name)
        if method is None:
            return None
        try:
            return method(*args)
        except Exception:
            return None

    if (bundle := call("_repr_mimebundle_")) is not None and (r := _mime_renderable(bundle)) is not None:
        return r
    if isinstance(md := call("_repr_markdown_"), (str, tuple)):
        return Markdown(md[0] if isinstance(md, tuple) else md)
    if get_real_method(value, "_repr_pretty_") is not None:
        from ember.ipython.pretty import pretty

        try:
            return Text(pretty(value, max_width=100))
        except Exception:
            pass
    if (data := call("_repr_json_")) is not None:
        try:
            return JSON(json.dumps(data[0] if isinstance(data, tuple) else data, default=str))
        except (TypeError, ValueError):
            pass
    if isinstance(latex := call("_repr_latex_"), str):
        return Text(latex, style="ember.accent2")
    if type(value).__repr__ is object.__repr__ and isinstance(html := call("_repr_html_"), str):
        return Text(html_to_text(html))
    if precision:
        value = apply_precision(value, precision)
        if isinstance(value, _FloatRepr):
            return Text(value.text, style="repr.number")
    return Pretty(value, indent_guides=True, max_length=500, max_string=20_000)


def _user_tb(tb: TracebackType | None) -> TracebackType | None:
    """Hide ember's own frames above the user's code."""
    while tb is not None and tb.tb_frame.f_code.co_filename.startswith(PKG_DIR):
        tb = tb.tb_next
    return tb


def render_exception(
    etype: type[BaseException],
    evalue: BaseException,
    tb: TracebackType | None,
    theme: Theme,
    width: int,
    mode: str = "context",
) -> RenderableType:
    """Render an exception in one of the xmodes: minimal · plain · context · verbose."""
    tb = _user_tb(tb)
    if isinstance(evalue, KeyboardInterrupt):
        return Text("⏹  interrupted", style="ember.warn")
    if mode == "minimal":
        return Text.assemble((etype.__name__, "ember.err.bold"), (f": {evalue}" if str(evalue) else "", "ember.fg"))
    if mode == "plain":
        import traceback

        lines = traceback.format_exception(etype, evalue, tb)
        text = _CELL_FILE.sub(lambda m: cell_label(int(m[1])), "".join(lines).rstrip())
        styled = Text(text, style="ember.muted")
        styled.highlight_regex(r"(?m)^\w[\w.]*(Error|Exception|Exit|Interrupt|Warning)\b.*$", "ember.err")
        return styled
    rendered = CellTraceback.from_exception(
        etype,
        evalue,
        tb,
        width=width,
        code_width=min(width - 8, 100),
        extra_lines=2 if mode == "context" else 3,
        theme=theme.syntax_theme,  # type: ignore[arg-type]
        word_wrap=True,
        show_locals=mode == "verbose",
        locals_hide_dunder=True,
        locals_hide_sunder=True,
        max_frames=30,
        suppress=[PKG_DIR],
        indent_guides=False,
    )
    for stack in rendered.trace.stacks:
        for frame in stack.frames:
            if m := _CELL_FILE.fullmatch(frame.filename):
                frame.filename = cell_label(int(m[1]))
            if frame.name == "<module>":
                frame.locals = None  # module "locals" are the whole namespace
    return rendered


def _signature(obj: Any) -> str | None:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return None


def render_inspect(expr: str, obj: Any, level: int, theme: Theme) -> RenderableType:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="ember.faint", no_wrap=True)
    grid.add_column(style="ember.fg", overflow="fold")

    kind = type(obj)
    grid.add_row("type", Text(f"{kind.__module__}.{kind.__qualname__}" if kind.__module__ != "builtins" else kind.__qualname__, style="ember.class"))
    if callable(obj) and (sig := _signature(obj)) is not None:
        name = getattr(obj, "__name__", expr)
        grid.add_row("signature", Syntax(f"{name}{sig}", "python", theme=theme.syntax_theme, background_color="default", word_wrap=True))
    elif not inspect.ismodule(obj):
        r = repr(obj)
        grid.add_row("value", Text(r if len(r) < 400 else r[:400] + " …", style="ember.fg"))
    try:
        length = len(obj)
        grid.add_row("length", str(length))
    except Exception:
        pass
    shape = getattr(obj, "shape", None)
    if isinstance(shape, tuple):
        grid.add_row("shape", " × ".join(map(str, shape)))
    try:
        file = inspect.getsourcefile(obj) or inspect.getfile(obj)
        try:
            _, lineno = inspect.getsourcelines(obj)
            file = f"{file}:{lineno}"
        except Exception:
            pass
        file = _CELL_FILE.sub(lambda m: cell_label(int(m[1])), short_path(file))
        grid.add_row("file", Text(file, style="repr.path"))
    except TypeError:
        pass

    parts: list[RenderableType] = [grid]
    doc = inspect.getdoc(obj)
    if doc and (level < 2 or not _has_source(obj)):
        parts.append(Text(""))
        parts.append(Text(doc, style="ember.muted"))
    if level >= 2:
        try:
            source = inspect.getsource(obj)
            _, start = inspect.getsourcelines(obj)
            parts.append(Text(""))
            parts.append(
                Syntax(
                    source.rstrip(),
                    "python",
                    theme=theme.syntax_theme,
                    background_color="default",
                    line_numbers=True,
                    start_line=max(start, 1),
                    word_wrap=True,
                )
            )
        except (TypeError, OSError):
            parts.append(Text("\nsource not available", style="ember.faint"))

    return Panel(
        Group(*parts),
        title=Text.assemble(("◆ ", "ember.accent"), (expr, "ember.fg.bold")),
        title_align="left",
        border_style="ember.border",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _has_source(obj: Any) -> bool:
    try:
        inspect.getsource(obj)
        return True
    except Exception:
        return False


def help_panel(magics: dict[str, dict[str, str]]) -> RenderableType:
    def grid(rows: list[tuple[str, str]]) -> Table:
        g = Table.grid(padding=(0, 2))
        g.add_column(style="ember.accent.bold", no_wrap=True)
        g.add_column(style="ember.muted")
        for k, v in rows:
            g.add_row(k, v)
        return g

    keys = grid([
        ("enter", "run cell (or newline if incomplete)"),
        ("alt+enter", "insert newline"),
        ("tab / shift+tab", "complete · indent / dedent"),
        ("→ / ctrl+e", "accept inline suggestion"),
        ("↑ ↓", "history (prefix-aware)"),
        ("ctrl+r", "search history"),
        ("ctrl+o", "edit cell in $EDITOR"),
        ("ctrl+l", "clear screen"),
        ("ctrl+c", "clear input · interrupt running cell"),
        ("ctrl+d", "exit"),
        ("\\alpha tab", "unicode α · \\N{name} tab"),
    ])
    syntax = grid([
        ("obj?  obj??", "inspect object · show source"),
        ("np.*load*?", "wildcard name search"),
        ("!cmd  !!cmd", "run shell command · capture its output"),
        ("x = !cmd", "capture output as an SList (.s .n .grep() .fields())"),
        ("$var  {expr}", "expand Python values in ! commands and magics"),
        ("%magic  magic", "line magic (the % is optional with automagic)"),
        ("%%magic", "cell magic (first line of cell)"),
        ("_  __  _N  Out[N]", "previous results · In[N], _i, _ii previous inputs"),
        ("await …", "top-level await (asyncio, trio or curio)"),
        (">>> pasted code", "prompts are stripped automatically"),
    ])

    def section(title: str, body: RenderableType) -> RenderableType:
        return Group(Text(title, style="ember.fg.bold"), Padding(body, (0, 0, 1, 2)))

    order = ["general", "namespace & inspection", "running & timing", "history & session", "shell & files",
             "gui & plotting", "aliases", "user"]
    parts = [section("keys", keys), section("syntax", syntax)]
    for category in sorted(magics, key=lambda c: order.index(c) if c in order else len(order)):
        parts.append(section(f"magics · {category}", grid(sorted(magics[category].items()))))
    parts.append(Text("%help name shows details for one magic", style="ember.faint"))
    return Panel(
        Group(*parts),
        title=Text.assemble(("✦ ", "ember.accent"), ("ember", "ember.fg.bold"), (" help", "ember.muted")),
        title_align="left",
        border_style="ember.border",
        box=box.ROUNDED,
        padding=(1, 2, 0, 2),
    )


def magic_help(spec: Any) -> RenderableType:
    prefix = "%%" if spec.kind == "cell" else "%"
    body: list[RenderableType] = [Text(spec.doc, style="ember.fg")]
    if spec.usage and spec.usage.strip() != spec.doc:
        body += [Text(""), Text(spec.usage.rstrip(), style="ember.muted")]
    body += [Text(""), Text(f"category: {spec.category}", style="ember.faint")]
    return Panel(
        Group(*body),
        title=Text.assemble(("✦ ", "ember.accent"), (prefix + spec.name, "ember.fg.bold")),
        title_align="left",
        border_style="ember.border",
        box=box.ROUNDED,
        padding=(0, 1),
    )

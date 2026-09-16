"""Turning Python objects, exceptions and introspection into rich renderables."""

from __future__ import annotations

import inspect
import os
import re
from pathlib import Path
from types import TracebackType
from typing import Any

from rich import box
from rich.console import Group, RenderableType
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
_CELL_FILE = re.compile(r"<cell-(\d+)>")


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


def render_value(value: Any) -> RenderableType:
    if _is_dataframe(value):
        try:
            return dataframe_table(value)
        except Exception:
            pass
    if not isinstance(value, (str, bytes)) and is_renderable(value):
        return value
    return Pretty(value, indent_guides=True, max_length=500, max_string=20_000)


def render_exception(
    etype: type[BaseException],
    evalue: BaseException,
    tb: TracebackType | None,
    theme: Theme,
    width: int,
) -> RenderableType:
    # Hide ember's own frames above the user's code.
    while tb is not None and tb.tb_frame.f_code.co_filename.startswith(PKG_DIR):
        tb = tb.tb_next
    if isinstance(evalue, KeyboardInterrupt):
        return Text("⏹  interrupted", style="ember.warn")
    rendered = CellTraceback.from_exception(
        etype,
        evalue,
        tb,
        width=width,
        code_width=min(width - 8, 100),
        extra_lines=2,
        theme=theme.syntax_theme,  # type: ignore[arg-type]
        word_wrap=True,
        max_frames=30,
        suppress=[PKG_DIR],
        indent_guides=False,
    )
    for stack in rendered.trace.stacks:
        for frame in stack.frames:
            if m := _CELL_FILE.fullmatch(frame.filename):
                frame.filename = cell_label(int(m[1]))
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


def help_panel(magics: dict[str, str]) -> RenderableType:
    keys = Table.grid(padding=(0, 2))
    keys.add_column(style="ember.accent.bold", no_wrap=True)
    keys.add_column(style="ember.muted")
    for k, v in [
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
    ]:
        keys.add_row(k, v)

    syntax = Table.grid(padding=(0, 2))
    syntax.add_column(style="ember.accent.bold", no_wrap=True)
    syntax.add_column(style="ember.muted")
    for k, v in [
        ("obj?  obj??", "inspect object · show source"),
        ("!cmd", "run shell command"),
        ("x = !cmd", "capture shell output as list of lines"),
        ("%magic args", "line magic"),
        ("%%magic", "cell magic (first line of cell)"),
        ("_  __  _N  Out[N]", "previous results"),
        ("In[N]", "previous inputs"),
        ("await …", "top-level await works"),
    ]:
        syntax.add_row(k, v)

    mg = Table.grid(padding=(0, 2))
    mg.add_column(style="ember.accent.bold", no_wrap=True)
    mg.add_column(style="ember.muted")
    for name, doc in sorted(magics.items()):
        mg.add_row(name, doc)

    def section(title: str, body: RenderableType) -> RenderableType:
        return Group(Text(title, style="ember.fg.bold"), Padding(body, (0, 0, 1, 2)))

    return Panel(
        Group(section("keys", keys), section("syntax", syntax), section("magics", mg)),
        title=Text.assemble(("✦ ", "ember.accent"), ("ember", "ember.fg.bold"), (" help", "ember.muted")),
        title_align="left",
        border_style="ember.border",
        box=box.ROUNDED,
        padding=(1, 2, 0, 2),
    )

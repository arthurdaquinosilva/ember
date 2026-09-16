"""Built-in %magics and %%cell magics."""

from __future__ import annotations

import ast
import os
import pdb
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import timeit
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from rich import box
from rich.columns import Columns
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ember.display import short_path
from ember.output import format_duration
from ember.theme import PALETTES

if TYPE_CHECKING:
    from ember.shell import Shell

LINE_MAGICS: dict[str, tuple[Callable, str]] = {}
CELL_MAGICS: dict[str, tuple[Callable, str]] = {}


def line_magic(*names: str, doc: str):
    def deco(fn):
        for n in names:
            LINE_MAGICS[n] = (fn, doc)
        return fn

    return deco


def cell_magic(*names: str, doc: str):
    def deco(fn):
        for n in names:
            CELL_MAGICS[n] = (fn, doc)
        return fn

    return deco


class MagicError(Exception):
    """An error raised by a magic, shown as a one-line message instead of a traceback."""


def magic_docs() -> dict[str, str]:
    groups: dict[tuple[Callable, str], tuple[list[str], str]] = {}
    for table, prefix in ((LINE_MAGICS, "%"), (CELL_MAGICS, "%%")):
        for name, (fn, doc) in table.items():
            groups.setdefault((fn, prefix), ([], doc))[0].append(prefix + name)
    return {", ".join(names): doc for names, doc in groups.values()}


# ── helpers ────────────────────────────────────────────────────────────────


def _compile_stmt(shell: Shell, src: str):
    """Compile as an expression if possible so %time can return a value."""
    try:
        return compile(src, "<magic>", "eval"), True
    except SyntaxError:
        return compile(src, "<magic>", "exec"), False


def _stream(shell: Shell, cmd: str | list[str], capture: bool = False) -> list[str] | None:
    env = dict(os.environ, FORCE_COLOR="1", CLICOLOR_FORCE="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        cmd,
        shell=isinstance(cmd, str),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode(errors="replace")
            if capture:
                lines.append(line.rstrip("\n"))
            else:
                sys.stdout.write(line)
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        raise
    if proc.returncode and not capture:
        shell.print(Text(f"exit {proc.returncode}", style="ember.err"))
    return lines if capture else None


# ── line magics ────────────────────────────────────────────────────────────


@line_magic("help", doc="show keys, syntax and magics")
def m_help(shell: Shell, args: str):
    from ember.display import help_panel

    shell.print(help_panel(magic_docs()))


@line_magic("time", doc="time a single statement or expression")
def m_time(shell: Shell, args: str):
    if not args.strip():
        raise MagicError("usage: %time <statement>")
    code, is_expr = _compile_stmt(shell, args)
    cpu0, wall0 = time.process_time(), time.perf_counter()
    result = eval(code, shell.ns) if is_expr else exec(code, shell.ns)
    wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
    shell.print(
        Text.assemble(
            ("wall ", "ember.faint"), (format_duration(wall), "ember.accent.bold"),
            ("  cpu ", "ember.faint"), (format_duration(cpu), "ember.fg"),
        )
    )
    return result


def _timeit(shell: Shell, stmt: str, setup: str = "pass", number: int = 0, repeat: int = 7):
    timer = timeit.Timer(stmt, setup, globals=shell.ns)
    if not number:
        number = 1
        while number < 10_000_000 and timer.timeit(number) < 0.2:
            number *= 10
    runs = [t / number for t in timer.repeat(repeat, number)]
    mean = statistics.fmean(runs)
    std = statistics.stdev(runs) if len(runs) > 1 else 0.0
    shell.print(
        Text.assemble(
            (format_duration(mean), "ember.accent.bold"),
            (" ± ", "ember.faint"),
            (format_duration(std), "ember.fg"),
            ("  per loop", "ember.muted"),
            (f"   best {format_duration(min(runs))} · {repeat} runs × {number:,} loops", "ember.faint"),
        )
    )


_TIMEIT_FLAG = re.compile(r"^\s*-([nr])\s+(\d+)")


def _parse_timeit_args(args: str) -> tuple[str, int, int]:
    opts = {"n": 0, "r": 7}
    while m := _TIMEIT_FLAG.match(args):
        opts[m[1]] = int(m[2])
        args = args[m.end():]
    return args.strip(), opts["n"], opts["r"]


@line_magic("timeit", doc="benchmark a statement (-n loops, -r runs)")
def m_timeit(shell: Shell, args: str):
    stmt, number, repeat = _parse_timeit_args(args)
    if not stmt.strip():
        raise MagicError("usage: %timeit [-n N] [-r R] <statement>")
    _timeit(shell, stmt, number=number, repeat=repeat)


def _user_vars(shell: Shell) -> dict[str, Any]:
    return {
        k: v
        for k, v in shell.ns.items()
        if not k.startswith("_") and k not in shell.initial_names and not (k in ("In", "Out", "exit", "quit"))
    }


@line_magic("who", doc="list user variables")
def m_who(shell: Shell, args: str):
    names = sorted(_user_vars(shell))
    if not names:
        shell.print(Text("no variables defined", style="ember.faint"))
        return
    shell.print(Columns([Text(n, style="ember.fg") for n in names], padding=(0, 3)))


@line_magic("whos", "vars", doc="table of user variables with types and values")
def m_whos(shell: Shell, args: str):
    items = _user_vars(shell)
    if not items:
        shell.print(Text("no variables defined", style="ember.faint"))
        return
    table = Table(box=box.SIMPLE_HEAD, border_style="ember.border", header_style="ember.accent.bold", show_edge=False, pad_edge=False)
    table.add_column("name", style="ember.fg.bold", no_wrap=True)
    table.add_column("type", style="ember.class", no_wrap=True)
    table.add_column("info", style="ember.muted", overflow="ellipsis", no_wrap=True, max_width=80)
    import inspect as _inspect

    for name, value in sorted(items.items()):
        if _inspect.ismodule(value):
            info = getattr(value, "__file__", None) or "built-in"
            info = short_path(info)
        elif _inspect.isfunction(value) or _inspect.isclass(value):
            try:
                info = f"{name}{_inspect.signature(value)}"
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


@line_magic("reset", doc="clear all user variables")
def m_reset(shell: Shell, args: str):
    n = 0
    for k in list(_user_vars(shell)):
        del shell.ns[k]
        n += 1
    shell.Out.clear()
    for k in [k for k in shell.ns if k.startswith("_") and k.lstrip("_").isdigit() or k in ("_", "__", "___")]:
        del shell.ns[k]
    shell.print(Text(f"cleared {n} variable{'s' if n != 1 else ''}", style="ember.muted"))


@line_magic("run", doc="run a python file in the shell namespace")
def m_run(shell: Shell, args: str):
    argv = shlex.split(args)
    if not argv:
        raise MagicError("usage: %run file.py [args…]")
    path = Path(argv[0]).expanduser()
    if not path.exists():
        raise MagicError(f"no such file: {path}")
    source = path.read_text()
    code = compile(source, str(path.resolve()), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    saved_argv = sys.argv
    sys.argv = [str(path), *argv[1:]]
    saved_file = shell.ns.get("__file__")
    shell.ns["__file__"] = str(path.resolve())
    sys.path.insert(0, str(path.resolve().parent))
    try:
        shell.run_code(code)
    finally:
        sys.argv = saved_argv
        sys.path.remove(str(path.resolve().parent))
        if saved_file is None:
            shell.ns.pop("__file__", None)
        else:
            shell.ns["__file__"] = saved_file


@line_magic("load", doc="load a file (or In[N]) into the next prompt")
def m_load(shell: Shell, args: str):
    target = args.strip()
    if target.isdigit():
        shell.next_input = shell.In[int(target)]
    else:
        path = Path(target).expanduser()
        if not path.exists():
            raise MagicError(f"no such file: {path}")
        shell.next_input = path.read_text().rstrip()
    shell.print(Text("loaded into prompt ↓", style="ember.muted"))


@line_magic("edit", doc="edit a file or the last cell in $EDITOR, then load it")
def m_edit(shell: Shell, args: str):
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    target = args.strip()
    shell.pause_output()
    if target and not target.isdigit():
        subprocess.call([*shlex.split(editor), target])
        shell.next_input = f"%run {target}"
        return
    initial = shell.In[int(target)] if target.isdigit() else (shell.In[-2] if len(shell.In) > 2 else "")
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
        f.write(initial)
        name = f.name
    try:
        subprocess.call([*shlex.split(editor), name])
        shell.next_input = Path(name).read_text().rstrip()
    finally:
        os.unlink(name)


@line_magic("pip", doc="run pip for this interpreter")
def m_pip(shell: Shell, args: str):
    _stream(shell, [sys.executable, "-m", "pip", *shlex.split(args)])
    if args.split()[:1] in (["install"], ["uninstall"]):
        import importlib

        importlib.invalidate_caches()
        shell.print(Text("restart ember if an already-imported package changed", style="ember.faint"))


@line_magic("cd", doc="change directory (supports ~ and -)")
def m_cd(shell: Shell, args: str):
    target = args.strip() or "~"
    if target == "-":
        target = shell.prev_dir or os.getcwd()
    path = Path(target).expanduser()
    if not path.is_dir():
        raise MagicError(f"not a directory: {target}")
    shell.prev_dir = os.getcwd()
    os.chdir(path)
    shell.print(Text(short_path(os.getcwd()), style="repr.path"))


@line_magic("pwd", doc="print working directory")
def m_pwd(shell: Shell, args: str):
    return os.getcwd()


@line_magic("ls", doc="list a directory")
def m_ls(shell: Shell, args: str):
    show_all = "-a" in args.split()
    target = next((a for a in args.split() if not a.startswith("-")), ".")
    path = Path(target).expanduser()
    if not path.exists():
        raise MagicError(f"no such file or directory: {target}")
    entries = sorted(path.iterdir() if path.is_dir() else [path], key=lambda p: (not p.is_dir(), p.name.lower()))
    items = []
    for e in entries:
        if e.name.startswith(".") and not show_all:
            continue
        if e.is_dir():
            items.append(Text.assemble(("▸ ", "ember.faint"), (e.name + "/", "ember.info.bold")))
        elif e.suffix == ".py":
            items.append(Text.assemble(("◆ ", "ember.accent"), (e.name, "ember.fg")))
        elif os.access(e, os.X_OK):
            items.append(Text.assemble(("● ", "ember.ok"), (e.name, "ember.ok")))
        else:
            items.append(Text.assemble(("  ", ""), (e.name, "ember.muted")))
    if not items:
        shell.print(Text("empty", style="ember.faint"))
    else:
        shell.print(Columns(items, padding=(0, 3)))


@line_magic("history", "hist", doc="show input history (-n N for last N)")
def m_history(shell: Shell, args: str):
    parts = args.split()
    n = int(parts[parts.index("-n") + 1]) if "-n" in parts else 20
    start = max(1, len(shell.In) - n)
    for i in range(start, len(shell.In)):
        src = shell.In[i]
        shell.print(Text(f"{i:>4} ", style="ember.faint"), end="")
        shell.print(Syntax(src, "python", theme=shell.theme.syntax_theme, background_color="default"))


@line_magic("save", doc="save session inputs to a file")
def m_save(shell: Shell, args: str):
    target = args.strip()
    if not target:
        raise MagicError("usage: %save file.py")
    cells = [c for c in shell.In[1:-1] if not c.lstrip().startswith(("%", "!"))]
    Path(target).expanduser().write_text("\n\n".join(cells) + "\n")
    shell.print(Text(f"saved {len(cells)} cells → {target}", style="ember.muted"))


@line_magic("clear", "cls", doc="clear the screen")
def m_clear(shell: Shell, args: str):
    sys.__stdout__.write("\x1b[2J\x1b[3J\x1b[H")
    sys.__stdout__.flush()
    shell.suppress_footer = True


@line_magic("theme", doc="list or switch color themes")
def m_theme(shell: Shell, args: str):
    name = args.strip()
    if not name:
        for n, p in PALETTES.items():
            mark = "●" if n == shell.theme.name else "○"
            swatch = Text.assemble(*[("██", c) for c in (p.accent, p.accent2, p.keyword, p.string, p.builtin, p.number)])
            shell.print(Text.assemble((f"{mark} ", p.accent), (f"{n:<10}", "ember.fg.bold"), swatch))
        return
    if name not in PALETTES:
        raise MagicError(f"unknown theme {name!r} — try: {', '.join(PALETTES)}")
    shell.set_theme(name)
    shell.print(Text.assemble(("theme → ", "ember.muted"), (name, "ember.accent.bold")))


@line_magic("env", doc="show env vars, or %env NAME / %env NAME=value")
def m_env(shell: Shell, args: str):
    a = args.strip()
    if "=" in a:
        k, v = a.split("=", 1)
        os.environ[k.strip()] = v.strip()
        return
    if a:
        return os.environ.get(a)
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="ember.accent.bold", no_wrap=True)
    table.add_column(style="ember.muted", overflow="fold")
    for k in sorted(os.environ):
        table.add_row(k, os.environ[k])
    shell.print(table)


@line_magic("autoreload", doc="toggle reloading changed modules before each cell")
def m_autoreload(shell: Shell, args: str):
    a = args.strip().lower()
    shell.autoreload.enabled = {"on": True, "1": True, "off": False, "0": False}.get(a, not shell.autoreload.enabled)
    if shell.autoreload.enabled:
        shell.autoreload.snapshot()
    state = ("on", "ember.ok") if shell.autoreload.enabled else ("off", "ember.muted")
    shell.print(Text.assemble(("autoreload ", "ember.muted"), state))


@line_magic("debug", doc="post-mortem debugger on the last exception")
def m_debug(shell: Shell, args: str):
    tb = shell.last_traceback
    if tb is None:
        raise MagicError("no exception to debug")
    shell.pause_output()
    pdb.post_mortem(tb)


@line_magic("copy", doc="copy the last result (or an expression) to the clipboard")
def m_copy(shell: Shell, args: str):
    value = eval(args, shell.ns) if args.strip() else shell.ns.get("_")
    text = value if isinstance(value, str) else repr(value)
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["clip.exe"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text.encode(), check=False)
            shell.print(Text(f"copied {len(text):,} chars", style="ember.muted"))
            return
    raise MagicError("no clipboard tool found")


@line_magic("exit", "quit", doc="leave ember")
def m_exit(shell: Shell, args: str):
    raise SystemExit(0)


# ── cell magics ────────────────────────────────────────────────────────────


@cell_magic("time", doc="time the whole cell")
def c_time(shell: Shell, args: str, body: str):
    from ember.transform import transform

    cpu0, wall0 = time.process_time(), time.perf_counter()
    result = shell.execute(transform(body), shell.current_filename)
    wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
    shell.print(
        Text.assemble(
            ("wall ", "ember.faint"), (format_duration(wall), "ember.accent.bold"),
            ("  cpu ", "ember.faint"), (format_duration(cpu), "ember.fg"),
        )
    )
    return result


@cell_magic("timeit", doc="benchmark the cell body (first-line args = setup)")
def c_timeit(shell: Shell, args: str, body: str):
    setup, number, repeat = _parse_timeit_args(args)
    _timeit(shell, body, setup=setup or "pass", number=number, repeat=repeat)


@cell_magic("writefile", doc="write the cell body to a file (-a to append)")
def c_writefile(shell: Shell, args: str, body: str):
    parts = shlex.split(args)
    append = "-a" in parts
    target = next((p for p in parts if p != "-a"), None)
    if not target:
        raise MagicError("usage: %%writefile [-a] path")
    path = Path(target).expanduser()
    with path.open("a" if append else "w") as f:
        f.write(body if body.endswith("\n") else body + "\n")
    shell.print(Text(f"{'appended to' if append else 'wrote'} {short_path(path)}", style="ember.muted"))


@cell_magic("bash", "sh", doc="run the cell as a shell script")
def c_bash(shell: Shell, args: str, body: str):
    _stream(shell, ["bash", "-c", body])

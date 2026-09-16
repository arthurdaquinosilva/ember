"""Running & timing magics: %time, %timeit, %prun, %run, %%capture."""

from __future__ import annotations

import cProfile
import io
import math
import os
import pstats
import runpy
import sys
import time
import timeit
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from rich import box
from rich.table import Table
from rich.text import Text

from ember.magics import MagicError, cell_magic, line_magic, parse_args
from ember.output import format_duration
from ember.utils import arg_split

if TYPE_CHECKING:
    from ember.shell import Shell


def _timing_line(wall: float, cpu: float) -> Text:
    return Text.assemble(
        ("wall ", "ember.faint"), (format_duration(wall), "ember.accent.bold"),
        ("  cpu ", "ember.faint"), (format_duration(cpu), "ember.fg"),
    )


# ── %time ──────────────────────────────────────────────────────────────────


@line_magic("time", doc="time a single statement or expression", expand=False)
def m_time(shell: Shell, args: str):
    if not args.strip():
        raise MagicError("usage: %time <statement>")
    cpu0, wall0 = time.process_time(), time.perf_counter()
    try:
        return shell.execute(shell.transform(args), shell.current_filename, interactivity="last_expr")
    finally:
        shell.print(_timing_line(time.perf_counter() - wall0, time.process_time() - cpu0))


@cell_magic("time", doc="time the whole cell", expand=False)
def c_time(shell: Shell, args: str, body: str):
    cpu0, wall0 = time.process_time(), time.perf_counter()
    try:
        return shell.execute(shell.transform(body), shell.current_filename)
    finally:
        shell.print(_timing_line(time.perf_counter() - wall0, time.process_time() - cpu0))


# ── %timeit ────────────────────────────────────────────────────────────────


class TimeitResult:
    """Returned by `%timeit -o`: `.average`, `.stdev`, `.best`, `.worst`, `.all_runs`, `.loops`, `.repeat`."""

    def __init__(self, loops: int, repeat: int, best: float, worst: float, all_runs: list[float], compile_time: float, precision: int):
        self.loops = loops
        self.repeat = repeat
        self.best = best
        self.worst = worst
        self.all_runs = all_runs
        self.compile_time = compile_time
        self._precision = precision
        self.timings = [t / loops for t in all_runs]

    @property
    def average(self) -> float:
        return math.fsum(self.timings) / len(self.timings)

    @property
    def stdev(self) -> float:
        mean = self.average
        return (math.fsum((x - mean) ** 2 for x in self.timings) / len(self.timings)) ** 0.5

    def __str__(self) -> str:
        return (f"{format_duration(self.average)} ± {format_duration(self.stdev)} per loop "
                f"(mean ± std. dev. of {self.repeat} runs, {self.loops:,} loops each)")

    __repr__ = __str__

    def __rich__(self) -> Text:
        return Text.assemble(
            (format_duration(self.average), "ember.accent.bold"),
            (" ± ", "ember.faint"),
            (format_duration(self.stdev), "ember.fg"),
            ("  per loop", "ember.muted"),
            (f"   best {format_duration(self.best)} · {self.repeat} runs × {self.loops:,} loops", "ember.faint"),
        )

    def _repr_pretty_(self, p: Any, cycle: bool) -> None:
        p.text(str(self))


def _timeit(shell: Shell, stmt: str, setup: str, opts: Any) -> TimeitResult | None:
    number = int(opts.get("n", 0))
    repeat = int(opts.get("r", 7))
    precision = int(opts.get("p", 3))
    stmt = shell.transform(stmt)
    setup = shell.transform(setup) if setup.strip() else "pass"
    t0 = time.perf_counter()
    try:
        timer = timeit.Timer(stmt, setup, globals=shell.ns)
    except SyntaxError as e:
        raise MagicError(f"syntax error in statement: {e.msg}") from None
    compile_time = time.perf_counter() - t0
    if not number:
        number = 1
        while number < 10_000_000 and timer.timeit(number) < 0.2:
            number *= 10
    runs = timer.repeat(repeat, number)
    per_loop = [t / number for t in runs]
    result = TimeitResult(number, repeat, min(per_loop), max(per_loop), runs, compile_time, precision)
    if not opts.get("q"):
        shell.print(result)
        if result.worst > result.best * 4 and result.worst > 1e-6:
            shell.print(Text("⚠ slowest run took much longer than the fastest — results may be cached or noisy", style="ember.warn"))
    return result if opts.get("o") else None


@line_magic("timeit", doc="benchmark a statement (-n loops -r runs -p precision -q quiet -o return result)", expand=False)
def m_timeit(shell: Shell, args: str):
    opts, stmt = parse_args(args, "n:r:p:t:c:qo")
    if not stmt:
        raise MagicError("usage: %timeit [-n N] [-r R] [-q] [-o] statement")
    return _timeit(shell, stmt, "", opts)


@cell_magic("timeit", doc="benchmark the cell body; the first-line text is setup code", expand=False)
def c_timeit(shell: Shell, args: str, body: str):
    opts, setup = parse_args(args, "n:r:p:t:c:qo")
    return _timeit(shell, body, setup, opts)


# ── %prun ──────────────────────────────────────────────────────────────────

_SORT_KEYS = {"calls", "cumulative", "cumtime", "file", "filename", "module", "ncalls", "pcalls", "line", "name",
              "nfl", "stdname", "time", "tottime"}


def _render_stats(shell: Shell, stats: pstats.Stats, sort: list[str], limit: int) -> None:
    from ember.display import _CELL_FILE, PKG_DIR, cell_label

    def ours(func: tuple) -> bool:
        return func[0].startswith(PKG_DIR) or "_lsprof.Profiler" in func[2]

    stats.sort_stats(*sort)
    rows = [f for f in (stats.fcn_list or []) if not ours(f)][:limit]  # type: ignore[attr-defined]
    table = Table(box=box.SIMPLE_HEAD, border_style="ember.border", header_style="ember.accent.bold", show_edge=False, pad_edge=False)
    for col, justify in (("ncalls", "right"), ("tottime", "right"), ("percall", "right"), ("cumtime", "right"),
                         ("percall", "right"), ("function", "left")):
        table.add_column(col, justify=justify, no_wrap=col != "function", style="ember.fg" if col == "function" else "ember.muted")
    for func in rows:
        cc, nc, tt, ct, _ = stats.stats[func]  # type: ignore[attr-defined]
        calls = f"{nc}/{cc}" if nc != cc else str(nc)
        filename, line, name = func
        if m := _CELL_FILE.fullmatch(filename):
            filename = cell_label(int(m[1]))
        where = name if filename == "~" else f"{os.path.basename(filename)}:{line}({name})"
        table.add_row(calls, f"{tt:.4f}", f"{tt / nc:.4f}" if nc else "-", f"{ct:.4f}", f"{ct / cc:.4f}" if cc else "-", where)
    total = getattr(stats, "total_tt", 0.0)
    shell.print(Text.assemble((f"{stats.total_calls:,} function calls", "ember.fg"), (f" in {total:.3f}s", "ember.muted"),  # type: ignore[attr-defined]
                              (f" · sorted by {', '.join(sort)}", "ember.faint")))
    shell.print(table)


def _prun(shell: Shell, code: str, opts: Any) -> pstats.Stats | None:
    sort = opts.get("s", "cumulative")
    sort = sort if isinstance(sort, list) else [sort]
    bad = [s for s in sort if s not in _SORT_KEYS]
    if bad:
        raise MagicError(f"unknown sort key {bad[0]!r} — try: {', '.join(sorted(_SORT_KEYS))}")
    limit = int(opts.get("l", 25))
    profiler = cProfile.Profile()
    source = shell.transform(code)
    try:
        profiler.enable()
        try:
            shell.execute(source, shell.current_filename, interactivity="none")
        finally:
            profiler.disable()
    except SystemExit:
        pass
    stats = pstats.Stats(profiler)
    if dump := opts.get("D"):
        stats.dump_stats(dump)
        shell.print(Text(f"profile data dumped to {dump}", style="ember.muted"))
    if text_file := opts.get("T"):
        buf = io.StringIO()
        pstats.Stats(profiler, stream=buf).sort_stats(*sort).print_stats(limit)
        Path(text_file).write_text(buf.getvalue())
        shell.print(Text(f"profile report written to {text_file}", style="ember.muted"))
    if not opts.get("q"):
        _render_stats(shell, stats, sort, limit)
    return stats if opts.get("r") else None


@line_magic("prun", doc="profile a statement (-s sort -l limit -r return stats -q -D dumpfile -T textfile)", expand=False)
def m_prun(shell: Shell, args: str):
    opts, stmt = parse_args(args, "s:l:rqD:T:")
    if not stmt:
        raise MagicError("usage: %prun [-s key] [-l limit] statement")
    return _prun(shell, stmt, opts)


@cell_magic("prun", doc="profile the cell body", expand=False)
def c_prun(shell: Shell, args: str, body: str):
    opts, _ = parse_args(args, "s:l:rqD:T:")
    return _prun(shell, body, opts)


# ── %run ───────────────────────────────────────────────────────────────────

RUN_USAGE = """%run [options] file.py [args…]
  -i       run in the shell's namespace (default: fresh namespace, merged back afterwards)
  -n       don't set __name__ to "__main__"
  -e       ignore sys.exit() calls
  -t       print timing (-N count repeats it)
  -d       run under the debugger (-b file:line sets a breakpoint)
  -p       profile with cProfile (accepts %prun's -s/-l/-D/-T options)
  -m mod   run a module like `python -m`"""


@contextmanager
def _argv(argv: list[str], path_entry: str | None) -> Iterator[None]:
    saved = sys.argv
    sys.argv = argv
    if path_entry:
        sys.path.insert(0, path_entry)
    try:
        yield
    finally:
        sys.argv = saved
        if path_entry and path_entry in sys.path:
            sys.path.remove(path_entry)


def _merge(shell: Shell, ns: dict[str, Any]) -> None:
    for key, value in ns.items():
        if not (key.startswith("__") and key.endswith("__")):
            shell.ns[key] = value


@line_magic("run", doc="run a python file or module (-i -n -e -t -d -p -m; see %help run)", usage=RUN_USAGE)
def m_run(shell: Shell, args: str):
    opts, rest = parse_args(args, "inetN:db:pm:s:l:rqD:T:")
    argv = arg_split(rest, posix=True)

    if module := opts.get("m"):
        with _argv([module, *argv], os.getcwd()):
            try:
                ns = runpy.run_module(module, run_name="__main__" if not opts.get("n") else module, alter_sys=True)
            except SystemExit as e:
                if not opts.get("e") and e.code not in (0, None):
                    raise MagicError(f"{module} exited with status {e.code}") from None
                return
        _merge(shell, ns)
        return

    if not argv:
        raise MagicError("usage: " + RUN_USAGE.split("\n")[0])
    path = Path(argv[0]).expanduser()
    if not path.exists() and path.suffix == "" and Path(f"{path}.py").exists():
        path = Path(f"{path}.py")
    if not path.exists():
        raise MagicError(f"no such file: {path}")
    full = str(path.resolve())
    source = path.read_text()
    if path.suffix == ".ipy":
        source = shell.transform(source)

    if opts.get("i"):
        ns = shell.ns
        saved_name, saved_file = ns.get("__name__"), ns.get("__file__")
    else:
        ns = {"__builtins__": __builtins__, "__doc__": None, "__package__": None}
    ns["__name__"] = "__main__" if not opts.get("n") else path.stem
    ns["__file__"] = full

    try:
        code = compile(source, full, "exec", flags=shell.compile_flags)
        with _argv([full, *argv[1:]], str(path.resolve().parent)):
            try:
                if opts.get("d"):
                    _run_debug(shell, code, ns, full, opts.get("b"))
                elif opts.get("p"):
                    _run_profiled(shell, code, ns, opts)
                elif opts.get("t"):
                    _run_timed(shell, code, ns, int(opts.get("N", 1)))
                else:
                    shell.run_code(code, ns)
            except SystemExit as e:
                if not opts.get("e") and e.code not in (0, None):
                    raise MagicError(f"{path.name} exited with status {e.code}") from None
    finally:
        if opts.get("i"):
            ns["__name__"] = saved_name
            if saved_file is None:
                ns.pop("__file__", None)
            else:
                ns["__file__"] = saved_file
        else:
            _merge(shell, ns)


def _run_timed(shell: Shell, code: Any, ns: dict, repeats: int) -> None:
    walls, cpus = [], []
    for _ in range(max(1, repeats)):
        cpu0, wall0 = time.process_time(), time.perf_counter()
        shell.run_code(code, ns)
        walls.append(time.perf_counter() - wall0)
        cpus.append(time.process_time() - cpu0)
    line = _timing_line(sum(walls), sum(cpus))
    if repeats > 1:
        line.append(f"   {repeats} runs · {format_duration(sum(walls) / repeats)} each", style="ember.faint")
    shell.print(line)


def _run_profiled(shell: Shell, code: Any, ns: dict, opts: Any) -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        shell.run_code(code, ns)
    finally:
        profiler.disable()
        sort = opts.get("s", "cumulative")
        _render_stats(shell, pstats.Stats(profiler), sort if isinstance(sort, list) else [sort], int(opts.get("l", 25)))


def _run_debug(shell: Shell, code: Any, ns: dict, filename: str, breakpoint: str | None) -> None:
    debugger = shell.debugger()
    shell.pause_output()
    if breakpoint:
        file, _, line = breakpoint.rpartition(":") if ":" in breakpoint else (filename, "", breakpoint)
        err = debugger.set_break(os.path.abspath(file) if file else filename, int(line))
        if err:
            raise MagicError(err)
    shell.print(Text("entering debugger — type c to continue, q to quit", style="ember.faint"))
    debugger.run(code, ns)


# ── %%capture ──────────────────────────────────────────────────────────────


class CapturedIO:
    """Output captured by `%%capture`: `.stdout`, `.stderr`, `.outputs`, and `.show()` / call to replay."""

    def __init__(self, stdout: str, stderr: str, outputs: list[Any]):
        self.stdout = stdout
        self.stderr = stderr
        self.outputs = outputs

    def show(self) -> None:
        if self.stdout:
            sys.stdout.write(self.stdout)
        if self.stderr:
            sys.stderr.write(self.stderr)
        from ember.shell import Shell

        for renderable in self.outputs:
            if Shell.active:
                Shell.active.print(renderable)

    __call__ = show

    def __repr__(self) -> str:
        return f"<CapturedIO stdout={len(self.stdout)} chars, stderr={len(self.stderr)} chars, outputs={len(self.outputs)}>"


@cell_magic("capture", doc="capture stdout/stderr/displays: %%capture [var] [--no-stdout] [--no-stderr] [--no-display]")
def c_capture(shell: Shell, args: str, body: str):
    opts, rest = parse_args(args, "", "no-stdout", "no-stderr", "no-display")
    var = rest.split()[0] if rest.split() else None
    out, err = io.StringIO(), io.StringIO()
    outputs: list[Any] = []
    real_out, real_err = sys.stdout, sys.stderr
    keep_displays = not opts.get("no-display")
    with redirect_stdout(real_out if opts.get("no-stdout") else out), redirect_stderr(real_err if opts.get("no-stderr") else err):
        with shell.capture_displays(outputs if keep_displays else None):
            shell.execute(shell.transform(body), shell.current_filename, on_value=shell.print_value)
    captured = CapturedIO(out.getvalue(), err.getvalue(), outputs)
    if var:
        shell.ns[var] = captured


# ── %paste / %cpaste ───────────────────────────────────────────────────────


def _run_pasted(shell: Shell, block: str, quiet: bool) -> None:
    from ember.transform import strip_prompts

    block = strip_prompts(block).rstrip()
    if not block.strip():
        raise MagicError("nothing to paste")
    shell.ns["pasted_block"] = block
    if not quiet:
        from rich.syntax import Syntax

        shell.print(Syntax(block, "python", theme=shell.theme.syntax_theme, background_color="default", word_wrap=True))
        shell.print(Text("── end of paste ──", style="ember.faint"))
    shell.execute(shell.transform(block), shell.current_filename, on_value=shell.print_value)


@line_magic("paste", doc="run code from the clipboard (prompts stripped): -q quiet · -r rerun last paste")
def m_paste(shell: Shell, args: str):
    import shutil
    import subprocess

    opts, _ = parse_args(args, "qr")
    if opts.get("r"):
        block = shell.ns.get("pasted_block")
        if not block:
            raise MagicError("nothing has been pasted yet")
        _run_pasted(shell, block, True)
        return
    for cmd in (["pbpaste"], ["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["powershell.exe", "Get-Clipboard"]):
        if shutil.which(cmd[0]):
            text = subprocess.run(cmd, capture_output=True, check=False).stdout.decode(errors="replace")
            break
    else:
        raise MagicError("no clipboard tool found — use %cpaste")
    _run_pasted(shell, text.replace("\r\n", "\n"), bool(opts.get("q")))


@line_magic("cpaste", doc="paste a block, end with a line containing only -- (or ctrl+d); prompts are stripped")
def m_cpaste(shell: Shell, args: str):
    opts, _ = parse_args(args, "qs:")
    sentinel = str(opts.get("s", "--"))
    shell.pause_output()
    shell.print(Text(f"pasting — end with {sentinel!r} alone on a line, or ctrl+d", style="ember.faint"))
    lines = []
    while True:
        try:
            line = input(":")
        except EOFError:
            break
        if line.strip() == sentinel:
            break
        lines.append(line)
    _run_pasted(shell, "\n".join(lines), True)

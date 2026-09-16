"""Shell & file magics: cd/bookmarks/dir stack, ls, env, pip, aliases, sx, %%script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich import box
from rich.columns import Columns
from rich.table import Table
from rich.text import Text

from ember.display import short_path
from ember.magics import LINE_MAGICS, MagicError, MagicSpec, cell_magic, line_magic, parse_args
from ember.utils import SList, arg_split

if TYPE_CHECKING:
    from ember.shell import Shell


# ── running commands ───────────────────────────────────────────────────────


def run_command(shell: Shell, cmd: str | list[str], capture: bool = False, stdin: str | None = None) -> SList | int:
    """Stream a command's output through the cell (or capture it as an SList). Returns the exit code when streaming."""
    env = dict(os.environ, FORCE_COLOR="1", CLICOLOR_FORCE="1", PYTHONUNBUFFERED="1")
    if capture:
        env.pop("FORCE_COLOR")
        env.pop("CLICOLOR_FORCE")
    proc = subprocess.Popen(
        cmd,
        shell=isinstance(cmd, str),
        stdin=subprocess.PIPE if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    assert proc.stdout is not None
    if stdin is not None:
        assert proc.stdin is not None
        threading.Thread(target=_feed, args=(proc.stdin, stdin), daemon=True).start()
    lines = SList()
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
    if capture:
        return lines
    if proc.returncode:
        shell.print(Text(f"exit {proc.returncode}", style="ember.err"))
    return proc.returncode


def _feed(pipe: Any, data: str) -> None:
    try:
        pipe.write(data.encode())
    finally:
        pipe.close()


@line_magic("sx", "system", doc="run a shell command and return its output lines (same as !!cmd)")
def m_sx(shell: Shell, args: str):
    return shell.getoutput(args)


# ── directories ────────────────────────────────────────────────────────────


def _bookmarks(shell: Shell) -> dict[str, str]:
    if shell.profile is None:
        return {}
    try:
        return json.loads(shell.profile.bookmarks_file.read_text())
    except (OSError, ValueError):
        return {}


def _save_bookmarks(shell: Shell, marks: dict[str, str]) -> None:
    if shell.profile is None:
        raise MagicError("bookmarks need a profile directory")
    shell.profile.bookmarks_file.parent.mkdir(parents=True, exist_ok=True)
    shell.profile.bookmarks_file.write_text(json.dumps(marks, indent=2, sort_keys=True))


def change_dir(shell: Shell, target: str | os.PathLike, quiet: bool = False) -> None:
    path = Path(target).expanduser()
    if not path.is_dir():
        raise MagicError(f"not a directory: {target}")
    shell.prev_dir = os.getcwd()
    os.chdir(path)
    cwd = os.getcwd()
    if not shell.dir_history or shell.dir_history[-1] != cwd:
        shell.dir_history.append(cwd)
    if not quiet:
        shell.print(Text(short_path(cwd), style="repr.path"))


@line_magic("cd", doc="change directory: ~ · - · -N (from %dhist) · -b bookmark · -q quiet",
            usage="""%cd [-q] [dir]     go to dir (default ~); falls back to a bookmark of that name
%cd -              go back to the previous directory
%cd -N             go to entry N of %dhist
%cd -b name        go to a bookmark""")
def m_cd(shell: Shell, args: str):
    opts, target = parse_args(args, "qb")
    quiet = bool(opts.get("q"))
    target = target.strip().strip("'\"")
    if opts.get("b"):
        marks = _bookmarks(shell)
        if target not in marks:
            raise MagicError(f"no bookmark {target!r}")
        change_dir(shell, marks[target], quiet)
        return
    if target == "-":
        change_dir(shell, shell.prev_dir or os.getcwd(), quiet)
        return
    if target.startswith("-") and target[1:].isdigit():
        index = int(target[1:])
        if index >= len(shell.dir_history):
            raise MagicError(f"directory history only has {len(shell.dir_history)} entries")
        change_dir(shell, shell.dir_history[index], quiet)
        return
    target = target or "~"
    if not Path(target).expanduser().is_dir() and target in (marks := _bookmarks(shell)):
        target = marks[target]
    change_dir(shell, target, quiet)


@line_magic("pwd", doc="return the working directory")
def m_pwd(shell: Shell, args: str):
    return os.getcwd()


@line_magic("bookmark", doc="bookmark directories: %bookmark name [dir] · -l list · -d name · -r remove all")
def m_bookmark(shell: Shell, args: str):
    opts, rest = parse_args(args, "ldr")
    marks = _bookmarks(shell)
    parts = rest.split(None, 1)
    if opts.get("r"):
        _save_bookmarks(shell, {})
        return
    if opts.get("d"):
        if not parts or parts[0] not in marks:
            raise MagicError("usage: %bookmark -d existing_name")
        del marks[parts[0]]
        _save_bookmarks(shell, marks)
        return
    if opts.get("l") or not parts:
        if not marks:
            shell.print(Text("no bookmarks", style="ember.faint"))
            return
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="ember.accent.bold")
        grid.add_column(style="repr.path")
        for name, path in sorted(marks.items()):
            grid.add_row(name, short_path(path))
        shell.print(grid)
        return
    name = parts[0]
    path = os.path.abspath(os.path.expanduser(parts[1])) if len(parts) > 1 else os.getcwd()
    marks[name] = path
    _save_bookmarks(shell, marks)
    shell.print(Text.assemble(("bookmark ", "ember.muted"), (name, "ember.accent.bold"), (" → ", "ember.faint"), (short_path(path), "repr.path")))


@line_magic("pushd", doc="push the current directory on the stack and cd")
def m_pushd(shell: Shell, args: str):
    here = os.getcwd()
    target = args.strip() or "~"
    if not Path(target).expanduser().is_dir() and target in (marks := _bookmarks(shell)):
        target = marks[target]
    change_dir(shell, target)
    shell.dir_stack.insert(0, here)
    return list(shell.dir_stack)


@line_magic("popd", doc="pop a directory off the stack and cd there")
def m_popd(shell: Shell, args: str):
    if not shell.dir_stack:
        raise MagicError("directory stack is empty")
    change_dir(shell, shell.dir_stack.pop(0))


@line_magic("dirs", doc="return the directory stack")
def m_dirs(shell: Shell, args: str):
    return list(shell.dir_stack)


@line_magic("dhist", doc="show visited directories: %dhist [N | from to]")
def m_dhist(shell: Shell, args: str):
    history = shell.dir_history
    nums = [int(x) for x in args.split() if x.lstrip("-").isdigit()]
    if len(nums) == 1:
        start, stop = max(0, len(history) - nums[0]), len(history)
    elif len(nums) >= 2:
        start, stop = nums[0], nums[1]
    else:
        start, stop = 0, len(history)
    if not history:
        shell.print(Text("no directory history", style="ember.faint"))
        return
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="ember.faint")
    grid.add_column(style="repr.path")
    for i in range(start, min(stop, len(history))):
        grid.add_row(str(i), short_path(history[i]))
    shell.print(grid)


@line_magic("ls", doc="list a directory (-a shows hidden files)")
def m_ls(shell: Shell, args: str):
    show_all = "-a" in args.split()
    target = next((a for a in arg_split(args, posix=True) if not a.startswith("-")), ".")
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


@line_magic("env", "set_env", doc="show env vars, or %env NAME · %env NAME=value")
def m_env(shell: Shell, args: str):
    a = args.strip()
    if "=" in a or (shell.current_magic == "set_env" and " " in a):
        k, v = a.split("=", 1) if "=" in a else a.split(None, 1)
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


@line_magic("pip", doc="run pip for this interpreter")
def m_pip(shell: Shell, args: str):
    run_command(shell, [sys.executable, "-m", "pip", *arg_split(args, posix=True)])
    if args.split()[:1] in (["install"], ["uninstall"]):
        import importlib

        importlib.invalidate_caches()
        shell.print(Text("restart ember if an already-imported package changed", style="ember.faint"))


# ── aliases ────────────────────────────────────────────────────────────────

DEFAULT_ALIASES = {
    "cat": "cat", "cp": "cp", "mv": "mv", "rm": "rm", "mkdir": "mkdir", "rmdir": "rmdir",
    "ll": "ls -lF" if sys.platform != "darwin" else "ls -lFG", "lf": "ls -F", "lx": "ls -F -l -X",
}


def define_alias(shell: Shell, name: str, command: str) -> None:
    if not name.isidentifier():
        raise MagicError(f"{name!r} is not a valid alias name")
    existing = LINE_MAGICS.get(name)
    if existing is not None and existing.category != "aliases":
        raise MagicError(f"%{name} is a magic; pick another alias name")
    n_args = command.count("%s")
    if n_args and "%l" in command:
        raise MagicError("an alias can't use both %s and %l")

    def run(sh: Shell, line: str, _cmd: str = command, _n: int = n_args):
        parts = arg_split(line, posix=False)
        if "%l" in _cmd:
            full = _cmd.replace("%l", line)
        elif _n:
            if len(parts) < _n:
                raise MagicError(f"alias {name} needs {_n} argument{'s' if _n != 1 else ''}")
            full = _cmd % tuple(parts[:_n])
            if parts[_n:]:
                full += " " + " ".join(parts[_n:])
        else:
            full = f"{_cmd} {line}".strip()
        run_command(sh, full)

    LINE_MAGICS[name] = MagicSpec(name, run, f"alias → {command}", "line", "aliases", True, "")
    shell.aliases[name] = command


@line_magic("alias", doc="define a shell alias: %alias name command (%s = positional arg, %l = whole line)")
def m_alias(shell: Shell, args: str):
    parts = args.strip().split(None, 1)
    if not parts:
        if not shell.aliases:
            shell.print(Text("no aliases", style="ember.faint"))
            return
        table = Table(box=box.SIMPLE_HEAD, border_style="ember.border", header_style="ember.accent.bold", show_edge=False, pad_edge=False)
        table.add_column("alias", style="ember.fg.bold")
        table.add_column("command", style="ember.muted")
        for name, command in sorted(shell.aliases.items()):
            table.add_row(name, command)
        shell.print(table)
        return
    if len(parts) == 1:
        raise MagicError("usage: %alias name command")
    define_alias(shell, parts[0], parts[1])


@line_magic("unalias", doc="remove an alias")
def m_unalias(shell: Shell, args: str):
    name = args.strip()
    if name not in shell.aliases:
        raise MagicError(f"no alias named {name!r}")
    del shell.aliases[name]
    LINE_MAGICS.pop(name, None)


@cell_magic("writefile", doc="write the cell body to a file (-a to append)")
def c_writefile(shell: Shell, args: str, body: str):
    opts, rest = parse_args(args, "a", "append")
    targets = arg_split(rest, posix=True)
    if not targets:
        raise MagicError("usage: %%writefile [-a] path")
    path = Path(targets[0]).expanduser()
    append = bool(opts.get("a") or opts.get("append"))
    existed = path.exists()
    with path.open("a" if append else "w") as f:
        f.write(body)
    verb = "appended to" if append else ("overwrote" if existed else "wrote")
    shell.print(Text(f"{verb} {short_path(path.resolve())}", style="ember.muted"))


# ── %%script ───────────────────────────────────────────────────────────────


class BackgroundScript:
    def __init__(self, shell: Shell, argv: list[str], body: str, out: str | None, err: str | None):
        self.argv = argv
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=_feed, args=(self.proc.stdin, body), daemon=True).start()
        self._threads = [
            threading.Thread(target=self._pump, args=(shell, self.proc.stdout, out, "stdout"), daemon=True),
            threading.Thread(target=self._pump, args=(shell, self.proc.stderr, err, "stderr"), daemon=True),
        ]
        for t in self._threads:
            t.start()

    @staticmethod
    def _pump(shell: Shell, pipe: Any, var: str | None, stream: str) -> None:
        chunks = []
        for raw in iter(pipe.readline, b""):
            line = raw.decode(errors="replace")
            if var:
                chunks.append(line)
            else:
                # Looked up per line: above the prompt this is prompt_toolkit's patched stdout.
                getattr(sys, stream).write(line)
        if var:
            shell.ns[var] = "".join(chunks)


def _script(shell: Shell, command: str, args: str, body: str) -> Any:
    opts, rest = parse_args(args, "", "bg", "out=", "err=", "proc=", "no-raise-error")
    argv = arg_split(f"{command} {rest}".strip(), posix=True)
    if not argv:
        raise MagicError("usage: %%script [--bg] [--out var] [--err var] command")
    if opts.get("bg"):
        job = BackgroundScript(shell, argv, body, opts.get("out"), opts.get("err"))
        shell.bg_processes.append(job.proc)
        if proc_var := opts.get("proc"):
            shell.ns[proc_var] = job.proc
        shell.print(Text(f"started {argv[0]} in the background (pid {job.proc.pid})", style="ember.muted"))
        return None
    if opts.get("out") or opts.get("err"):
        result = subprocess.run(argv, input=body.encode(), capture_output=True)
        if opts.get("out"):
            shell.ns[opts["out"]] = result.stdout.decode(errors="replace")
        else:
            sys.stdout.write(result.stdout.decode(errors="replace"))
        if opts.get("err"):
            shell.ns[opts["err"]] = result.stderr.decode(errors="replace")
        else:
            sys.stderr.write(result.stderr.decode(errors="replace"))
        code = result.returncode
    else:
        try:
            code = run_command(shell, argv, stdin=body)
        except FileNotFoundError:
            raise MagicError(f"command not found: {argv[0]}") from None
    if code and not opts.get("no-raise-error"):
        raise MagicError(f"{argv[0]} exited with status {code}")
    return None


@cell_magic("script", doc="run the cell with any program: %%script [--bg] [--out var] [--err var] command")
def c_script(shell: Shell, args: str, body: str):
    return _script(shell, "", args, body)


def _script_alias(program: str):
    def run(shell: Shell, args: str, body: str):
        return _script(shell, program, args, body)

    return run


for _name, _program in {"bash": "bash", "sh": "sh", "zsh": "zsh", "python": sys.executable, "python3": sys.executable,
                        "pypy": "pypy", "perl": "perl", "ruby": "ruby", "node": "node"}.items():
    cell_magic(_name, doc=f"run the cell with {_name}")(_script_alias(_program))


@line_magic("killbgscripts", doc="terminate all background %%script processes")
def m_killbgscripts(shell: Shell, args: str):
    alive = [p for p in shell.bg_processes if p.poll() is None]
    for proc in alive:
        proc.terminate()
    shell.bg_processes.clear()
    shell.print(Text(f"terminated {len(alive)} background process{'es' if len(alive) != 1 else ''}", style="ember.muted"))

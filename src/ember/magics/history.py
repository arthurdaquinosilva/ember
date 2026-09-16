"""History & session magics: history, recall, rerun, macro, store, log*, save, load, edit."""

from __future__ import annotations

import ast
import datetime as dt
import io
import os
import pickle
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from rich import box
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ember.display import short_path
from ember.history import Entry
from ember.magics import MagicError, line_magic, parse_args
from ember.utils import arg_split, plural

if TYPE_CHECKING:
    from ember.shell import Shell


# ── helpers ────────────────────────────────────────────────────────────────


def _entries(shell: Shell, spec: str, raw: bool = True, output: bool = False) -> list[Entry]:
    try:
        return shell.history.get_range_by_str(spec, raw=raw, output=output)
    except ValueError as e:
        raise MagicError(str(e)) from None


def _current_session(shell: Shell, raw: bool = True, output: bool = False, exclude_current: bool = True) -> list[Entry]:
    entries = shell.history.get_range(shell.history.session, 1, None, raw, output)
    if exclude_current and entries and entries[-1].line == shell.count:
        entries = entries[:-1]
    return entries


def _label(shell: Shell, entry: Entry) -> str:
    return str(entry.line) if entry.session == shell.history.session else f"{entry.session}/{entry.line}"


def _is_self(source: str, *names: str) -> bool:
    stripped = source.lstrip()
    return any(re.match(rf"%{n}\b", stripped) for n in names)


# ── %history ───────────────────────────────────────────────────────────────


@line_magic("history", "hist", doc="show history: ranges like 4-6 ~1/, -g pattern, -l N, -o, -p, -n, -u, -f file",
            usage="""%history [options] [ranges…]
  ranges   4 · 4-6 · 4:6 (end exclusive) · ~1/ (whole previous session) · ~2/3-5
  -g [pat] search every session (glob, e.g. -g "import*")
  -l [N]   last N lines across sessions (default 10)
  -n       show line numbers   -o  include outputs   -p  add >>> prompts
  -t       show translated (python) source instead of raw input
  -u       unique lines only (with -g)
  -f file  write to a file instead of the screen""")
def m_history(shell: Shell, args: str):
    opts, rest = _history_args(args)
    raw = not opts.get("t")
    output = bool(opts.get("o"))
    if "g" in opts:
        pattern = opts["g"] if isinstance(opts["g"], str) else "*"
        entries = [e for e in shell.history.search(pattern, raw=raw, output=output, unique=bool(opts.get("u")))
                   if not _is_self(e.source, "history", "hist")]
    elif "l" in opts:
        entries = shell.history.get_tail(int(opts["l"]) if isinstance(opts["l"], str) else 10, raw=raw, output=output)
    elif not rest:
        entries = _current_session(shell, raw, output)
    else:
        entries = _entries(shell, rest, raw, output)

    if target := opts.get("f"):
        with open(Path(target).expanduser(), "w") as f:
            _write_plain(shell, entries, f, bool(opts.get("n")), bool(opts.get("p")), output)
        shell.print(Text(f"wrote {plural(len(entries), 'entry')} → {target}", style="ember.muted"))
        return
    if not entries:
        shell.print(Text("no history", style="ember.faint"))
        return
    if opts.get("p"):
        buf = io.StringIO()
        _write_plain(shell, entries, buf, bool(opts.get("n")), True, output)
        shell.print(Syntax(buf.getvalue().rstrip(), "pycon", theme=shell.theme.syntax_theme, background_color="default"))
        return
    grid = Table.grid(padding=(0, 1))
    grid.add_column(justify="right", style="ember.faint", no_wrap=True)
    grid.add_column(ratio=1)
    for entry in entries:
        grid.add_row(_label(shell, entry), Syntax(entry.source, "python", theme=shell.theme.syntax_theme, background_color="default", word_wrap=True))
        if output and entry.output:
            grid.add_row("", Text.assemble(("→ ", "ember.faint"), (entry.output, "ember.muted")))
    shell.print(grid)


def _history_args(args: str) -> tuple[dict[str, Any], str]:
    """Options may appear anywhere; -g and -l take optional values, -f a required one."""
    opts: dict[str, Any] = {}
    ranges: list[str] = []
    tokens = arg_split(args, posix=True)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if tok in ("-g", "-l", "-f"):
            key = tok[1]
            takes = nxt is not None and not nxt.startswith("-") and (key != "l" or nxt.isdigit())
            if key == "f" and not takes:
                raise MagicError("-f needs a file name")
            opts[key] = nxt if takes else True
            i += 2 if takes else 1
        elif tok.startswith("-") and len(tok) > 1 and set(tok[1:]) <= set("noptru"):
            opts.update(dict.fromkeys(tok[1:], True))
            i += 1
        else:
            ranges.append(tok)
            i += 1
    return opts, " ".join(ranges)


def _write_plain(shell: Shell, entries: list[Entry], f: Any, numbers: bool, prompts: bool, output: bool) -> None:
    for entry in entries:
        lines = entry.source.split("\n")
        if prompts:
            lines = [(">>> " if i == 0 else "... ") + ln for i, ln in enumerate(lines)]
            if len(entry.source.split("\n")) > 1:
                lines.append("...")
        if numbers:
            lines[0] = f"{_label(shell, entry)}: {lines[0]}"
        f.write("\n".join(lines) + "\n")
        if output and entry.output:
            f.write(("" if prompts else "#[Out]# ") + entry.output + "\n")


# ── recall / rerun / macro ─────────────────────────────────────────────────


def _sources(shell: Shell, rest: str, raw: bool = True) -> list[str]:
    if rest.strip():
        return [e.source for e in _entries(shell, rest, raw)]
    entries = _current_session(shell, raw)
    return [entries[-1].source] if entries else []


@line_magic("recall", "rep", doc="put previous input (or a range) into the prompt for editing")
def m_recall(shell: Shell, args: str):
    rest = args.strip()
    if rest and not re.match(r"^[~\d]", rest):
        value = shell.ns.get(rest, None)
        if value is None:
            raise MagicError(f"{rest} is neither a history range nor a variable")
        shell.next_input = str(value)
        return
    sources = [s for s in _sources(shell, rest) if not _is_self(s, "recall", "rep")]
    if not sources:
        raise MagicError("nothing to recall")
    shell.next_input = "\n".join(sources)


@line_magic("rerun", doc="run previous input again: %rerun · %rerun 3-5 · -l N last N · -g pattern")
def m_rerun(shell: Shell, args: str):
    opts, rest = parse_args(args, "l:g:")
    if "l" in opts:
        entries = _current_session(shell)[-int(opts["l"]):]
        sources = [e.source for e in entries]
    elif "g" in opts:
        found = [e for e in shell.history.search(str(opts["g"])) if not _is_self(e.source, "rerun")]
        sources = [found[-1].source] if found else []
    else:
        sources = _sources(shell, rest)
    sources = [s for s in sources if not _is_self(s, "rerun")]
    if not sources:
        raise MagicError("nothing to rerun")
    shell.print(Text(f"↻ rerunning {plural(len(sources), 'cell')}", style="ember.faint"))
    for source in sources:
        shell.execute(shell.transform(source), shell.current_filename, on_value=shell.print_value)


class Macro:
    """A named block of input: typing its name as a cell runs it again."""

    def __init__(self, code: str):
        self.value = code.rstrip() + "\n"

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Macro({self.value!r})"

    def __add__(self, other: Any) -> Macro:
        if isinstance(other, Macro):
            return Macro(self.value + other.value)
        if isinstance(other, str):
            return Macro(self.value + other)
        return NotImplemented

    def __rich__(self) -> Any:
        from ember.shell import Shell

        theme = Shell.active.theme.syntax_theme if Shell.active else "ansi_dark"
        return Syntax(self.value.rstrip(), "python", theme=theme, background_color="default")


@line_magic("macro", doc="define a macro from history: %macro name 3-5 8 (typing the name runs it)")
def m_macro(shell: Shell, args: str):
    opts, rest = parse_args(args, "rq")
    parts = rest.split(None, 1)
    if len(parts) < 2:
        raise MagicError("usage: %macro [-r] [-q] name ranges|macros…")
    name, spec = parts
    if not name.isidentifier():
        raise MagicError(f"{name!r} is not a valid name")
    chunks = []
    for token in spec.split():
        existing = shell.ns.get(token)
        if isinstance(existing, Macro):
            chunks.append(existing.value.rstrip())
        else:
            chunks.extend(e.source for e in _entries(shell, token, raw=True))
    macro = Macro("\n".join(chunks))
    shell.ns[name] = macro
    if not opts.get("q"):
        shell.print(Text.assemble(("macro ", "ember.muted"), (name, "ember.accent.bold"), (" =", "ember.faint")))
        shell.print(macro)


# ── %store ─────────────────────────────────────────────────────────────────


def _store_dir(shell: Shell) -> Path:
    if shell.profile is None:
        raise MagicError("%store needs a profile directory")
    path = shell.profile.store_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def restore_store(shell: Shell, names: list[str] | None = None, quiet: bool = False) -> list[str]:
    restored = []
    directory = _store_dir(shell)
    for file in sorted(directory.iterdir()):
        if names and file.name not in names:
            continue
        try:
            with open(file, "rb") as f:
                shell.ns[file.name] = pickle.load(f)
            restored.append(file.name)
        except Exception as e:
            if not quiet:
                shell.print(Text(f"⚠ could not restore {file.name}: {e}", style="ember.warn"))
    return restored


@line_magic("store", doc="persist variables across sessions: %store x · -r restore · -d x delete · -z clear · x >file",
            usage="""%store              list stored variables
%store x y          store variables (pickled)
%store -r [x …]     restore all, or some, into the namespace
%store -d x         forget a stored variable
%store -z           forget everything
%store x >file.txt  write str(x) to a file (>> appends)""")
def m_store(shell: Shell, args: str):
    opts, rest = parse_args(args, "drz")
    directory = _store_dir(shell)
    if opts.get("z"):
        for file in directory.iterdir():
            file.unlink()
        shell.print(Text("store cleared", style="ember.muted"))
        return
    if opts.get("d"):
        for name in rest.split():
            try:
                (directory / name).unlink()
            except FileNotFoundError:
                raise MagicError(f"{name} is not stored") from None
        return
    if opts.get("r"):
        names = restore_store(shell, rest.split() or None)
        shell.print(Text(f"restored {', '.join(names) or 'nothing'}", style="ember.muted"))
        return
    if m := re.match(r"^\s*(\S+)\s*(>>?)\s*(\S+)\s*$", rest):
        name, mode, target = m.groups()
        value = shell.ns.get(name) if name in shell.ns else eval(name, shell.ns)
        with open(Path(target).expanduser(), "a" if mode == ">>" else "w") as f:
            f.write(str(value) if not isinstance(value, list) else "\n".join(map(str, value)) + "\n")
        shell.print(Text(f"{'appended' if mode == '>>' else 'wrote'} {name} → {target}", style="ember.muted"))
        return
    if not rest:
        files = sorted(directory.iterdir())
        if not files:
            shell.print(Text("nothing stored", style="ember.faint"))
            return
        table = Table(box=box.SIMPLE_HEAD, border_style="ember.border", header_style="ember.accent.bold", show_edge=False, pad_edge=False)
        table.add_column("name", style="ember.fg.bold")
        table.add_column("value", style="ember.muted", overflow="ellipsis", no_wrap=True, max_width=70)
        for file in files:
            try:
                with open(file, "rb") as f:
                    shown = repr(pickle.load(f))
            except Exception as e:
                shown = f"<unreadable: {e}>"
            table.add_row(file.name, shown.replace("\n", " "))
        shell.print(table)
        return
    for name in rest.split():
        if name not in shell.ns:
            raise MagicError(f"{name} is not defined")
        value = shell.ns[name]
        try:
            data = pickle.dumps(value)
        except Exception as e:
            raise MagicError(f"can't store {name}: {e}") from None
        (directory / name).write_bytes(data)
        shell.print(Text.assemble(("stored ", "ember.muted"), (name, "ember.accent.bold"), (f" ({type(value).__name__})", "ember.faint")))


# ── logging ────────────────────────────────────────────────────────────────


class SessionLogger:
    def __init__(self, path: Path, mode: str, output: bool, raw: bool, timestamp: bool):
        self.path = path
        self.mode = mode
        self.output = output
        self.raw = raw
        self.timestamp = timestamp
        self.active = True
        self.file: TextIO = open(path, "a" if mode in ("append", "global") else "w")
        self.file.write(f"# ember log — session started {dt.datetime.now():%Y-%m-%d %H:%M:%S}\n")
        self.file.flush()

    def log_input(self, raw: str, translated: str) -> None:
        if not self.active:
            return
        if self.timestamp:
            self.file.write(f"# {dt.datetime.now():%a, %d %b %Y %H:%M:%S}\n")
        self.file.write((raw if self.raw else translated).rstrip() + "\n")
        self.file.flush()

    def log_output(self, value_repr: str) -> None:
        if self.active and self.output:
            self.file.write("\n".join("#[Out]# " + ln for ln in value_repr.splitlines()) + "\n")
            self.file.flush()

    def close(self) -> None:
        self.file.close()


@line_magic("logstart", doc="log this session's input to a file: %logstart [-o] [-r] [-t] [file [append|over|backup|rotate|global]]")
def m_logstart(shell: Shell, args: str):
    if shell.logger is not None:
        raise MagicError(f"already logging to {short_path(shell.logger.path)} — %logstop first")
    opts, rest = parse_args(args, "ortq")
    parts = rest.split()
    mode = parts[1] if len(parts) > 1 else "backup"
    if mode not in ("append", "backup", "global", "over", "rotate"):
        raise MagicError("mode must be append, backup, global, over or rotate")
    path = Path("~/ember_log.py" if mode == "global" else (parts[0] if parts else "ember_log.py")).expanduser()
    if path.exists() and mode == "backup":
        shutil.move(path, path.with_name(path.name + "~"))
    elif path.exists() and mode == "rotate":
        n = 1
        while path.with_name(f"{path.name}.{n:03d}~").exists():
            n += 1
        shutil.move(path, path.with_name(f"{path.name}.{n:03d}~"))
    shell.logger = SessionLogger(path, mode, bool(opts.get("o")), bool(opts.get("r")), bool(opts.get("t")))
    if not opts.get("q"):
        shell.print(Text.assemble(("logging → ", "ember.muted"), (short_path(path.resolve()), "repr.path"), (f"  ({mode})", "ember.faint")))


@line_magic("logstop", doc="stop logging and close the log file")
def m_logstop(shell: Shell, args: str):
    if shell.logger is None:
        raise MagicError("not logging")
    shell.logger.close()
    shell.logger = None


@line_magic("logon", "logoff", doc="resume / pause logging")
def m_logon(shell: Shell, args: str):
    if shell.logger is None:
        raise MagicError("not logging — use %logstart")
    shell.logger.active = shell.current_magic == "logon"


@line_magic("logstate", doc="show logging status")
def m_logstate(shell: Shell, args: str):
    lg = shell.logger
    if lg is None:
        shell.print(Text("not logging", style="ember.muted"))
        return
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="ember.faint")
    grid.add_column(style="ember.fg")
    for k, v in (("file", short_path(lg.path.resolve())), ("mode", lg.mode), ("active", lg.active),
                 ("output", lg.output), ("raw", lg.raw), ("timestamps", lg.timestamp)):
        grid.add_row(k, str(v))
    shell.print(grid)


# ── save / load / edit ─────────────────────────────────────────────────────


@line_magic("save", doc="save input to a file: %save file [ranges] (-a append, -r raw)")
def m_save(shell: Shell, args: str):
    opts, rest = parse_args(args, "arf")
    parts = rest.split(None, 1)
    if not parts:
        raise MagicError("usage: %save [-a] [-r] file [ranges]")
    target = Path(parts[0]).expanduser()
    if target.suffix == "":
        target = target.with_suffix(".py")
    raw = bool(opts.get("r"))
    if len(parts) > 1:
        cells = []
        for token in parts[1].split():
            existing = shell.ns.get(token)
            cells.extend([existing.value.rstrip()] if isinstance(existing, Macro) else [e.source for e in _entries(shell, token, raw)])
    else:
        cells = [e.source for e in _current_session(shell, raw) if not _is_self(e.source, "save")]
    text = "\n\n".join(c.rstrip() for c in cells) + "\n"
    with open(target, "a" if opts.get("a") else "w") as f:
        f.write(text)
    shell.print(Text(f"{'appended' if opts.get('a') else 'saved'} {plural(len(cells), 'cell')} → {short_path(target)}", style="ember.muted"))


def _extract_symbols(source: str, symbols: list[str]) -> str:
    tree = ast.parse(source)
    lines = source.split("\n")
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in symbols:
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1
            found.append("\n".join(lines[start:node.end_lineno]))
    missing = set(symbols) - {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    if missing:
        raise MagicError(f"not found: {', '.join(sorted(missing))}")
    return "\n\n".join(found)


def _slice_lines(source: str, spec: str) -> str:
    lines = source.split("\n")
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-") if "-" in part else part.partition(":")
        start = int(a) if a else 1
        end = int(b) if b else (start if not part.endswith(("-", ":")) else len(lines))
        out.extend(lines[start - 1 : end])
    return "\n".join(out)


@line_magic("load", doc="load code into the prompt: file, url, history range or macro (-r lines, -s symbols)")
def m_load(shell: Shell, args: str):
    opts, target = parse_args(args, "yr:s:n:")
    target = target.strip()
    if not target:
        raise MagicError("usage: %load [-r lines] [-s symbols] source")
    if isinstance(shell.ns.get(target), Macro):
        source = shell.ns[target].value
    elif re.fullmatch(r"[~\d/:\- ]+", target) and not os.path.exists(target):
        source = "\n".join(e.source for e in _entries(shell, target))
    elif target.startswith(("http://", "https://")):
        from urllib.request import urlopen

        with urlopen(target, timeout=10) as resp:  # noqa: S310 - user-requested URL
            source = resp.read().decode()
    else:
        path = Path(target).expanduser()
        if not path.exists():
            raise MagicError(f"no such file: {target}")
        source = path.read_text()
    if symbols := opts.get("s"):
        source = _extract_symbols(source, [s.strip() for s in str(symbols).split(",")])
    if lines := opts.get("r"):
        source = _slice_lines(source, str(lines))
    shell.next_input = source.rstrip()
    shell.print(Text("loaded into prompt ↓", style="ember.muted"))


@line_magic("edit", "ed", doc="edit a file, history range, macro or object's source in $EDITOR, then load it")
def m_edit(shell: Shell, args: str):
    import inspect

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    opts, target = parse_args(args, "prxn:")
    target = target.strip()
    shell.pause_output()

    def open_editor(path: str, line: int | None = None) -> None:
        cmd = shlex.split(editor)
        if line and os.path.basename(cmd[0]) in ("vi", "vim", "nvim", "nano", "emacs", "micro", "hx", "kak"):
            cmd.append(f"+{line}")
        subprocess.call([*cmd, path])

    obj = shell.ns.get(target) if target.isidentifier() else None
    if target and obj is not None and not isinstance(obj, (Macro, str)):
        try:
            path = inspect.getsourcefile(obj)
            _, line = inspect.getsourcelines(obj)
        except (TypeError, OSError):
            raise MagicError(f"can't find source for {target}") from None
        if path and os.path.exists(path):
            open_editor(path, line)
            shell.next_input = f"%run -i {shlex.quote(path)}" if not opts.get("x") else ""
            return
    if target and not isinstance(obj, Macro) and not re.fullmatch(r"[~\d/:\- ]+", target):
        open_editor(target)
        if not opts.get("x"):
            shell.next_input = f"%run {shlex.quote(target)}"
        return
    if isinstance(obj, Macro):
        initial = obj.value
    elif target:
        initial = "\n".join(e.source for e in _entries(shell, target))
    else:
        previous = [e for e in _current_session(shell) if not _is_self(e.source, "edit", "ed")]
        initial = previous[-1].source if previous else ""
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
        f.write(initial)
        name = f.name
    try:
        open_editor(name)
        edited = Path(name).read_text().rstrip()
    finally:
        os.unlink(name)
    if isinstance(obj, Macro):
        shell.ns[target] = Macro(edited)
    elif not opts.get("x"):
        shell.next_input = edited

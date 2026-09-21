"""General magics: help, settings, errors & debugging, extensions, autoreload."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from dataclasses import fields
from typing import TYPE_CHECKING

from rich import box
from rich.table import Table
from rich.text import Text

from ember.config import AUTOAWAIT, EDITING_MODES, XMODES, Settings, resolve_setting_name
from ember.display import short_path
from ember.magics import CELL_MAGICS, LINE_MAGICS, MagicError, line_magic, magic_docs
from ember.theme import PALETTES

if TYPE_CHECKING:
    from ember.shell import Shell


def _state(on: bool) -> tuple[str, str]:
    return ("on", "ember.ok") if on else ("off", "ember.muted")


def _flag(value: str, current: bool) -> bool:
    value = value.strip().lower()
    if not value:
        return not current
    if value in ("on", "1", "true", "yes"):
        return True
    if value in ("off", "0", "false", "no"):
        return False
    raise MagicError(f"expected on/off, got {value!r}")


@line_magic("help", doc="show keys, syntax and magics · %help name for one magic")
def m_help(shell: Shell, args: str):
    from ember.display import help_panel, magic_help

    name = args.strip().lstrip("%")
    if not name:
        shell.print(help_panel(magic_docs()))
        return
    spec = LINE_MAGICS.get(name) or CELL_MAGICS.get(name)
    if spec is None:
        raise MagicError(f"no magic named %{name}")
    shell.print(magic_help(spec))


@line_magic("lsmagic", doc="list all magics")
def m_lsmagic(shell: Shell, args: str):
    from rich.columns import Columns

    for title, table, prefix in (("line", LINE_MAGICS, "%"), ("cell", CELL_MAGICS, "%%")):
        shell.print(Text(f"{title} magics", style="ember.fg.bold"))
        shell.print(Columns([Text(prefix + n, style="ember.accent") for n in sorted(table)], padding=(0, 2)))


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
    shell.set_setting("theme", name)
    shell.print(Text.assemble(("theme → ", "ember.muted"), (name, "ember.accent.bold")))


@line_magic("config", doc="show or change settings: %config · %config name · %config name=value", expand=False)
def m_config(shell: Shell, args: str):
    a = args.strip()
    if not a:
        table = Table(box=box.SIMPLE_HEAD, border_style="ember.border", header_style="ember.accent.bold", show_edge=False, pad_edge=False)
        table.add_column("setting", style="ember.fg.bold", no_wrap=True)
        table.add_column("value", style="ember.string")
        for f in fields(Settings):
            table.add_row(f.name, repr(getattr(shell.settings, f.name)))
        shell.print(table)
        if shell.profile:
            shell.print(Text(f"saved defaults live in {short_path(shell.profile.config_file)}", style="ember.faint"))
        return
    key, eq, value = a.partition("=")
    try:
        name = resolve_setting_name(key)
    except KeyError:
        raise MagicError(f"unknown setting {key.strip()!r} — see %config") from None
    if not eq:
        return getattr(shell.settings, name)
    try:
        shell.set_setting(name, value.strip())
    except ValueError as e:
        raise MagicError(str(e)) from None
    shell.print(Text.assemble((name, "ember.fg.bold"), (" = ", "ember.faint"), (repr(getattr(shell.settings, name)), "ember.string")))


@line_magic("xmode", doc="traceback style: minimal · plain · context · verbose (no arg cycles)")
def m_xmode(shell: Shell, args: str):
    mode = args.strip().lower()
    if not mode:
        order = ("plain", "context", "verbose", "minimal")
        mode = order[(order.index(shell.settings.xmode) + 1) % len(order)]
    if mode not in XMODES:
        raise MagicError(f"xmode must be one of: {', '.join(XMODES)}")
    shell.set_setting("xmode", mode)
    shell.print(Text.assemble(("exception mode → ", "ember.muted"), (mode, "ember.accent.bold")))


@line_magic("pdb", doc="toggle automatic post-mortem debugging on errors")
def m_pdb(shell: Shell, args: str):
    shell.set_setting("pdb", _flag(args, shell.settings.pdb))
    shell.print(Text.assemble(("automatic pdb ", "ember.muted"), _state(shell.settings.pdb)))


@line_magic("tb", doc="print the last traceback again")
def m_tb(shell: Shell, args: str):
    if shell.last_exception is None:
        raise MagicError("no traceback available")
    mode = args.strip().lower()
    if mode and mode not in XMODES:
        raise MagicError(f"mode must be one of: {', '.join(XMODES)}")
    shell.show_exception(shell.last_exception, mode or None)


@line_magic("debug", doc="post-mortem debugger on the last error, or %debug statement", expand=False)
def m_debug(shell: Shell, args: str):
    stmt = args.strip()
    shell.pause_output()
    if stmt:
        # Give the statement a source "file" so `l` / `ll` can show it, instead of pdb's `<string>`.
        import linecache

        filename = f"<debug-{shell.count}>"
        linecache.cache[filename] = (len(stmt), None, [stmt + "\n"], filename)
        code = compile(shell.transform(stmt), filename, "exec")
        shell.print(Text("stopped before the statement runs — s steps into the call, n runs it, c continues", style="ember.faint"))
        shell.debugger().run(code, shell.ns)
        return
    if shell.last_exception is None:
        raise MagicError("no exception to debug")
    shell.post_mortem(shell.last_exception.__traceback__)


@line_magic("autoawait", doc="top-level await runner: asyncio · trio · curio · off")
def m_autoawait(shell: Shell, args: str):
    value = args.strip().lower()
    if not value:
        shell.print(Text.assemble(("autoawait ", "ember.muted"), (shell.settings.autoawait, "ember.accent.bold")))
        return
    value = {"true": "asyncio", "on": "asyncio", "false": "off", "0": "off", "1": "asyncio"}.get(value, value)
    if value not in AUTOAWAIT:
        raise MagicError(f"runner must be one of: {', '.join(AUTOAWAIT)}")
    if value in ("trio", "curio"):
        try:
            importlib.import_module(value)
        except ImportError:
            raise MagicError(f"{value} is not installed — %pip install {value}") from None
    shell.set_setting("autoawait", value)
    shell.print(Text.assemble(("autoawait → ", "ember.muted"), (value, "ember.accent.bold")))


@line_magic("automagic", doc="toggle calling magics without the % prefix")
def m_automagic(shell: Shell, args: str):
    shell.set_setting("automagic", _flag(args, shell.settings.automagic))
    shell.print(Text.assemble(("automagic ", "ember.muted"), _state(shell.settings.automagic)))


@line_magic("editmode", "vi", "emacs", doc="switch key bindings: %editmode vi|emacs (or just %vi / %emacs)")
def m_editmode(shell: Shell, args: str):
    mode = args.strip().lower() or shell.current_magic
    if mode not in EDITING_MODES:
        raise MagicError("editmode must be vi or emacs")
    shell.set_setting("editing_mode", mode)
    shell.print(Text.assemble(("editing mode → ", "ember.muted"), (mode, "ember.accent.bold"), ("  (this session)", "ember.faint")))
    if shell.profile is not None:
        shell.print(Text(f'to keep it, add  editing_mode = "{mode}"  to {short_path(shell.profile.config_file)}  or start with --vi',
                         style="ember.faint"))


@line_magic("doctest_mode", doc="toggle plain >>> prompts and output, for copying into doctests")
def m_doctest_mode(shell: Shell, args: str):
    shell.doctest_mode = _flag(args, shell.doctest_mode)
    shell.print(Text.assemble(("doctest mode ", "ember.muted"), _state(shell.doctest_mode)))


@line_magic("profile", doc="show the active profile and its directories")
def m_profile(shell: Shell, args: str):
    p = shell.profile
    if p is None:
        shell.print(Text("no profile (running without config)", style="ember.muted"))
        return
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="ember.faint")
    grid.add_column(style="repr.path")
    grid.add_row("profile", Text(p.name, style="ember.accent.bold"))
    grid.add_row("config", short_path(p.config_file))
    grid.add_row("startup", short_path(p.startup_dir))
    grid.add_row("history", short_path(p.history_db))
    grid.add_row("store", short_path(p.store_dir))
    shell.print(grid)


# ── extensions ─────────────────────────────────────────────────────────────


@line_magic("load_ext", doc="load an extension module (IPython extensions work too)")
def m_load_ext(shell: Shell, args: str):
    name = args.strip()
    if not name:
        raise MagicError("usage: %load_ext module")
    try:
        result = shell.ipy.extension_manager.load_extension(name)
    except ModuleNotFoundError as e:
        raise MagicError(f"no module named {e.name!r}") from None
    if result == "already loaded":
        shell.print(Text(f"{name} is already loaded — use %reload_ext {name}", style="ember.muted"))
    elif result == "no load function":
        raise MagicError(f"{name} has no load_ember_extension or load_ipython_extension function")
    else:
        shell.print(Text.assemble(("loaded ", "ember.muted"), (name, "ember.accent.bold")))


@line_magic("unload_ext", doc="unload an extension")
def m_unload_ext(shell: Shell, args: str):
    name = args.strip()
    result = shell.ipy.extension_manager.unload_extension(name)
    if result:
        raise MagicError(f"{name}: {result}")
    shell.print(Text.assemble(("unloaded ", "ember.muted"), (name, "ember.fg")))


@line_magic("reload_ext", doc="reload an extension")
def m_reload_ext(shell: Shell, args: str):
    shell.ipy.extension_manager.reload_extension(args.strip())
    shell.print(Text.assemble(("reloaded ", "ember.muted"), (args.strip(), "ember.accent.bold")))


# ── autoreload ─────────────────────────────────────────────────────────────

_AUTORELOAD_MODES = {"0": 0, "off": 0, "1": 1, "explicit": 1, "2": 2, "all": 2, "3": 2, "complete": 2, "on": 2}


@line_magic("autoreload", doc="reload changed modules: 0 off · 1 %aimport-ed only · 2 all · now")
def m_autoreload(shell: Shell, args: str):
    a = args.strip().lower()
    if a in ("", "now"):
        reloaded, errors = shell.autoreload.check(force=True)
        _report_reload(shell, reloaded, errors, quiet_if_empty=False)
        return
    if a not in _AUTORELOAD_MODES:
        raise MagicError("usage: %autoreload [0|1|2|now]")
    shell.set_setting("autoreload", _AUTORELOAD_MODES[a])
    labels = {0: "off", 1: "only %aimport-ed modules", 2: "all modules"}
    shell.print(Text.assemble(("autoreload → ", "ember.muted"), (labels[shell.settings.autoreload], "ember.accent.bold")))


def _report_reload(shell: Shell, reloaded: list[str], errors: list[tuple[str, str]], quiet_if_empty: bool = True) -> None:
    if reloaded:
        shell.print(Text(f"↻ reloaded {', '.join(reloaded)}", style="ember.faint"))
    for name, err in errors:
        shell.print(Text(f"⚠ reloading {name} failed: {err}", style="ember.warn"))
    if not reloaded and not errors and not quiet_if_empty:
        shell.print(Text("nothing changed", style="ember.faint"))


@line_magic("aimport", doc="mark modules for autoreload 1 (%aimport -mod excludes)")
def m_aimport(shell: Shell, args: str):
    ar = shell.autoreload
    names = [n.strip() for n in args.replace(",", " ").split() if n.strip()]
    if not names:
        shell.print(Text.assemble(("modules to reload: ", "ember.muted"), (" ".join(sorted(ar.included)) or "—", "ember.fg")))
        shell.print(Text.assemble(("modules to skip: ", "ember.muted"), (" ".join(sorted(ar.excluded)) or "—", "ember.fg")))
        return
    for name in names:
        if name.startswith("-"):
            ar.excluded.add(name[1:])
            ar.included.discard(name[1:])
            continue
        ar.excluded.discard(name)
        ar.included.add(name)
        importlib.import_module(name)
        top = name.split(".")[0]
        shell.ns[top] = sys.modules[top]
        ar.snapshot()


# ── clipboard & exit ───────────────────────────────────────────────────────


@line_magic("copy", doc="copy the last result (or an expression) to the clipboard", expand=False)
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
    shell.exit_requested = True

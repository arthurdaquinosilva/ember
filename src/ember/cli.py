"""Command-line entry point."""

from __future__ import annotations

import argparse
import shlex
import sys

from ember import __version__
from ember.theme import PALETTES


def _import_legacy_history(shell) -> None:
    """ember < 0.2 kept a prompt_toolkit FileHistory; fold it into the SQLite database once."""
    if shell.profile is None or not shell.history.is_new:
        return
    legacy = shell.profile.data_dir / "history"
    if not legacy.is_file():
        return
    from prompt_toolkit.history import FileHistory

    try:
        lines = list(reversed(list(FileHistory(str(legacy)).load_history_strings())))
    except OSError:
        return
    if lines:
        shell.history.import_lines(lines, remark=f"imported from {legacy}")
        legacy.rename(legacy.with_name("history.imported"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ember", description="A modern interactive Python shell.")
    parser.add_argument("file", nargs="?", help="python file to run")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the file")
    parser.add_argument("-c", dest="command", help="run a command")
    parser.add_argument("-m", dest="module", help="run a library module as a script")
    parser.add_argument("-i", action="store_true", help="stay interactive after running a file, module or command")
    parser.add_argument("--profile", help="use a named profile (separate config, startup files and history)")
    parser.add_argument("--theme", choices=list(PALETTES), help="color theme")
    parser.add_argument("--vi", action="store_true", help="vi key bindings")
    parser.add_argument("--no-startup", action="store_true", help="skip startup files, exec_lines and extensions")
    parser.add_argument("--version", action="version", version=f"ember {__version__}")
    opts = parser.parse_args(argv)
    # Like `python`: code in the session sees an empty argv, not ember's own options.
    # (%run sets sys.argv for the scripts it runs.)
    sys.argv = ["-c"] if opts.command is not None else [""]

    from ember.config import load_profile, load_settings
    from ember.shell import Shell

    profile = load_profile(opts.profile)
    settings, warnings = load_settings(profile)
    if opts.theme:
        settings.theme = opts.theme
    if opts.vi:
        settings.editing_mode = "vi"
    if opts.no_startup:
        settings.exec_lines, settings.exec_files, settings.extensions = [], [], []

    shell = Shell(settings=settings, profile=profile)
    _import_legacy_history(shell)
    try:
        status = _run_batch(shell, opts, warnings)
    except SystemExit as e:
        status = e.code if isinstance(e.code, int) else 0
    if status is not None:
        shell.close()
        return status

    from ember.ui import Repl

    return Repl(shell).run()


def _run_batch(shell, opts: argparse.Namespace, warnings: list[str]) -> int | None:
    """Run startup and any -c/-m/file/stdin work. Returns an exit status, or None to go interactive."""
    shell.startup(warnings, run_files=not opts.no_startup)
    ran = False
    if opts.command is not None:
        shell.run_cell(opts.command)
        ran = True
    if opts.module:
        shell.run_cell(f"%run -m {shlex.join([opts.module, *([opts.file] if opts.file else []), *opts.args])}")
        ran = True
    elif opts.file:
        shell.run_cell(f"%run {shlex.join([opts.file, *opts.args])}")
        ran = True
    if ran and not opts.i:
        if shell.exit_status is not None:
            return shell.exit_status
        return 0 if shell.last_ok else 1
    if not sys.stdin.isatty():
        shell.run_cell(sys.stdin.read())
        return 0 if shell.last_ok else 1
    return None

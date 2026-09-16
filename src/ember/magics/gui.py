"""GUI event loop & plotting magics: %gui, %matplotlib."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from ember.inputhooks import GUIS
from ember.magics import MagicError, line_magic

if TYPE_CHECKING:
    from ember.shell import Shell


@line_magic("gui", doc="keep a GUI event loop running at the prompt: %gui qt|tk|osx|gtk3|gtk4|wx|asyncio (no arg disables)")
def m_gui(shell: Shell, args: str):
    name = args.strip() or None
    try:
        shell.enable_gui(name)
    except (ValueError, ImportError) as e:
        raise MagicError(str(e)) from None
    if name:
        shell.print(Text.assemble(("event loop → ", "ember.muted"), (name, "ember.accent.bold"), ("  (runs while the prompt waits)", "ember.faint")))
    else:
        shell.print(Text("event loop integration off", style="ember.muted"))


@line_magic("matplotlib", doc="interactive matplotlib windows that stay responsive: %matplotlib [qt|tk|osx|…] · -l list")
def m_matplotlib(shell: Shell, args: str):
    name = args.strip()
    if name in ("-l", "--list"):
        shell.print(Text("event loops: " + ", ".join(g for g in GUIS if g != "asyncio"), style="ember.fg"))
        shell.print(Text("backends: any matplotlib backend name, e.g. QtAgg, TkAgg, macosx, agg", style="ember.muted"))
        return
    if name in ("inline", "widget", "ipympl", "notebook", "nbagg"):
        raise MagicError(f"%matplotlib {name} needs a notebook — in a terminal use a GUI backend (qt, tk, osx)")
    try:
        gui, backend = shell.enable_matplotlib(name or None)
    except ImportError as e:
        raise MagicError(f"{e} — %pip install matplotlib") from None
    except (ValueError, RuntimeError) as e:
        raise MagicError(str(e)) from None
    shell.print(Text.assemble(("matplotlib → ", "ember.muted"), (backend, "ember.accent.bold"),
                              (f"  · event loop {gui}" if gui else "  · no GUI event loop needed", "ember.faint")))

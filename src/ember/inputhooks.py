"""Event-loop integration: keep GUI windows (and asyncio tasks) alive while the prompt waits."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from prompt_toolkit.eventloop.inputhook import InputHookContext

    from ember.shell import Shell

InputHook = Callable[["InputHookContext"], None]

# matplotlib backend → gui event loop
BACKEND_GUI = {
    "qtagg": "qt", "qt5agg": "qt", "qt6agg": "qt", "qtcairo": "qt", "qt5cairo": "qt",
    "tkagg": "tk", "tkcairo": "tk",
    "macosx": "osx",
    "gtk3agg": "gtk3", "gtk3cairo": "gtk3", "gtk4agg": "gtk4", "gtk4cairo": "gtk4",
    "wxagg": "wx", "wxcairo": "wx", "wx": "wx",
}
GUI_BACKEND = {"qt": "QtAgg", "qt5": "Qt5Agg", "qt6": "QtAgg", "tk": "TkAgg", "osx": "macosx", "macosx": "macosx",
               "gtk3": "GTK3Agg", "gtk4": "GTK4Agg", "wx": "WXAgg"}
GUI_ALIASES = {"qt5": "qt", "qt6": "qt", "pyqt5": "qt", "pyqt6": "qt", "pyside2": "qt", "pyside6": "qt",
               "macosx": "osx", "gtk": "gtk3"}
GUIS = ("asyncio", "qt", "tk", "osx", "gtk3", "gtk4", "wx")


def _poll(ctx: InputHookContext, step: Callable[[], None], interval: float = 0.01) -> None:
    while not ctx.input_is_ready():
        step()
        time.sleep(interval)


def _matplotlib_step() -> None:
    mpl = sys.modules.get("matplotlib._pylab_helpers")
    if mpl is None:
        return
    for manager in mpl.Gcf.get_all_fig_managers():
        canvas = manager.canvas
        try:
            if canvas.figure.stale:
                canvas.draw_idle()
            canvas.flush_events()
        except Exception:
            pass


def asyncio_hook(shell: Shell) -> InputHook:
    def hook(ctx: InputHookContext) -> None:
        loop = shell.loop
        ready = loop.create_future()
        loop.add_reader(ctx.fileno(), lambda: ready.done() or ready.set_result(None))
        try:
            loop.run_until_complete(ready)
        finally:
            loop.remove_reader(ctx.fileno())

    return hook


def qt_hook(shell: Shell) -> InputHook:
    for name in ("PyQt6", "PySide6", "PyQt5", "PySide2"):
        try:
            QtCore = __import__(f"{name}.QtCore", fromlist=["QtCore"])
            QtWidgets = __import__(f"{name}.QtWidgets", fromlist=["QtWidgets"])
            break
        except ImportError:
            continue
    else:
        raise ImportError("no Qt binding found (install PyQt6 or PySide6)")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def hook(ctx: InputHookContext) -> None:
        loop = QtCore.QEventLoop()
        read = getattr(QtCore.QSocketNotifier, "Type", QtCore.QSocketNotifier).Read
        notifier = QtCore.QSocketNotifier(ctx.fileno(), read)
        notifier.activated.connect(loop.exit)
        try:
            (loop.exec if hasattr(loop, "exec") else loop.exec_)()
        finally:
            notifier.setEnabled(False)
        _ = app

    return hook


def tk_hook(shell: Shell) -> InputHook:
    import tkinter

    def hook(ctx: InputHookContext) -> None:
        root = tkinter._default_root  # type: ignore[attr-defined]
        if root is None:
            _poll(ctx, _matplotlib_step, 0.02)
            return
        done = []

        def on_input(*_):
            done.append(True)
            root.quit()

        try:
            root.createfilehandler(ctx.fileno(), tkinter.READABLE, on_input)
            root.mainloop()
            root.deletefilehandler(ctx.fileno())
        except (AttributeError, tkinter.TclError):
            _poll(ctx, root.update, 0.02)

    return hook


def osx_hook(shell: Shell) -> InputHook:
    def hook(ctx: InputHookContext) -> None:
        _poll(ctx, _matplotlib_step, 0.02)

    return hook


def gtk3_hook(shell: Shell) -> InputHook:
    from gi.repository import Gtk  # type: ignore[import-not-found]

    def step() -> None:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

    return lambda ctx: _poll(ctx, step)


def gtk4_hook(shell: Shell) -> InputHook:
    from gi.repository import GLib  # type: ignore[import-not-found]

    context = GLib.MainContext.default()

    def step() -> None:
        while context.pending():
            context.iteration(False)

    return lambda ctx: _poll(ctx, step)


def wx_hook(shell: Shell) -> InputHook:
    import wx  # type: ignore[import-not-found]

    app = wx.GetApp() or wx.App(False)

    def step() -> None:
        loop = wx.EventLoopBase.GetActive() or wx.GUIEventLoop()
        while loop.Pending():
            loop.Dispatch()
        app.ProcessIdle()

    return lambda ctx: _poll(ctx, step)


FACTORIES: dict[str, Callable[["Shell"], InputHook]] = {
    "asyncio": asyncio_hook,
    "qt": qt_hook,
    "tk": tk_hook,
    "osx": osx_hook,
    "gtk3": gtk3_hook,
    "gtk4": gtk4_hook,
    "wx": wx_hook,
}


def normalize_gui(name: str | None) -> str | None:
    if not name:
        return None
    name = name.lower()
    return GUI_ALIASES.get(name, name)


def make_hook(name: str, shell: Shell) -> InputHook:
    gui = normalize_gui(name)
    if gui not in FACTORIES:
        raise ValueError(f"unknown gui {name!r} — try: {', '.join(GUIS)}")
    return FACTORIES[gui](shell)


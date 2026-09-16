"""Stream proxies that draw a left rail beside cell output, plus a live 'running' spinner."""

from __future__ import annotations

import io
import re
import threading
import time
from typing import TextIO

_SPLIT = re.compile(r"(\r\n|\n|\r)")
FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def format_duration(seconds: float) -> str:
    if seconds < 1e-6:
        return f"{seconds * 1e9:.0f}ns"
    if seconds < 1e-3:
        return f"{seconds * 1e6:.1f}µs"
    if seconds < 1:
        return f"{seconds * 1e3:.1f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {s:.0f}s"


class RailState:
    """Shared between stdout and stderr so both agree on where the cursor is."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self.at_line_start = True
        self.wrote = False
        self.lock = threading.RLock()


class Spinner:
    def __init__(self, real: TextIO, state: RailState, render, delay: float = 0.25):
        self.real = real
        self.state = state
        self.render = render  # (frame, elapsed) -> ansi str
        self.delay = delay
        self.shown = False
        self.enabled = real.isatty()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started = time.perf_counter()

    def start(self) -> None:
        if not self.enabled:
            return
        self.started = time.perf_counter()
        self._thread = threading.Thread(target=self._run, name="ember-spinner", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        i = 0
        while not self._stop.wait(0.08):
            elapsed = time.perf_counter() - self.started
            if elapsed < self.delay:
                continue
            with self.state.lock:
                if self._stop.is_set() or not self.state.at_line_start:
                    continue
                self.real.write("\r\x1b[2K" + self.render(FRAMES[i % len(FRAMES)], elapsed))
                self.real.flush()
                self.shown = True
            i += 1

    def clear(self) -> None:
        """Erase the spinner line. Caller holds state.lock."""
        if self.shown:
            self.real.write("\r\x1b[2K")
            self.shown = False

    def stop(self) -> None:
        self._stop.set()
        with self.state.lock:
            self.clear()
            self.real.flush()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.5)


class RailWriter(io.TextIOBase):
    def __init__(self, real: TextIO, state: RailState, spinner: Spinner | None = None):
        self.real = real
        self.state = state
        self.spinner = spinner

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            raise TypeError(f"write() argument must be str, not {type(s).__name__}")
        if not s:
            return 0
        st = self.state
        with st.lock:
            if self.spinner:
                self.spinner.clear()
            out: list[str] = []
            if not st.wrote and st.at_line_start:
                out.append(st.prefix.rstrip() + "\n")  # breathing room below the echoed code
            for piece in _SPLIT.split(s):
                if not piece:
                    continue
                if piece in ("\n", "\r\n"):
                    if st.at_line_start:
                        out.append(st.prefix.rstrip() if st.prefix else "")
                    out.append("\n")
                    st.at_line_start = True
                elif piece == "\r":
                    out.append("\r")
                    st.at_line_start = True
                else:
                    if st.at_line_start:
                        out.append(st.prefix)
                        st.at_line_start = False
                    out.append(piece)
            self.real.write("".join(out))
            self.real.flush()
            st.wrote = True
        return len(s)

    def flush(self) -> None:
        self.real.flush()

    def isatty(self) -> bool:
        return self.real.isatty()

    def fileno(self) -> int:
        return self.real.fileno()

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self.real, "encoding", "utf-8")

    @property
    def errors(self) -> str | None:  # type: ignore[override]
        return getattr(self.real, "errors", None)

    @property
    def buffer(self):
        return self.real.buffer

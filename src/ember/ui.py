"""The interactive prompt: a rounded input box with a live status line."""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import ThreadedCompleter
from prompt_toolkit.cursor_shapes import ModalCursorShapeConfig
from prompt_toolkit.document import Document
from prompt_toolkit.enums import DEFAULT_BUFFER, EditingMode
from prompt_toolkit.filters import (
    Condition,
    emacs_mode,
    has_completions,
    has_focus,
    has_selection,
    vi_insert_mode,
    vi_mode,
    vi_navigation_mode,
)
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.layout import (
    ConditionalContainer,
    Float,
    FloatContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import (
    AppendAutoSuggestion,
    HighlightMatchingBracketProcessor,
)
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import DynamicStyle
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import SearchToolbar
from pygments.lexers.python import PythonLexer
from rich.text import Text

from ember import __version__, signature
from ember.completer import EmberCompleter, SignatureHinter
from ember.history import PromptHistory
from ember.display import short_path
from ember.output import format_duration
from ember.shell import Shell
from ember.transform import has_prompts, is_complete, next_indent, strip_prompts

INDENT = "    "
MENU_HEIGHT = 8


def _width(fragments: StyleAndTextTuples) -> int:
    return sum(get_cwidth(f[1]) for f in fragments)


def _truncate(fragments: StyleAndTextTuples, width: int) -> StyleAndTextTuples:
    out: StyleAndTextTuples = []
    used = 0
    for style, text, *_ in fragments:
        if used + get_cwidth(text) >= width:
            out.append((style, text[: max(0, width - used - 1)] + "…"))
            break
        out.append((style, text))
        used += get_cwidth(text)
    return out


def _render_hints(hints: list[tuple[str, str]]) -> StyleAndTextTuples:
    out: StyleAndTextTuples = []
    for i, (key, label) in enumerate(hints):
        if i:
            out.append(("class:status.sep", "   "))
        out.append(("class:status.key", key))
        if label:
            out.append(("class:status.dim", f" {label}"))
    return out


class Repl:
    def __init__(self, shell: Shell):
        self.shell = shell
        self.flash: tuple[str, float] | None = None
        self.hinter = SignatureHinter(shell, self._invalidate)

        self.buffer = Buffer(
            name=DEFAULT_BUFFER,
            multiline=True,
            history=PromptHistory(shell.history),
            completer=ThreadedCompleter(EmberCompleter(shell)),
            complete_while_typing=True,
            auto_suggest=AutoSuggestFromHistory(),
            enable_history_search=Condition(lambda: "\n" not in self.buffer.text),
            on_text_changed=self._on_change,
            on_cursor_position_changed=self._on_change,
        )
        self.search = SearchToolbar(text_if_not_searching="", forward_search_prompt="  search ↓ ", backward_search_prompt="  search ↑ ")
        self.app = self._build_app()

    # ── state helpers ─────────────────────────────────────────────────────

    def _invalidate(self) -> None:
        try:
            self.app.invalidate()
        except Exception:
            pass

    def _on_change(self, _buffer: Buffer) -> None:
        self.flash = None
        self.hinter.request(self.buffer.document)

    def _incomplete(self) -> bool:
        text = self.buffer.text
        return bool(text.strip()) and not is_complete(text)

    # ── layout ────────────────────────────────────────────────────────────

    def _build_app(self) -> Application:
        input_window = Window(
            BufferControl(
                buffer=self.buffer,
                lexer=PygmentsLexer(PythonLexer),
                input_processors=[
                    HighlightMatchingBracketProcessor(chars="[](){}"),
                    AppendAutoSuggestion(),
                ],
                search_buffer_control=self.search.control,
                preview_search=True,
            ),
            height=Dimension(min=1, max=16),
            wrap_lines=True,
            get_line_prefix=self._line_prefix,
            dont_extend_height=True,
        )

        def border(char: str, **kw) -> Window:
            return Window(char=char, style=self._border_style, **kw)

        top = VSplit([
            border("╭", width=1, height=1),
            Window(FormattedTextControl(self._title), height=1, dont_extend_width=True, style=self._border_style),
            border("─", height=1),
            Window(FormattedTextControl(self._top_right), height=1, dont_extend_width=True, style=self._border_style),
            border("╮", width=1, height=1),
        ])
        middle = VSplit([
            border("│", width=1),
            Window(width=1),
            input_window,
            Window(width=1),
            border("│", width=1),
        ])
        bottom = VSplit([border("╰", width=1, height=1), border("─", height=1), border("╯", width=1, height=1)])

        status = Window(FormattedTextControl(self._status), height=1, style="class:status")
        reserve = ConditionalContainer(Window(height=MENU_HEIGHT), filter=has_completions)

        body = HSplit([top, middle, bottom, self.search, Window(height=1), status, Window(height=1), reserve])
        root = FloatContainer(
            content=body,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=MENU_HEIGHT, scroll_offset=1, extra_filter=has_focus(DEFAULT_BUFFER)),
                )
            ],
        )
        app = Application(
            layout=Layout(root, focused_element=input_window),
            key_bindings=self._bindings(),
            style=DynamicStyle(lambda: self.shell.theme.pt_style),
            include_default_pygments_style=False,
            erase_when_done=True,
            mouse_support=False,
            cursor=ModalCursorShapeConfig(),
        )
        app.ttimeoutlen = 0.05  # escape sequences arrive together; don't make vi users wait on Esc
        app.key_processor.after_key_press += lambda _: app.invalidate()
        return app

    def _border_style(self) -> str:
        return "class:box.border.active" if self.buffer.text else "class:box.border"

    def _line_prefix(self, line_number: int, wrap_count: int) -> StyleAndTextTuples:
        if wrap_count:
            return [("class:prompt.cont", "  ")]
        if line_number == 0:
            return [("class:prompt", "❯ ")]
        return [("class:prompt.cont", "· ")]

    def _title(self) -> StyleAndTextTuples:
        return [("class:box.border", "─ "), ("class:box.title", f"In [{self.shell.count + 1}]"), ("class:box.border", " ")]

    def _top_right(self) -> StyleAndTextTuples:
        tags: list[str] = []
        if self.app.editing_mode == EditingMode.VI:
            mode = self.app.vi_state.input_mode
            tags.append("NORMAL" if mode == InputMode.NAVIGATION else "REPLACE" if mode == InputMode.REPLACE else "INSERT")
        if self.shell.gui:
            tags.append(f"gui {self.shell.gui}")
        if self.shell.autoreload.enabled:
            tags.append("autoreload")
        lines = self.buffer.text.count("\n") + 1
        if lines > 1:
            tags.append(f"{lines} lines")
        if not tags:
            return [("class:box.border", "")]
        return [("class:box.label", " " + " · ".join(tags) + " "), ("class:box.border", "─")]

    def _status(self) -> StyleAndTextTuples:
        width = self.app.output.get_size().columns - 2
        left = self._status_left(width)
        hints = self._hints()
        left_w = _width(left)
        if left_w > width:
            return [("", " "), *_truncate(left, width)]
        # Drop hints from the end until everything fits.
        while hints and left_w + 4 + _width(_render_hints(hints)) > width:
            hints.pop()
        right = _render_hints(hints)
        return [("", " "), *left, ("", " " * (width - left_w - _width(right))), *right]

    def _status_left(self, width: int) -> StyleAndTextTuples:
        if self.flash and time.monotonic() < self.flash[1]:
            return [("class:status.warn", self.flash[0])]
        if self.hinter.current and "(" in self.buffer.text:
            return signature.render(self.hinter.current, width)
        sep = ("class:status.sep", "  ·  ")
        out: StyleAndTextTuples = [("class:status.accent", "● "), ("class:status", f"py {platform.python_version()}")]
        venv = os.environ.get("VIRTUAL_ENV") or (sys.prefix if sys.prefix != sys.base_prefix else "")
        if venv:
            out += [sep, ("class:status.dim", "venv "), ("class:status", Path(venv).name)]
        out += [sep, ("class:status", short_path(os.getcwd()))]
        if self.shell.last_duration is not None:
            mark = ("class:status.ok", "✓ ") if self.shell.last_ok else ("class:status.err", "✗ ")
            out += [sep, mark, ("class:status", format_duration(self.shell.last_duration))]
        return out

    def _hints(self) -> list[tuple[str, str]]:
        if self.buffer.complete_state:
            return [("tab", "next"), ("⏎", "accept"), ("esc", "close")]
        if self._incomplete():
            return [("⏎", "newline"), ("⏎ on blank line", "run"), ("ctrl+o", "editor")]
        if not self.buffer.text:
            return [("%help", ""), ("obj?", "inspect"), ("ctrl+d", "exit"), ("ctrl+r", "history")]
        return [("⏎", "run"), ("alt+⏎", "newline"), ("ctrl+o", "editor")]

    # ── keys ──────────────────────────────────────────────────────────────

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()
        focused = has_focus(DEFAULT_BUFFER)
        insert_mode = emacs_mode | vi_insert_mode

        @kb.add(Keys.BracketedPaste, filter=focused)
        def _paste(event: KeyPressEvent) -> None:
            data = event.data.replace("\r\n", "\n").replace("\r", "\n")
            if has_prompts(data):
                data = strip_prompts(data)
            event.current_buffer.insert_text(data)

        @kb.add("enter", filter=focused & vi_mode & vi_navigation_mode & ~has_selection)
        def _vi_enter(event: KeyPressEvent) -> None:
            if is_complete(event.current_buffer.text):
                self._submit(event)

        @kb.add("enter", filter=focused & ~has_selection & insert_mode)
        def _enter(event: KeyPressEvent) -> None:
            b = event.current_buffer
            state = b.complete_state
            if state and state.current_completion:
                b.apply_completion(state.current_completion)
                return
            if state:
                b.cancel_completion()
            at_end = not b.document.text_after_cursor.strip()
            if (at_end or "\n" not in b.text) and is_complete(b.text):
                self._submit(event)
                return
            self._newline(b)

        @kb.add("escape", "enter", filter=focused & insert_mode)
        @kb.add("c-j", filter=focused & insert_mode)
        def _newline(event: KeyPressEvent) -> None:
            self._newline(event.current_buffer)

        @kb.add("tab", filter=focused & ~has_selection & insert_mode)
        def _tab(event: KeyPressEvent) -> None:
            b = event.current_buffer
            if b.complete_state:
                b.complete_next()
            elif not b.document.current_line_before_cursor.strip():
                b.insert_text(INDENT)
            else:
                b.start_completion(insert_common_part=True)

        @kb.add("s-tab", filter=focused & insert_mode)
        def _stab(event: KeyPressEvent) -> None:
            b = event.current_buffer
            if b.complete_state:
                b.complete_previous()
                return
            doc = b.document
            line = doc.current_line
            remove = min(len(INDENT), len(line) - len(line.lstrip(" ")))
            if remove:
                start = doc.translate_row_col_to_index(doc.cursor_position_row, 0)
                text = doc.text[:start] + doc.text[start + remove:]
                b.document = Document(text, max(start, doc.cursor_position - remove))

        @kb.add("backspace", filter=focused & insert_mode & Condition(self._in_indent))
        def _backspace(event: KeyPressEvent) -> None:
            b = event.current_buffer
            before = b.document.current_line_before_cursor
            b.delete_before_cursor(len(before) % len(INDENT) or len(INDENT))

        @kb.add("escape", filter=focused & has_completions, eager=True)
        def _escape(event: KeyPressEvent) -> None:
            b = event.current_buffer
            b.cancel_completion()
            # In vi, Esc must still leave insert mode even though it also closed the menu.
            if event.app.editing_mode == EditingMode.VI and event.app.vi_state.input_mode != InputMode.NAVIGATION:
                event.app.vi_state.input_mode = InputMode.NAVIGATION
                b.cursor_position += b.document.get_cursor_left_position()

        @kb.add("c-c", filter=focused)
        def _ctrl_c(event: KeyPressEvent) -> None:
            b = event.current_buffer
            if b.text:
                b.reset()
            else:
                self.flash = ("press ctrl+d to exit", time.monotonic() + 2.5)
                event.app.invalidate()

        @kb.add("c-d", filter=focused & Condition(lambda: not self.buffer.text))
        def _ctrl_d(event: KeyPressEvent) -> None:
            event.app.exit(result=None)

        @kb.add("c-l")
        def _clear(event: KeyPressEvent) -> None:
            event.app.renderer.clear()

        @kb.add("c-o", filter=focused)
        @kb.add("f2", filter=focused)
        def _editor(event: KeyPressEvent) -> None:
            event.current_buffer.open_in_editor(validate_and_handle=False)

        return kb

    def _submit(self, event: KeyPressEvent) -> None:
        b = event.current_buffer
        text = b.text
        if text.strip():
            b.document = Document(text.rstrip())
            b.append_to_history()
        event.app.exit(result=text)

    def _in_indent(self) -> bool:
        before = self.buffer.document.current_line_before_cursor
        return len(before) > 0 and not before.strip(" ") and not self.buffer.selection_state

    def _newline(self, b: Buffer) -> None:
        line = b.document.current_line_before_cursor
        b.insert_text("\n" + next_indent(line))

    # ── main loop ─────────────────────────────────────────────────────────

    def banner(self) -> None:
        ui = self.shell.ui
        name = Text()
        for ch, color in zip("ember", ("ember.accent", "ember.accent", "ember.accent2", "ember.accent2", "ember.accent2")):
            name.append(ch, style=f"bold {color}")
        ui.print()
        ui.print(Text.assemble(("  ✦ ", "ember.accent"), name, (f"  v{__version__}", "ember.faint")))
        ui.print()
        ui.print(
            Text.assemble(
                ("    python ", "ember.faint"), (platform.python_version(), "ember.muted"),
                ("  ·  ", "ember.faint"), (short_path(os.getcwd()), "ember.muted"),
                ("  ·  ", "ember.faint"), ("theme ", "ember.faint"), (self.shell.theme.name, "ember.muted"),
            )
        )
        ui.print(
            Text.assemble(
                ("    ", ""), ("%help", "ember.accent"), (" commands  ", "ember.faint"),
                ("obj?", "ember.accent"), (" inspect  ", "ember.faint"),
                ("!cmd", "ember.accent"), (" shell  ", "ember.faint"),
                ("ctrl+d", "ember.accent"), (" exit", "ember.faint"),
            )
        )
        ui.print("\n")

    def read(self) -> str | None:
        initial, self.shell.next_input = self.shell.next_input, ""
        self.hinter.clear()
        self.flash = None

        vi = self.shell.settings.editing_mode == "vi"
        self.app.editing_mode = EditingMode.VI if vi else EditingMode.EMACS
        # Esc is a prefix of alt+key bindings; vi users need it to take effect almost immediately.
        self.app.timeoutlen = 0.15 if vi else 1.0

        def pre_run() -> None:
            self.buffer.reset(Document(initial, len(initial)))
            if self.app.editing_mode == EditingMode.VI:
                self.app.vi_state.input_mode = InputMode.INSERT

        with patch_stdout(raw=True):
            return self.app.run(pre_run=pre_run, inputhook=self._inputhook() if self.shell.inputhook else None)

    def _inputhook(self):
        """Wrap the shell's GUI hook: prompt_toolkit's own loop is 'running' while hooks run."""
        hook = self.shell.inputhook

        def run(context) -> None:
            running = asyncio.events._get_running_loop()
            asyncio.events._set_running_loop(None)
            try:
                hook(context)
            except Exception as e:
                self.shell.enable_gui(None)
                self.flash = (f"gui event loop failed and was disabled: {e}", time.monotonic() + 5)
            finally:
                asyncio.events._set_running_loop(running)

        return run

    def run(self) -> int:
        self.banner()
        code = 0
        try:
            while True:
                try:
                    text = self.read()
                except (EOFError, KeyboardInterrupt):
                    break
                if text is None:
                    break
                try:
                    self.shell.run_cell(text)
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else 0
                    break
        finally:
            self.shell.close()
        self.shell.ui.print(Text("  goodbye ✦", style="ember.faint"))
        return code

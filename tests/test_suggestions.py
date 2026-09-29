"""Inline history suggestions: → / ctrl+e / ctrl+f accept the ghost text."""

import threading
import time

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from ember.config import Settings
from ember.shell import Shell
from ember.ui import Repl

PREVIOUS = "answer = 42 + 8"


def type_and_accept(profile, keys: str, vi: bool = False) -> str:
    """Type 'ans', press `keys`, then Enter; return the cell ember would run.

    The keys go in stages from another thread: prompt_toolkit loads history and computes the
    suggestion in the background, so a single burst would arrive before any suggestion exists."""
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        shell = Shell(Settings(editing_mode="vi" if vi else "emacs"), profile)
        shell.history.store_input(1, PREVIOUS)
        repl = Repl(shell)

        def type_it() -> None:
            for chunk in ("ans", keys, "\r"):
                time.sleep(0.25)
                if chunk:
                    pipe.send_text(chunk)

        typist = threading.Thread(target=type_it, daemon=True)
        typist.start()
        try:
            return repl.read()
        finally:
            typist.join(timeout=2)
            shell.close()


@pytest.mark.parametrize("keys, name", [("\x1b[C", "right"), ("\x05", "ctrl-e"), ("\x06", "ctrl-f")])
def test_keys_accept_the_suggestion(profile, keys, name):
    assert type_and_accept(profile, keys) == PREVIOUS


def test_right_accepts_in_vi_insert_mode(profile):
    assert type_and_accept(profile, "\x1b[C", vi=True) == PREVIOUS


def test_without_accepting_only_the_typed_text_runs(profile):
    assert type_and_accept(profile, "") == "ans"

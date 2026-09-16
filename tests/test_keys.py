"""Terminal key encodings: modified Enter inserts a newline; other modified keys don't leak as text."""

import pytest
from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.keys import Keys

import ember.ui  # noqa: F401  registers the sequences


def parse(data: str):
    keys = []
    parser = Vt100Parser(keys.append)
    parser.feed(data)
    parser.flush()
    return [k.key for k in keys]


@pytest.mark.parametrize("seq", ["\x1b[13;2u", "\x1b[27;2;13~", "\x1b[13;6u", "\x1b[13;5u", "\x1b[27;5;13~"])
def test_modified_enter_is_newline(seq):
    assert parse(seq) == [Keys.ControlJ]


def test_plain_enter_still_submits():
    assert parse("\r") == [Keys.ControlM]


def test_other_modified_keys_are_ignored_not_inserted():
    assert parse("\x1b[53;6u\x1b[13;2u") == [Keys.Ignore, Keys.ControlJ]

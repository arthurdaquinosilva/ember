import pytest

from ember.shell import Shell


@pytest.fixture
def shell(capsys):
    return Shell()


def test_expression_result_is_stored(shell):
    shell.run_cell("1 + 2")
    assert shell.Out[1] == 3
    assert shell.ns["_"] == 3
    assert shell.ns["_1"] == 3
    assert shell.last_ok


def test_trailing_semicolon_suppresses_output(shell):
    shell.run_cell("1 + 2;")
    assert shell.Out == {}


def test_top_level_await(shell):
    shell.run_cell("import asyncio\nasync def f():\n    await asyncio.sleep(0)\n    return 7\nawait f()")
    assert shell.Out[1] == 7


def test_exception_marks_failure(shell):
    shell.run_cell("1/0")
    assert not shell.last_ok
    assert shell.last_traceback is not None


def test_unknown_magic_suggests(shell, capsys):
    shell.run_cell("%timit 1")
    assert not shell.last_ok


def test_shell_capture(shell):
    shell.run_cell("out = !echo hello")
    assert shell.ns["out"] == ["hello"]


def test_reset(shell):
    shell.run_cell("a = 1")
    shell.run_cell("%reset")
    assert "a" not in shell.ns


def test_exit_raises_system_exit(shell):
    with pytest.raises(SystemExit):
        shell.run_cell("exit")

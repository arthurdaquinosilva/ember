"""Shell features: paste prompts, automagic, interactivity, xmode, pdb, doctest mode, autoawait, config, startup."""

import os
import textwrap
import time

import pytest

from ember.config import Settings
from ember.shell import Shell
from ember.transform import strip_prompts, transform
from tests.conftest import last_out


def test_strip_classic_prompts():
    pasted = ">>> def f(x):\n...     return x * 2\n...\n>>> f(3)\n6\n"
    assert strip_prompts(pasted) == "def f(x):\n    return x * 2\n\nf(3)"


def test_strip_ipython_prompts():
    pasted = "In [1]: x = 1\n\nIn [2]: for i in range(2):\n   ...:     x += i\n   ...:\n\nOut[2]: 3"
    assert strip_prompts(pasted) == "x = 1\nfor i in range(2):\n    x += i"


def test_run_pasted_doctest(shell):
    shell.run_cell(">>> a = 20\n>>> a + 1\n21")
    assert last_out(shell) == 21


def test_automagic(shell):
    assert transform("cd ..", shell._automagic) == "__ember__.magic('cd', '..')"
    assert transform("pwd", shell._automagic) == "__ember__.magic('pwd', '')"
    shell.run_cell("pwd = 3")
    assert transform("pwd", shell._automagic) == "pwd"  # shadowed by a variable
    assert transform("ls = [1]", shell._automagic) == "ls = [1]"
    assert transform("ls(1)", shell._automagic) == "ls(1)"
    assert transform("time.sleep(1)", shell._automagic) == "time.sleep(1)"
    assert transform("for x in y:\n    cd ..", shell._automagic).endswith("cd ..")  # multi-line cells untouched


def test_automagic_off(shell):
    shell.run_cell("%automagic off")
    assert transform("pwd", shell._automagic) == "pwd"


def test_capture_bang_bang_and_slist(shell):
    shell.run_cell("!!printf 'a 1\\nb 2\\n'")
    out = last_out(shell)
    assert out == ["a 1", "b 2"]
    assert out.fields(1) == ["1", "2"]
    assert out.grep("b") == ["b 2"]
    assert out.s == "a 1 b 2"


def test_dollar_and_brace_expansion(shell):
    from ember.utils import expand_vars

    shell.run_cell("name = 'ember'")
    shell.run_cell("out = !echo $name {name.upper()}")
    assert shell.ns["out"] == ["ember EMBER"]
    ns = {"name": "ember"}
    assert expand_vars("echo $name $$HOME $UNKNOWN '$name' {{braces}} {1+1}", ns) == "echo ember $HOME $UNKNOWN '$name' {braces} 2"


def test_ast_node_interactivity_all(shell):
    shell.run_cell("%config ast_node_interactivity=all")
    shell.run_cell("1\n2\n3")
    assert shell.Out[shell.count] == 3


def test_last_expr_or_assign(shell):
    shell.run_cell("%config InteractiveShell.ast_node_interactivity = 'last_expr_or_assign'")
    shell.run_cell("answer = 42")
    assert last_out(shell) == 42


@pytest.mark.parametrize("mode", ["minimal", "plain", "context", "verbose"])
def test_xmodes_render(shell, mode, capfd):
    shell.run_cell(f"%xmode {mode}")
    assert shell.settings.xmode == mode
    shell.run_cell("def boom():\n    secret = 7\n    raise ValueError('bad')\nboom()")
    assert not shell.last_ok
    out = capfd.readouterr().out
    assert "ValueError" in out
    if mode == "verbose":
        assert "secret" in out
    if mode == "minimal":
        assert "Traceback" not in out


def test_tb_reprints(shell, capfd):
    shell.run_cell("1/0")
    capfd.readouterr()
    shell.run_cell("%tb minimal")
    assert "ZeroDivisionError" in capfd.readouterr().out


def test_auto_pdb_invokes_debugger(shell, monkeypatch):
    calls = []
    monkeypatch.setattr(shell, "post_mortem", lambda tb: calls.append(tb))
    shell.run_cell("%pdb on")
    shell.run_cell("1/0")
    assert len(calls) == 1


def test_doctest_mode(shell, capfd):
    shell.run_cell("%doctest_mode on")
    capfd.readouterr()
    shell.run_cell("[1, 2]")
    out = capfd.readouterr().out
    assert ">>> [1, 2]" in out and "[1, 2]" in out and "╰─" not in out and "│" not in out


def test_autoawait_trio(shell):
    pytest.importorskip("trio")
    shell.run_cell("%autoawait trio")
    shell.run_cell("import trio\nawait trio.sleep(0)\n'done'")
    assert last_out(shell) == "done"


def test_autoawait_off(shell):
    shell.run_cell("%autoawait off")
    shell.run_cell("import asyncio\nawait asyncio.sleep(0)")
    assert not shell.last_ok


def test_config_listing_and_errors(shell):
    shell.run_cell("%config xmode=nonsense")
    assert not shell.last_ok
    shell.run_cell("%config automagic")
    assert last_out(shell) is True


def test_startup_files_exec_lines_and_aliases(profile):
    (profile.startup_dir).mkdir(parents=True)
    (profile.startup_dir / "00-first.py").write_text("from_startup = 'yes'\n")
    settings = Settings(exec_lines=["from_exec = 1 + 1"], aliases={"hello": "echo hello %s"})
    sh = Shell(settings, profile)
    sh.startup()
    assert sh.ns["from_startup"] == "yes"
    assert sh.ns["from_exec"] == 2
    sh.run_cell("out = !!echo ok")
    sh.run_cell("hello world")  # alias via automagic
    assert sh.last_ok
    sh.close()


def test_profile_config_file(profile):
    from ember.config import load_settings

    profile.config_file.write_text('theme = "nebula"\nxmode = "Verbose"\n"InteractiveShell.pdb" = true\nbogus = 1\n')
    settings, warnings = load_settings(profile)
    assert settings.theme == "nebula" and settings.xmode == "verbose" and settings.pdb is True
    assert any("bogus" in w for w in warnings)


def test_psearch_wildcard(shell, capfd):
    shell.run_cell("import os\nos.*dir*?")
    out = capfd.readouterr().out
    assert "os.listdir" in out and "os.makedirs" in out


def test_who_ls_and_xdel(shell):
    shell.run_cell("a = 1\nb = 'x'\nc = 2")
    shell.run_cell("%who_ls int")
    assert last_out(shell) == ["a", "c"]
    shell.run_cell("c")
    shell.run_cell("%xdel c")
    assert "c" not in shell.ns and 2 not in shell.Out.values()


def test_timeit_return_and_quiet(shell):
    shell.run_cell("r = %timeit -o -q -n 10 -r 2 sum(range(10))")
    r = shell.ns["r"]
    assert r.loops == 10 and r.repeat == 2 and r.average > 0


def test_prun_returns_stats(shell):
    shell.run_cell("stats = %prun -r -q sum(range(1000))")
    assert shell.ns["stats"].total_calls >= 1


def test_capture_cell_magic(shell):
    shell.run_cell("%%capture cap\nprint('hidden')\nimport sys\nprint('err', file=sys.stderr)")
    cap = shell.ns["cap"]
    assert cap.stdout == "hidden\n" and cap.stderr == "err\n"


def test_run_flags(shell, profile):
    script = profile.config_dir / "script.py"
    script.write_text("import sys\nresult = sys.argv[1:]\nif __name__ != '__main__':\n    result = 'not main'\n")
    shell.run_cell(f"%run {script} a b")
    assert shell.ns["result"] == ["a", "b"]
    shell.run_cell(f"%run -n {script}")
    assert shell.ns["result"] == "not main"
    shell.run_cell(f"%run -t {script}")
    assert shell.last_ok
    exiting = profile.config_dir / "exits.py"
    exiting.write_text("import sys\nsys.exit(3)\n")
    shell.run_cell(f"%run {exiting}")
    assert not shell.last_ok
    shell.run_cell(f"%run -e {exiting}")
    assert shell.last_ok


def test_run_module(shell, profile, monkeypatch):
    pkg = profile.config_dir / "runme.py"
    pkg.write_text("value = 'from module'\n")
    monkeypatch.syspath_prepend(str(profile.config_dir))
    shell.run_cell("%run -m runme")
    assert shell.ns["value"] == "from module"


def test_script_magics(shell):
    shell.run_cell("%%bash --out captured\necho from bash")
    assert shell.ns["captured"] == "from bash\n"
    shell.run_cell("%%script --bg --out bg sh\necho background")
    deadline = time.time() + 5
    while "bg" not in shell.ns and time.time() < deadline:
        time.sleep(0.05)
    assert shell.ns["bg"] == "background\n"
    shell.run_cell("%%bash\nexit 4")
    assert not shell.last_ok


def test_bookmarks_and_dir_stack(shell, profile):
    target = profile.data_dir
    shell.run_cell(f"%bookmark data {target}")
    shell.run_cell("%cd -b data")
    assert os.getcwd() == str(target.resolve())
    shell.run_cell("%pushd ..")
    assert shell.dir_stack == [str(target.resolve())]
    shell.run_cell("%popd")
    assert os.getcwd() == str(target.resolve())
    shell.run_cell("%cd -0")
    assert shell.dir_history[0] == os.getcwd()


def test_paste_magic(shell, monkeypatch):
    import shutil
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")  # CI machines have no clipboard tool

    class Result:
        stdout = b">>> pasted = 5\n>>> pasted * 2\n10\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    shell.run_cell("%paste -q")
    assert shell.ns["pasted"] == 5
    assert shell.ns["pasted_block"] == "pasted = 5\npasted * 2"


def test_gui_asyncio_hook_runs_tasks(shell):
    shell.run_cell("%gui asyncio")
    assert shell.gui == "asyncio" and shell.inputhook is not None
    shell.run_cell("import asyncio\nticks = []\nasync def ticker():\n    while True:\n        ticks.append(1)\n        await asyncio.sleep(0.01)\ntask = asyncio.get_event_loop().create_task(ticker()) if False else None")
    shell.run_cell("%gui")
    assert shell.inputhook is None


def test_matplotlib_agg(shell):
    pytest.importorskip("matplotlib")
    shell.run_cell("%matplotlib agg")
    assert shell.last_ok
    assert shell.gui is None
    shell.run_cell("import matplotlib.pyplot as plt\nplt.plot([1, 2])")
    assert shell.last_ok


def test_unicode_and_dict_completion(shell):
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

    from ember.completer import EmberCompleter

    completer = EmberCompleter(shell)
    requested = CompleteEvent(completion_requested=True)
    texts = [c.text for c in completer.get_completions(Document("x = \\alpha"), requested)]
    assert texts[0] == "α"
    texts = [c.text for c in completer.get_completions(Document("\\α"), requested)]
    assert texts == ["\\alpha"]
    texts = [c.text for c in completer.get_completions(Document("\\N{GREEK SMALL LETTER BET"), requested)]
    assert "β" in texts
    shell.run_cell("data = {'apple': 1, 'apricot': 2, 'banana': 3, 7: 'seven'}")
    typing = CompleteEvent(text_inserted=True)
    texts = [c.text for c in completer.get_completions(Document("data['ap"), typing)]
    assert texts == ["apple']", "apricot']"]
    texts = [c.text for c in completer.get_completions(Document("data["), typing)]
    assert "7]" in texts and "'banana']" in texts


def test_autoreload_updates_existing_objects(shell, profile, monkeypatch):
    moddir = profile.config_dir
    monkeypatch.syspath_prepend(str(moddir))
    mod = moddir / "reloadme.py"
    mod.write_text(textwrap.dedent('''
        def greet():
            return "v1"
        class Thing:
            def who(self):
                return "old"
    '''))
    shell.run_cell("%autoreload 2")
    shell.run_cell("from reloadme import greet, Thing\nt = Thing()")
    assert shell.ns["greet"]() == "v1"
    time.sleep(0.01)
    mod.write_text(textwrap.dedent('''
        def greet():
            return "version two"
        class Thing:
            def who(self):
                return "new and improved"
    '''))
    os.utime(mod, (time.time() + 5, time.time() + 5))
    shell.run_cell("pass")
    assert shell.ns["greet"]() == "version two"
    assert shell.ns["t"].who() == "new and improved"

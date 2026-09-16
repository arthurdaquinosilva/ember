"""SQLite history, ranges, history magics, macros, %store, logging, save/load."""

import pickle

from ember.config import Settings
from ember.history import HistoryManager
from ember.shell import Shell


def test_ranges_and_sessions(tmp_path):
    db = tmp_path / "h.sqlite"
    first = HistoryManager(db)
    for i, src in enumerate(["a = 1", "b = 2", "c = 3"], 1):
        first.store_input(i, src)
    first.end_session()
    second = HistoryManager(db)
    second.store_input(1, "d = 4")
    assert [e.source for e in second.get_range_by_str("~1/")] == ["a = 1", "b = 2", "c = 3"]
    assert [e.source for e in second.get_range_by_str("~1/2-3")] == ["b = 2", "c = 3"]
    assert [e.source for e in second.get_range_by_str("~1/1:3")] == ["a = 1", "b = 2"]
    assert [e.source for e in second.get_range_by_str("1")] == ["d = 4"]
    assert [e.source for e in second.search("b*")] == ["b = 2"]
    assert second.recent_inputs()[:2] == ["d = 4", "c = 3"]


def test_history_persists_across_shells(profile):
    one = Shell(Settings(), profile)
    one.run_cell("x = 'persisted'")
    one.run_cell("x")
    one.close()
    two = Shell(Settings(), profile)
    two.run_cell("%history -o ~1/")
    assert two.last_ok
    entries = two.history.get_range_by_str("~1/", output=True)
    assert entries[1].output == "'persisted'"
    two.close()


def test_input_variables(shell):
    shell.run_cell("1")
    shell.run_cell("2")
    shell.run_cell("3")
    assert shell.ns["_i"] == "2" and shell.ns["_ii"] == "1" and shell.ns["_i3"] == "3"
    assert shell.ns["_ih"] is shell.In and shell.ns["_oh"] is shell.Out


def test_recall_and_rerun(shell):
    shell.run_cell("counter = 0")
    shell.run_cell("counter += 1")
    shell.run_cell("%rerun")
    assert shell.ns["counter"] == 2
    shell.run_cell("%recall 2")
    assert shell.next_input == "counter += 1"


def test_macro(shell):
    shell.run_cell("total = 0")
    shell.run_cell("total += 5")
    shell.run_cell("%macro -q add5 2")
    shell.run_cell("add5")
    shell.run_cell("add5")
    assert shell.ns["total"] == 15


def test_store(shell, profile):
    shell.run_cell("keep = {'a': [1, 2]}")
    shell.run_cell("%store keep")
    assert pickle.loads((profile.store_dir / "keep").read_bytes()) == {"a": [1, 2]}
    shell.run_cell("del keep")
    shell.run_cell("%store -r keep")
    assert shell.ns["keep"] == {"a": [1, 2]}
    shell.run_cell("%store -d keep")
    assert not (profile.store_dir / "keep").exists()


def test_store_autorestore(profile):
    one = Shell(Settings(), profile)
    one.run_cell("saved = 99")
    one.run_cell("%store saved")
    one.close()
    two = Shell(Settings(store_autorestore=True), profile)
    two.startup()
    assert two.ns["saved"] == 99
    two.close()


def test_logstart(shell, profile):
    log = profile.data_dir / "session.py"
    shell.run_cell(f"%logstart -o {log} over")
    shell.run_cell("z = 1 + 1")
    shell.run_cell("z")
    shell.run_cell("%logstop")
    text = log.read_text()
    assert "z = 1 + 1" in text and "#[Out]# 2" in text


def test_save_and_load_ranges(shell, profile):
    shell.run_cell("def f():\n    return 'saved'")
    shell.run_cell("value = f()")
    target = profile.data_dir / "out.py"
    shell.run_cell(f"%save {target} 1-2")
    assert "def f():" in target.read_text() and "value = f()" in target.read_text()
    shell.run_cell(f"%load -s f {target}")
    assert shell.next_input.startswith("def f():") and "value" not in shell.next_input
    shell.run_cell("%load 2")
    assert shell.next_input == "value = f()"


def test_history_magic_search_and_file(shell, profile):
    shell.run_cell("import json")
    shell.run_cell("json.dumps({})")
    out = profile.data_dir / "hist.txt"
    shell.run_cell(f"%history -g json -f {out}")
    assert "import json" in out.read_text()
    assert "history" not in out.read_text()
    shell.run_cell("%history -l 2")
    assert shell.last_ok

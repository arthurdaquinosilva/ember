import pytest

from ember.config import Profile, Settings
from ember.shell import Shell


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = Profile("test", tmp_path / "config", tmp_path / "data")
    p.ensure()
    return p


@pytest.fixture
def shell(profile):
    sh = Shell(Settings(), profile)
    sh.startup()
    yield sh
    sh.close()


def last_out(shell):
    return shell.Out[max(shell.Out)] if shell.Out else None

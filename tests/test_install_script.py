"""The install script must stay a valid, self-describing POSIX shell script."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "install.sh"


def test_is_valid_posix_sh():
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)


def test_help_lists_the_options():
    out = subprocess.run(["sh", str(SCRIPT), "--help"], capture_output=True, text=True, check=True).stdout
    for option in ("--uninstall", "EMBER_VERSION", "EMBER_NO_PIPX", "EMBER_INSTALL_DIR"):
        assert option in out


def test_rejects_unknown_options():
    result = subprocess.run(["sh", str(SCRIPT), "--wat"], capture_output=True, text=True)
    assert result.returncode != 0 and "unknown option" in result.stderr


def test_installs_the_published_package_name():
    assert 'PACKAGE="ember-shell"' in SCRIPT.read_text()


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck is not installed")
def test_shellcheck_clean():
    subprocess.run(["shellcheck", str(SCRIPT)], check=True)

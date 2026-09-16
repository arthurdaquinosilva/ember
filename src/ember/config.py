"""Settings, profiles and their on-disk locations."""

from __future__ import annotations

import ast
import dataclasses
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

XMODES = ("minimal", "plain", "context", "verbose")
INTERACTIVITY = ("last_expr", "all", "last", "none", "last_expr_or_assign")
AUTOAWAIT = ("asyncio", "trio", "curio", "off")
EDITING_MODES = ("emacs", "vi")
LAYOUTS = ("block", "box")


@dataclass
class Settings:
    theme: str = "void"
    layout: str = "block"
    editing_mode: str = "emacs"
    automagic: bool = True
    autoreload: int = 0
    pdb: bool = False
    xmode: str = "context"
    autoawait: str = "asyncio"
    precision: str = ""
    ast_node_interactivity: str = "last_expr"
    gui: str = ""
    matplotlib: str = ""
    store_autorestore: bool = False
    history_log_output: bool = True
    exec_lines: list[str] = field(default_factory=list)
    exec_files: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)

    def validate(self, name: str, value: Any) -> Any:
        """Coerce and check a value for setting `name`; raises ValueError/KeyError."""
        spec = {f.name: f for f in fields(self)}[name]
        default = spec.default if spec.default is not dataclasses.MISSING else spec.default_factory()  # type: ignore[misc]
        if isinstance(value, str) and not isinstance(default, str):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                lowered = value.strip().lower()
                if isinstance(default, bool) and lowered in ("on", "off", "yes", "no", "true", "false"):
                    value = lowered in ("on", "yes", "true")
                else:
                    raise ValueError(f"{name} expects a {type(default).__name__}") from None
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, int):
            value = int(value)
        elif isinstance(default, str):
            value = str(value).strip().strip("'\"")
        choices = {
            "xmode": XMODES,
            "ast_node_interactivity": INTERACTIVITY,
            "autoawait": AUTOAWAIT,
            "editing_mode": EDITING_MODES,
            "layout": LAYOUTS,
        }.get(name)
        if choices:
            value = value.lower()
            if value not in choices:
                raise ValueError(f"{name} must be one of: {', '.join(choices)}")
        if name == "autoreload" and value not in (0, 1, 2):
            raise ValueError("autoreload must be 0, 1 or 2")
        return value


# IPython's traitlet names → ember settings, so `%config InteractiveShell.xmode = "Verbose"` works.
IPYTHON_CONFIG_ALIASES = {
    "InteractiveShell.ast_node_interactivity": "ast_node_interactivity",
    "InteractiveShell.automagic": "automagic",
    "InteractiveShell.autoawait": "autoawait",
    "InteractiveShell.pdb": "pdb",
    "InteractiveShell.xmode": "xmode",
    "TerminalInteractiveShell.editing_mode": "editing_mode",
    "InteractiveShellApp.exec_lines": "exec_lines",
    "InteractiveShellApp.exec_files": "exec_files",
    "InteractiveShellApp.extensions": "extensions",
    "InteractiveShellApp.gui": "gui",
    "InteractiveShellApp.matplotlib": "matplotlib",
    "StoreMagics.autorestore": "store_autorestore",
    "PlainTextFormatter.float_precision": "precision",
    "HistoryManager.db_log_output": "history_log_output",
}


def resolve_setting_name(name: str) -> str:
    name = name.strip()
    for key in (name, *(k for k in IPYTHON_CONFIG_ALIASES if k.split(".")[-1] == name.split(".")[-1])):
        if key in IPYTHON_CONFIG_ALIASES:
            return IPYTHON_CONFIG_ALIASES[key]
    names = {f.name for f in fields(Settings)}
    short = name.split(".")[-1]
    if short in names:
        return short
    raise KeyError(name)


@dataclass
class Profile:
    name: str
    config_dir: Path
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def startup_dir(self) -> Path:
        return self.config_dir / "startup"

    @property
    def history_db(self) -> Path:
        return self.data_dir / "history.sqlite"

    @property
    def store_dir(self) -> Path:
        return self.data_dir / "store"

    @property
    def bookmarks_file(self) -> Path:
        return self.data_dir / "bookmarks.json"

    def ensure(self) -> None:
        for d in (self.config_dir, self.data_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass


def _base(env: str, fallback: str) -> Path:
    return Path(os.environ.get(env) or os.path.expanduser(fallback)) / "ember"


def load_profile(name: str | None = None) -> Profile:
    name = name or os.environ.get("EMBER_PROFILE") or "default"
    config, data = _base("XDG_CONFIG_HOME", "~/.config"), _base("XDG_DATA_HOME", "~/.local/share")
    if name != "default":
        config, data = config / "profiles" / name, data / "profiles" / name
    profile = Profile(name, config, data)
    profile.ensure()
    return profile


def load_settings(profile: Profile | None) -> tuple[Settings, list[str]]:
    """Read the profile's config.toml. Returns the settings and any warnings."""
    settings = Settings()
    warnings: list[str] = []
    data: dict[str, Any] = {}
    if profile is not None and profile.config_file.exists():
        try:
            import tomllib
        except ImportError:  # Python 3.10
            tomllib = None  # type: ignore[assignment]
        if tomllib is None:
            warnings.append("config.toml needs Python 3.11+ (tomllib); using defaults")
        else:
            try:
                data = tomllib.loads(profile.config_file.read_text())
            except (OSError, ValueError) as e:
                warnings.append(f"could not read {profile.config_file}: {e}")
    if theme := os.environ.get("EMBER_THEME"):
        data["theme"] = theme
    for key, value in data.items():
        try:
            name = resolve_setting_name(key)
            setattr(settings, name, settings.validate(name, value) if not isinstance(value, (list, dict)) else value)
        except (KeyError, ValueError) as e:
            warnings.append(f"config: {key}: {e}")
    return settings, warnings

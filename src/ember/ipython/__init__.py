"""IPython compatibility: `get_ipython()`, and stand-in `IPython.*` modules when IPython isn't installed.

With the stand-ins, code written for IPython (extensions such as line_profiler, `display()`,
`from IPython.core.magic import register_line_magic`, matplotlib's REPL integration) runs unchanged.
If the real IPython is installed it is left untouched; `get_ipython()` is still available as a builtin.
"""

from __future__ import annotations

import builtins
import importlib.machinery
import importlib.util
import sys
import types
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ember.ipython.shell import EmberInteractiveShell

_instance: EmberInteractiveShell | None = None
_installed = False

SHIM_VERSION = (8, 99, 0, "")


def get_ipython() -> EmberInteractiveShell | None:
    return _instance


def _module(name: str, package: bool = False, **attrs: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, None, is_package=package)
    if package:
        mod.__path__ = []  # type: ignore[attr-defined]
    mod.__dict__.update(attrs)
    mod.__ember_shim__ = True  # type: ignore[attr-defined]
    return mod


def real_ipython_available() -> bool:
    existing = sys.modules.get("IPython")
    if existing is not None:
        return not getattr(existing, "__ember_shim__", False)
    try:
        return importlib.util.find_spec("IPython") is not None
    except (ImportError, ValueError):
        return False


def install(ip: EmberInteractiveShell) -> bool:
    """Make `get_ipython()` return `ip`. Returns True if stand-in IPython modules were installed."""
    global _instance, _installed
    _instance = ip
    builtins.get_ipython = get_ipython  # type: ignore[attr-defined]
    if _installed or real_ipython_available():
        return _installed

    from ember.ipython import display, magic, pretty
    from ember.utils import SList, Struct, arg_split

    class InteractiveShell:
        @classmethod
        def initialized(cls) -> bool:
            return _instance is not None

        @classmethod
        def instance(cls, *args: Any, **kwargs: Any) -> EmberInteractiveShell | None:
            return _instance

    def page(strng: Any, start: int = 0, screen_lines: int = 0, pager_cmd: Any = None) -> None:
        if isinstance(strng, dict):
            strng = strng.get("text/plain", "")
        print(str(strng)[start:] if isinstance(start, int) and start else strng)

    def getoutput(cmd: str) -> str:
        return ip.getoutput(cmd).n if ip else ""

    display_attrs = {k: getattr(display, k) for k in dir(display) if not k.startswith("_")}
    magic_attrs = {k: getattr(magic, k) for k in dir(magic) if not k.startswith("_")}
    arguments_attrs = {k: magic_attrs[k] for k in (
        "magic_arguments", "argument", "argument_group", "defaults", "kwds", "parse_argstring",
        "construct_parser", "real_name", "MagicArgumentParser")}

    modules = {
        "IPython.core.getipython": _module("IPython.core.getipython", get_ipython=get_ipython),
        "IPython.core.magic": _module("IPython.core.magic", **magic_attrs),
        "IPython.core.magic_arguments": _module("IPython.core.magic_arguments", **arguments_attrs),
        "IPython.core.error": _module("IPython.core.error", UsageError=magic.UsageError, TryNext=magic.TryNext,
                                      StdinNotImplementedError=magic.StdinNotImplementedError,
                                      InputRejected=magic.InputRejected),
        "IPython.core.page": _module("IPython.core.page", page=page),
        "IPython.core.display": _module("IPython.core.display", **display_attrs),
        "IPython.core.display_functions": _module("IPython.core.display_functions", **display_attrs),
        "IPython.core.interactiveshell": _module("IPython.core.interactiveshell", InteractiveShell=InteractiveShell),
        "IPython.display": _module("IPython.display", **display_attrs),
        "IPython.lib.pretty": _module("IPython.lib.pretty", **{k: getattr(pretty, k) for k in dir(pretty) if not k.startswith("__")}),
        "IPython.utils.ipstruct": _module("IPython.utils.ipstruct", Struct=Struct),
        "IPython.utils.text": _module("IPython.utils.text", SList=SList),
        "IPython.utils.process": _module("IPython.utils.process", arg_split=arg_split, getoutput=getoutput),
    }
    packages = {
        "IPython": _module("IPython", package=True, get_ipython=get_ipython, __version__="8.99.0+ember",
                           version_info=SHIM_VERSION, InteractiveShell=InteractiveShell,
                           display=modules["IPython.display"]),
        "IPython.core": _module("IPython.core", package=True),
        "IPython.lib": _module("IPython.lib", package=True),
        "IPython.utils": _module("IPython.utils", package=True),
    }
    everything = {**packages, **modules}
    for name, mod in everything.items():
        sys.modules[name] = mod
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(everything[parent], child, mod)
    _installed = True
    return True

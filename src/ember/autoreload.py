"""Reload changed modules and patch existing functions/classes in place (IPython's `autoreload 2`)."""

from __future__ import annotations

import gc
import importlib
import os
import sys
import types
import weakref
from typing import Any, Iterator

from ember.display import PKG_DIR

_SKIP_ATTRS = {"__dict__", "__weakref__", "__module__", "__qualname__", "__doc__"}
_FUNC_ATTRS = ("__code__", "__defaults__", "__kwdefaults__", "__doc__", "__dict__", "__annotations__")


def update_function(old: types.FunctionType, new: types.FunctionType) -> None:
    for name in _FUNC_ATTRS:
        try:
            setattr(old, name, getattr(new, name))
        except (AttributeError, TypeError, ValueError):
            pass  # e.g. __code__ with a different number of free variables


def update_class(old: type, new: type) -> None:
    for key in list(old.__dict__):
        if key in _SKIP_ATTRS:
            continue
        if key not in new.__dict__:
            try:
                delattr(old, key)
            except (AttributeError, TypeError):
                pass
    for key, new_obj in new.__dict__.items():
        if key in _SKIP_ATTRS:
            continue
        old_obj = old.__dict__.get(key)
        if old_obj is not None and update_generic(old_obj, new_obj):
            continue
        try:
            setattr(old, key, new_obj)
        except (AttributeError, TypeError):
            pass


def update_property(old: property, new: property) -> None:
    for attr in ("fget", "fset", "fdel"):
        a, b = getattr(old, attr), getattr(new, attr)
        if a is not None and b is not None:
            update_generic(a, b)


def update_generic(old: Any, new: Any) -> bool:
    """Patch `old` to behave like `new`. Returns True if a strategy applied."""
    if isinstance(old, types.FunctionType) and isinstance(new, types.FunctionType):
        update_function(old, new)
    elif isinstance(old, type) and isinstance(new, type):
        update_class(old, new)
    elif isinstance(old, property) and isinstance(new, property):
        update_property(old, new)
    elif isinstance(old, (classmethod, staticmethod)) and isinstance(new, type(old)):
        update_generic(old.__func__, new.__func__)
    elif isinstance(old, types.MethodType) and isinstance(new, types.MethodType):
        update_generic(old.__func__, new.__func__)
    else:
        return False
    return True


class AutoReloader:
    """mode 0: off · 1: only modules marked with %aimport · 2: everything but %aimport -excluded."""

    def __init__(self) -> None:
        self.mode = 0
        self.included: set[str] = set()
        self.excluded: set[str] = set()
        self.mtimes: dict[str, float] = {}
        self.failed: dict[str, float] = {}
        # (module, name) → weakrefs to every version of that object we've seen
        self.old_objects: dict[tuple[str, str], list[weakref.ref]] = {}
        self._skip = tuple({sys.prefix, sys.base_prefix, sys.exec_prefix, PKG_DIR})

    @property
    def enabled(self) -> bool:
        return self.mode > 0

    def _source(self, mod: types.ModuleType) -> str | None:
        file = getattr(mod, "__file__", None)
        if not file:
            return None
        if file.endswith((".pyc", ".pyo")):
            file = file[:-1]
        if not file.endswith(".py") or file.startswith(self._skip) or "site-packages" in file:
            return None
        return file

    def _candidates(self) -> Iterator[tuple[str, types.ModuleType, str]]:
        for name, mod in list(sys.modules.items()):
            if not isinstance(mod, types.ModuleType) or name == "__main__":
                continue
            if self.mode == 1 and name not in self.included:
                continue
            if name in self.excluded:
                continue
            file = self._source(mod)
            if file:
                yield name, mod, file

    def snapshot(self) -> None:
        for name, mod, file in self._candidates():
            try:
                self.mtimes[name] = os.path.getmtime(file)
            except OSError:
                pass
            self._remember(mod)

    def record_new(self) -> None:
        """Note modules imported since the last check, so later edits to them are detected."""
        if not self.enabled:
            return
        for name, mod, file in self._candidates():
            if name not in self.mtimes:
                try:
                    self.mtimes[name] = os.path.getmtime(file)
                except OSError:
                    continue
                self._remember(mod)

    def _remember(self, mod: types.ModuleType) -> None:
        for key, value in list(vars(mod).items()):
            if getattr(value, "__module__", None) != mod.__name__:
                continue
            refs = self.old_objects.setdefault((mod.__name__, key), [])
            try:
                ref = weakref.ref(value)
            except TypeError:
                continue
            if not any(r() is value for r in refs):
                refs.append(ref)

    def check(self, force: bool = False) -> tuple[list[str], list[tuple[str, str]]]:
        """Reload modules whose source changed. Returns (reloaded, [(module, error)])."""
        reloaded: list[str] = []
        errors: list[tuple[str, str]] = []
        if not self.enabled and not force:
            return reloaded, errors
        for name, mod, file in self._candidates():
            try:
                mtime = os.path.getmtime(file)
            except OSError:
                continue
            old = self.mtimes.get(name)
            if old is None:
                self.mtimes[name] = mtime
                self._remember(mod)
                continue
            if mtime <= old and not force:
                continue
            if self.failed.get(name) == mtime:
                continue
            self.mtimes[name] = mtime
            try:
                self.superreload(mod)
                self.failed.pop(name, None)
                reloaded.append(name)
            except Exception as e:
                self.failed[name] = mtime
                errors.append((name, f"{type(e).__name__}: {e}"))
        return reloaded, errors

    def superreload(self, module: types.ModuleType) -> types.ModuleType:
        self._remember(module)
        saved = dict(vars(module))
        keep = {k: saved[k] for k in ("__name__", "__file__", "__loader__", "__spec__", "__path__", "__package__") if k in saved}
        vars(module).clear()
        vars(module).update(keep)
        try:
            module = importlib.reload(module)
        except BaseException:
            vars(module).clear()
            vars(module).update(saved)
            raise
        for key, new_obj in list(vars(module).items()):
            refs = self.old_objects.get((module.__name__, key), [])
            alive = []
            for ref in refs:
                old_obj = ref()
                if old_obj is None:
                    continue
                alive.append(ref)
                if old_obj is not new_obj:
                    update_generic(old_obj, new_obj)
            self.old_objects[(module.__name__, key)] = alive
        self._remember(module)
        gc.collect()
        return module

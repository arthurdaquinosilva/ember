"""Small shared helpers: IPython-compatible Struct/SList, argument splitting, `$var` expansion."""

from __future__ import annotations

import builtins
import inspect
import re
import shlex
from typing import Any, Iterable


class Struct(dict):
    """A dict with attribute access (IPython's `ipstruct.Struct`)."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def __delattr__(self, key: str) -> None:
        try:
            del self[key]
        except KeyError:
            raise AttributeError(key) from None

    def merge(self, __loc_data__: dict | None = None, __conflict_solve: Any = None, **kw: Any) -> None:
        """Add keys that aren't present yet; existing keys win (IPython's default policy)."""
        data = dict(__loc_data__ or {}, **kw)
        for key, value in data.items():
            if key not in self:
                self[key] = value

    def copy(self) -> Struct:
        return Struct(self)


class SList(list):
    """A list of output lines with IPython's conveniences (`.s`, `.n`, `.grep()`, `.fields()`)."""

    @property
    def l(self) -> list[str]:  # noqa: E743
        return list(self)

    @property
    def s(self) -> str:
        return " ".join(self)

    @property
    def n(self) -> str:
        return "\n".join(self)

    @property
    def p(self) -> list:
        from pathlib import Path

        return [Path(x) for x in self if Path(x).exists()]

    def grep(self, pattern: Any, prune: bool = False, field: int | None = None) -> SList:
        if isinstance(pattern, str):
            regex = re.compile(pattern, re.IGNORECASE)
            pred = lambda s: regex.search(s) is not None  # noqa: E731
        else:
            pred = pattern

        def matches(line: str) -> bool:
            target = line
            if field is not None:
                parts = line.split()
                if len(parts) <= field:
                    return False
                target = parts[field]
            return bool(pred(target))

        return SList(x for x in self if matches(x) != prune)

    def fields(self, *idx: int) -> SList:
        out = SList()
        for line in self:
            parts = line.split()
            if not idx:
                out.append(parts)
                continue
            picked = [parts[i] for i in idx if -len(parts) <= i < len(parts)]
            if picked:
                out.append(" ".join(picked))
        return out

    def sort(self, field: int | None = None, nums: bool = False) -> SList:  # type: ignore[override]
        def key(line: str):
            value = line if field is None else " ".join(line.split()[field:field + 1])
            if nums:
                digits = re.sub(r"[^\d.-]", "", value)
                try:
                    return float(digits)
                except ValueError:
                    return 0.0
            return value

        return SList(sorted(self, key=key))

    def __repr__(self) -> str:
        return f"SList({list.__repr__(self)})"


def arg_split(s: str, posix: bool = False, strict: bool = True) -> list[str]:
    """Split a command line like a shell would (IPython's `arg_split`)."""
    lex = shlex.shlex(s, posix=posix)
    lex.whitespace_split = True
    lex.commenters = ""
    tokens: list[str] = []
    while True:
        try:
            tok = next(lex)
        except StopIteration:
            break
        except ValueError:
            if strict:
                raise
            tokens.append(lex.token)
            break
        tokens.append(tok)
    return tokens


def resolve_name(expr: str, ns: dict[str, Any]) -> Any:
    """Resolve a dotted name statically (no properties or `__getattr__` are triggered).

    Raises LookupError when it can't be resolved."""
    head, *rest = expr.split(".")
    if head in ns:
        obj = ns[head]
    elif hasattr(builtins, head):
        obj = getattr(builtins, head)
    else:
        raise LookupError(expr)
    for attr in rest:
        try:
            obj = inspect.getattr_static(obj, attr)
        except AttributeError:
            raise LookupError(expr) from None
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
    return obj


_DOLLAR = re.compile(r"\$(\$|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
_BRACES = re.compile(r"(?<!\{)\{([^{}]+)\}(?!\})")


def expand_vars(text: str, ns: dict[str, Any]) -> str:
    """Expand `$name`, `$name.attr` and `{expression}` from the user namespace.

    `$$` is a literal `$`. Unknown `$NAMES` are left alone so shell variables like
    `$HOME` still reach the shell; `$` inside single quotes is never expanded;
    `{{`/`}}` escape braces."""

    def dollar(m: re.Match) -> str:
        token = m.group(1)
        if token == "$":
            return "$"
        prefix = text[: m.start()]
        if prefix.count("'") % 2 == 1:
            return m.group(0)
        root = token.split(".")[0]
        if root not in ns:
            return m.group(0)
        try:
            return str(eval(token, ns))
        except Exception:
            return m.group(0)

    def brace(m: re.Match) -> str:
        try:
            return str(eval(m.group(1), ns))
        except Exception:
            return m.group(0)

    text = _DOLLAR.sub(dollar, text)
    text = _BRACES.sub(brace, text)
    return text.replace("{{", "{").replace("}}", "}")


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def unique_everseen(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

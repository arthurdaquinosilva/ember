"""Typed call signatures: merge jedi's stub knowledge with the live object and inference."""

from __future__ import annotations

import builtins
import inspect
import re
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.utils import get_cwidth

_CALLEE = re.compile(r"([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*)\s*$")
_EMPTY = inspect.Parameter.empty


@dataclass
class Param:
    name: str
    stars: str = ""
    annotation: str | None = None
    inferred: bool = False  # annotation came from inference, not a declaration
    default: str | None = None


@dataclass
class SigInfo:
    name: str
    params: list[Param] = field(default_factory=list)
    index: int | None = None
    returns: str | None = None
    returns_inferred: bool = False


# ── parsing jedi's "name: ann=default" strings ─────────────────────────────


def split_param(text: str) -> Param:
    """Split `*name: annotation=default` at top level (ignoring brackets and quotes)."""
    stars = text[: len(text) - len(text.lstrip("*"))]
    body = text[len(stars):]
    colon = equals = -1
    depth = 0
    quote: str | None = None
    for i, ch in enumerate(body):
        if quote:
            if ch == quote and body[i - 1] != "\\":
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == ":" and colon < 0 and equals < 0:
            colon = i
        elif depth == 0 and ch == "=" and equals < 0:
            equals = i
    name_end = colon if colon >= 0 else (equals if equals >= 0 else len(body))
    param = Param(name=body[:name_end].strip(), stars=stars)
    if colon >= 0:
        param.annotation = _unquote(body[colon + 1 : equals if equals >= 0 else len(body)].strip() or None)
    if equals >= 0:
        param.default = body[equals + 1 :].strip()
    return param


def _returns_from_string(sig_text: str) -> str | None:
    """Pull the `-> X` off a jedi signature string, matching the params' closing paren."""
    depth = 0
    quote: str | None = None
    for i, ch in enumerate(sig_text):
        if quote:
            if ch == quote and sig_text[i - 1] != "\\":
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                rest = sig_text[i + 1 :].strip()
                return _unquote(rest[2:].strip() or None) if rest.startswith("->") else None
    return None


def _unquote(annotation: str | None) -> str | None:
    """`'list[float]'` → `list[float]` (jedi quotes annotations of live objects)."""
    if annotation and len(annotation) >= 2 and annotation[0] == annotation[-1] and annotation[0] in "'\"":
        return annotation[1:-1]
    return annotation


# ── live objects ───────────────────────────────────────────────────────────


def format_annotation(ann: Any) -> str:
    if isinstance(ann, str):
        return _unquote(ann) or ann
    if ann is None or ann is type(None):
        return "None"
    if isinstance(ann, type):
        return ann.__qualname__
    return inspect.formatannotation(ann).replace("typing.", "").replace("collections.abc.", "")


def type_name(value: Any) -> str:
    return "None" if value is None else type(value).__name__


def resolve_callee(text_before_bracket: str, ns: dict[str, Any]) -> Any:
    """Resolve a dotted name like `os.path.join` without calling anything."""
    m = _CALLEE.search(text_before_bracket)
    if not m:
        return None
    head, *rest = m.group(1).split(".")
    if head in ns:
        obj = ns[head]
    elif hasattr(builtins, head):
        obj = getattr(builtins, head)
    else:
        return None
    for attr in rest:
        try:
            obj = inspect.getattr_static(obj, attr)
        except AttributeError:
            return None
        if isinstance(obj, (staticmethod, classmethod)):
            obj = obj.__func__
    return obj


def _live_signature(obj: Any) -> inspect.Signature | None:
    if obj is None or not callable(obj):
        return None
    try:
        return inspect.signature(obj)
    except (TypeError, ValueError):
        return None


# ── building ───────────────────────────────────────────────────────────────


def _clean_inferred(names: list[str]) -> str | None:
    seen: list[str] = []
    for n in names:
        n = "None" if n == "NoneType" else n
        if n not in seen:
            seen.append(n)
    return " | ".join(seen) if seen else None


def build(jedi_sig: Any, text: str, ns: dict[str, Any]) -> SigInfo:
    line_no, col = jedi_sig.bracket_start
    line = text.split("\n")[line_no - 1][:col]
    live = _live_signature(resolve_callee(line, ns))
    live_params = dict(live.parameters) if live else {}

    info = SigInfo(name=jedi_sig.name, index=jedi_sig.index)
    for jp in jedi_sig.params:
        p = split_param(jp.to_string())
        lp = live_params.get(p.name)
        if p.annotation is None and lp is not None and lp.annotation is not _EMPTY:
            p.annotation = format_annotation(lp.annotation)
        if p.default is None and lp is not None and lp.default is not _EMPTY:
            p.default = repr(lp.default)
        if p.annotation is None and p.default is not None:
            if lp is not None and lp.default is not _EMPTY:
                p.annotation = type_name(lp.default)
            else:
                try:
                    p.annotation = _clean_inferred([n.name for n in jp.infer()])
                except Exception:
                    pass
            p.inferred = p.annotation is not None
        info.params.append(p)

    info.returns = _returns_from_string(jedi_sig.to_string())
    if info.returns is None and live is not None and live.return_annotation is not _EMPTY:
        info.returns = format_annotation(live.return_annotation)
    if info.returns is None:
        try:
            info.returns = _clean_inferred([n.name for n in jedi_sig.execute()])
            info.returns_inferred = info.returns is not None
        except Exception:
            pass
    return info


# ── rendering ──────────────────────────────────────────────────────────────


def _param_fragments(p: Param, current: bool, show_default: bool) -> StyleAndTextTuples:
    name_style = "class:sig.param.current" if current else "class:sig.param"
    out: StyleAndTextTuples = [(name_style, p.stars + p.name)]
    if p.annotation:
        type_style = "class:sig.type.inferred" if p.inferred else "class:sig.type"
        out += [("class:sig.punct", ": "), (type_style, p.annotation)]
    if show_default and p.default is not None:
        eq = " = " if p.annotation else "="
        out += [("class:sig.punct", eq), ("class:sig.default", p.default)]
    return out


def render(info: SigInfo, width: int) -> StyleAndTextTuples:
    """Render as wide as fits: full → no defaults → params windowed around the cursor."""
    n = len(info.params)
    current = info.index if info.index is not None and info.index < n else None

    def attempt(show_defaults: bool, window: int | None) -> StyleAndTextTuples:
        out: StyleAndTextTuples = [("class:sig.icon", "ƒ "), ("class:sig.name", info.name), ("class:sig.punct", "(")]
        visible = range(n)
        if window is not None:
            center = current if current is not None else 0
            visible = range(max(0, center - window), min(n, center + window + 1))
        if window is not None and visible.start > 0:
            out.append(("class:sig.punct", "…, "))
        for k, i in enumerate(visible):
            if k:
                out.append(("class:sig.punct", ", "))
            out += _param_fragments(info.params[i], i == current, show_defaults)
        if window is not None and visible.stop < n:
            out.append(("class:sig.punct", ", …"))
        out.append(("class:sig.punct", ")"))
        if info.returns:
            ret_style = "class:sig.type.inferred" if info.returns_inferred else "class:sig.return"
            out += [("class:sig.punct", " -> "), (ret_style, info.returns)]
        return out

    for show_defaults, window in ((True, None), (False, None), (False, 2), (False, 1), (False, 0)):
        frags = attempt(show_defaults, window)
        if sum(get_cwidth(t) for _, t, *_ in frags) <= width:
            return frags
    return frags

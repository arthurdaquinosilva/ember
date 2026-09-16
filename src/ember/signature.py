"""Typed call signatures: merge jedi's stub knowledge with the live object and inference."""

from __future__ import annotations

import ast
import builtins
import inspect
import re
import textwrap
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
    kind: str = "POSITIONAL_OR_KEYWORD"
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


# ── inference from the call site and the function body ─────────────────────

_CONTAINER_NODES = {
    ast.List: "list", ast.ListComp: "list", ast.Dict: "dict", ast.DictComp: "dict",
    ast.Set: "set", ast.SetComp: "set", ast.Tuple: "tuple", ast.JoinedStr: "str",
    ast.GeneratorExp: "Generator", ast.Lambda: "Callable",
}


def expr_type(
    node: ast.expr,
    source: str,
    ns: dict[str, Any],
    local_types: dict[str, str] | None = None,
    use_jedi: bool = True,
) -> str | None:
    """Best-effort type of an expression, without evaluating anything with side effects.

    `local_types` holds known types of names inside a function body (its parameters);
    jedi is only useful at the call site, where names refer to the live namespace."""
    local_types = local_types or {}
    if isinstance(node, ast.Constant):
        return type_name(node.value)
    for node_type, name in _CONTAINER_NODES.items():
        if isinstance(node, node_type):
            return name
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        return type_name(node.operand.value)
    if isinstance(node, ast.Name):
        if node.id in local_types:
            return local_types[node.id]
        if node.id in ns:
            return type_name(ns[node.id])
        if isinstance(getattr(builtins, node.id, None), type):
            return "type"
    if isinstance(node, ast.BinOp):
        left = expr_type(node.left, source, ns, local_types, use_jedi)
        right = expr_type(node.right, source, ns, local_types, use_jedi)
        sequences = ("str", "list", "tuple", "bytes")
        if isinstance(node.op, ast.Mult) and "int" in (left, right) and (left in sequences or right in sequences):
            return left if left in sequences else right
        if left and left == right:
            return "float" if isinstance(node.op, ast.Div) and left == "int" else left
        if {left, right} == {"int", "float"}:
            return "float"
        return None
    if isinstance(node, ast.Compare) or (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)):
        return "bool"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        target = ns.get(node.func.id, getattr(builtins, node.func.id, None))
        if isinstance(target, type):
            return target.__name__
    segment = ast.get_source_segment(source, node)
    if not use_jedi or not segment or "\n" in segment:
        return None
    try:
        import jedi

        names = jedi.Interpreter(segment, [ns]).infer(1, len(segment))
        return _clean_inferred([n.name for n in names if n.type in ("instance", "class")])
    except Exception:
        return None


def _call_arguments(text: str, bracket: tuple[int, int]) -> str:
    """The raw argument text of the call whose `(` is at `bracket` (1-based line)."""
    lines = text.split("\n")
    offset = sum(len(ln) + 1 for ln in lines[: bracket[0] - 1]) + bracket[1] + 1
    depth = 1
    quote: str | None = None
    for i in range(offset, len(text)):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[offset:i]
    return text[offset:]


def _parse_call(args: str) -> ast.Call | None:
    """Parse possibly-unfinished argument text, dropping a trailing partial argument if needed."""
    candidates = [args, args.rstrip().rstrip(",")]
    if "," in args:
        candidates.append(args[: args.rfind(",")])
    for candidate in candidates:
        try:
            tree = ast.parse(f"_({candidate})", mode="eval")
        except SyntaxError:
            continue
        if isinstance(tree.body, ast.Call):
            return tree.body
    return None


def infer_argument_types(params: list[Param], text: str, bracket: tuple[int, int], ns: dict[str, Any]) -> dict[str, str]:
    """Map each parameter name to the type of the argument passed for it at this call site."""
    source = _call_arguments(text, bracket)
    call = _parse_call(source)
    if call is None:
        return {}
    wrapped = f"_({source})"
    found: dict[str, list[str]] = {}
    positional = [p for p in params if p.kind in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
    var_positional = next((p for p in params if p.kind == "VAR_POSITIONAL"), None)
    for i, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred):
            break
        target = positional[i] if i < len(positional) else var_positional
        if target and (t := expr_type(arg, wrapped, ns)):
            found.setdefault(target.name, []).append(t)
    names = {p.name for p in params}
    var_keyword = next((p for p in params if p.kind == "VAR_KEYWORD"), None)
    for kw in call.keywords:
        if kw.arg is None:
            continue
        target_name = kw.arg if kw.arg in names else (var_keyword.name if var_keyword else None)
        if target_name and (t := expr_type(kw.value, wrapped, ns)):
            found.setdefault(target_name, []).append(t)
    return {name: _clean_inferred(types) or "" for name, types in found.items()}


class _ReturnCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.returns: list[ast.expr | None] = []
        self.generator = False

    def visit_Return(self, node: ast.Return) -> None:
        self.returns.append(node.value)

    def visit_Yield(self, node: ast.AST) -> None:
        self.generator = True

    visit_YieldFrom = visit_Yield

    def _skip(self, node: ast.AST) -> None:
        pass  # nested scopes have their own returns

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = visit_ClassDef = _skip


def infer_return_type(obj: Any, ns: dict[str, Any]) -> str | None:
    """Infer a return type from a live function's source: `None` if it never returns a value."""
    func = getattr(obj, "__func__", obj)
    if inspect.isclass(func) or not inspect.isfunction(func):
        return None
    try:
        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        return None
    fn = tree.body[0] if tree.body else None
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    local_types: dict[str, str] = {}
    all_args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
    defaults = [None] * (len(fn.args.posonlyargs) + len(fn.args.args) - len(fn.args.defaults)) + list(fn.args.defaults)
    defaults += list(fn.args.kw_defaults)
    for arg, default in zip(all_args, defaults):
        if arg.annotation is not None:
            local_types[arg.arg] = ast.unparse(arg.annotation)
        elif isinstance(default, ast.Constant) and default.value is not None:
            local_types[arg.arg] = type_name(default.value)
    collector = _ReturnCollector()
    for stmt in fn.body:
        collector.visit(stmt)
    if collector.generator:
        return "AsyncGenerator" if isinstance(fn, ast.AsyncFunctionDef) else "Generator"
    values = [v for v in collector.returns if v is not None and not (isinstance(v, ast.Constant) and v.value is None)]
    has_none = len(values) < len(collector.returns) or not collector.returns
    types: list[str] = []
    for value in values:
        # Only literals, constructor calls and the function's own typed parameters are trusted.
        t = expr_type(value, source, {}, local_types, use_jedi=False)
        if t is None:
            return None
        types.append(t)
    if has_none:
        types.append("None")
    result = _clean_inferred(types)
    if result and isinstance(fn, ast.AsyncFunctionDef):
        result = f"Coroutine[{result}]"
    return result


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
    callee = resolve_callee(line, ns)
    live = _live_signature(callee)
    live_params = dict(live.parameters) if live else {}

    info = SigInfo(name=jedi_sig.name, index=jedi_sig.index)
    for jp in jedi_sig.params:
        p = split_param(jp.to_string())
        p.kind = jp.kind.name
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

    # Unannotated params: the argument actually being passed beats a guess from the default.
    if any(p.annotation is None or p.inferred for p in info.params):
        for name, t in infer_argument_types(info.params, text, jedi_sig.bracket_start, ns).items():
            p = next(p for p in info.params if p.name == name)
            if t and (p.annotation is None or p.inferred):
                p.annotation, p.inferred = t, True

    info.returns = _returns_from_string(jedi_sig.to_string())
    if info.returns is None and live is not None and live.return_annotation is not _EMPTY:
        info.returns = format_annotation(live.return_annotation)
    if info.returns is None:
        try:
            info.returns = _clean_inferred([n.name for n in jedi_sig.execute()])
        except Exception:
            pass
        if info.returns is None:
            info.returns = infer_return_type(callee, ns)
        info.returns_inferred = info.returns is not None
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

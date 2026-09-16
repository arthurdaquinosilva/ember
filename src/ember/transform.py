"""Source transforms: `%magic`, `%%cell magic`, `!shell`, `!!capture`, `obj?`, `a*b?`, automagic, pasted prompts."""

from __future__ import annotations

import ast
import codeop
import re
import textwrap
import warnings
from typing import Callable

API = "__ember__"

_ASSIGN = r"(?P<assign>[A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*\s*=\s*)?"
MAGIC_RE = re.compile(rf"^(?P<indent>[ \t]*){_ASSIGN}%(?P<name>\w+)(?P<args>.*)$")
CAPTURE_RE = re.compile(r"^(?P<indent>[ \t]*)!!(?P<cmd>.*)$")
SHELL_RE = re.compile(rf"^(?P<indent>[ \t]*){_ASSIGN}!(?P<cmd>.*)$")
HELP_RE = re.compile(r"^(?P<indent>[ \t]*)(?:(?P<pre>\?\??)(?P<obj1>[A-Za-z_][\w.]*)|(?P<obj2>[A-Za-z_][\w.]*)(?P<post>\?\??))\s*$")
WILDCARD_RE = re.compile(r"^(?P<indent>[ \t]*)\??(?P<pattern>[\w.]*[*][\w.*]*)\?\s*$")
CELL_MAGIC_RE = re.compile(r"^%%(?P<name>\w+)(?P<args>[^\n]*)(?:\n(?P<body>.*))?$", re.S)
AUTOMAGIC_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<name>[A-Za-z_]\w*)(?:(?P<sep>\s+)(?P<args>.*))?$")
# After `name `, these mean the line is Python (assignment, call, operator…), not a magic.
_PYTHONIC_REST = re.compile(r"^(?:[=(\[,:;@]|\.(?=[A-Za-z_])|[-+*/%&|^<>!]=|\*\*|//|>>|<<|(?:is|in|and|or|if|else|for|not|as)\b)")

_compiler = codeop.CommandCompiler()
_compiler.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

# ── pasted prompts ─────────────────────────────────────────────────────────

_CLASSIC_START = re.compile(r"^>>>( |$)")
_CLASSIC_LINE = re.compile(r"^(>>>|\.\.\.)( |$)")
_IPY_START = re.compile(r"^In \[\d+\]: ")
_IPY_LINE = re.compile(r"^(In \[\d+\]: |\s*\.\.\.: ?)")


def strip_prompts(text: str) -> str:
    """Remove `>>> `/`... ` or `In [1]: `/`   ...: ` prompts from pasted code, dropping output lines."""
    lines = textwrap.dedent(text.replace("\r\n", "\n")).split("\n")
    first = next((ln for ln in lines if ln.strip()), "")
    for start, line_re in ((_CLASSIC_START, _CLASSIC_LINE), (_IPY_START, _IPY_LINE)):
        if start.match(first):
            kept = []
            for ln in lines:
                if m := line_re.match(ln):
                    kept.append(ln[m.end():])
            while kept and not kept[-1].strip():
                kept.pop()
            return "\n".join(kept)
    return text


def has_prompts(text: str) -> bool:
    first = next((ln for ln in textwrap.dedent(text).split("\n") if ln.strip()), "")
    return bool(_CLASSIC_START.match(first) or _IPY_START.match(first))


# ── line transforms ────────────────────────────────────────────────────────


def _in_triple_string(prefix: str) -> bool:
    return (prefix.count('"""') % 2 == 1) or (prefix.count("'''") % 2 == 1)


def transform_line(line: str, automagic: Callable[[str], bool] | None = None) -> str:
    if m := MAGIC_RE.match(line):
        assign = m["assign"] or ""
        return f"{m['indent']}{assign}{API}.magic({m['name']!r}, {m['args'].strip()!r})"
    if m := CAPTURE_RE.match(line):
        return f"{m['indent']}{API}.shell({m['cmd'].strip()!r}, capture=True)"
    if m := SHELL_RE.match(line):
        assign = m["assign"] or ""
        cmd = m["cmd"].lstrip("!") if assign else m["cmd"]  # `x = !!cmd` means the same as `x = !cmd`
        return f"{m['indent']}{assign}{API}.shell({cmd.strip()!r}, capture={bool(assign)})"
    if m := WILDCARD_RE.match(line):
        return f"{m['indent']}{API}.psearch({m['pattern']!r})"
    if m := HELP_RE.match(line):
        obj = m["obj1"] or m["obj2"]
        level = len(m["pre"] or m["post"])
        return f"{m['indent']}{API}.inspect({obj!r}, {level})"
    if automagic is not None and (m := AUTOMAGIC_RE.match(line)) and not m["indent"]:
        args = m["args"] or ""
        if automagic(m["name"]) and not _PYTHONIC_REST.match(args):
            return f"{API}.magic({m['name']!r}, {args.strip()!r})"
    return line


def transform(source: str, automagic: Callable[[str], bool] | None = None) -> str:
    """Rewrite shell syntax into Python, preserving the line count where possible.

    `automagic(name)` decides whether a bare `name args` line calls a magic; it only
    applies to single-line cells so ordinary code is never reinterpreted."""
    if m := CELL_MAGIC_RE.match(source):
        body = m["body"] or ""
        if body and not body.endswith("\n"):
            body += "\n"  # IPython passes the cell body with its trailing newline
        return f"{API}.cell_magic({m['name']!r}, {m['args'].strip()!r}, {body!r})"
    lines = source.split("\n")
    single = len([ln for ln in lines if ln.strip()]) == 1
    out: list[str] = []
    seen = ""
    for line in lines:
        if _in_triple_string(seen):
            out.append(line)
        else:
            out.append(transform_line(line, automagic if single else None))
        seen += line + "\n"
    return "\n".join(out)


def is_special(source: str) -> bool:
    s = source.strip()
    return bool(s) and "\n" not in s and (s[0] in "%!?" or transform_line(s) != s)


def is_complete(source: str) -> bool:
    """Should pressing Enter execute this source (True) or insert a newline (False)?"""
    if not source.strip():
        return True
    lines = source.split("\n")
    if source.startswith("%%"):
        return len(lines) > 1 and not lines[-1].strip()
    if has_prompts(source):
        return True
    if len(lines) == 1 and is_special(source):
        return not source.rstrip().endswith("\\")
    # A blank last line after a multi-line block always submits.
    if len(lines) > 1 and not lines[-1].strip():
        return True
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            code = _compiler(transform(source), "<input>", "exec")
    except (SyntaxError, OverflowError, ValueError):
        return True  # let the error surface
    if code is None:
        return False
    # Still inside an indented block: keep going until a blank line.
    if len(lines) > 1 and lines[-1][:1] in (" ", "\t"):
        return False
    return True


_DEDENT_RE = re.compile(r"^\s*(return|pass|break|continue|raise)\b")


def next_indent(line: str, indent_width: int = 4) -> str:
    indent = len(line) - len(line.lstrip(" "))
    stripped = line.rstrip()
    if stripped.endswith((":", "(", "[", "{")) and not stripped.lstrip().startswith("#"):
        indent += indent_width
    elif _DEDENT_RE.match(line):
        indent = max(0, indent - indent_width)
    return " " * indent

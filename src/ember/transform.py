"""Source transforms: `%magic`, `%%cell magic`, `!shell`, `obj?` → plain Python."""

from __future__ import annotations

import ast
import codeop
import re
import warnings

API = "__ember__"

_ASSIGN = r"(?P<assign>[A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*\s*=\s*)?"
MAGIC_RE = re.compile(rf"^(?P<indent>[ \t]*){_ASSIGN}%(?P<name>\w+)(?P<args>.*)$")
SHELL_RE = re.compile(rf"^(?P<indent>[ \t]*){_ASSIGN}!(?P<cmd>.*)$")
HELP_RE = re.compile(r"^(?P<indent>[ \t]*)(?:(?P<pre>\?\??)(?P<obj1>[A-Za-z_][\w.]*)|(?P<obj2>[A-Za-z_][\w.]*)(?P<post>\?\??))\s*$")
CELL_MAGIC_RE = re.compile(r"^%%(?P<name>\w+)(?P<args>[^\n]*)(?:\n(?P<body>.*))?$", re.S)

_compiler = codeop.CommandCompiler()
_compiler.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT


def _in_triple_string(prefix: str) -> bool:
    return (prefix.count('"""') % 2 == 1) or (prefix.count("'''") % 2 == 1)


def transform_line(line: str) -> str:
    if m := MAGIC_RE.match(line):
        assign = m["assign"] or ""
        return f"{m['indent']}{assign}{API}.magic({m['name']!r}, {m['args'].strip()!r})"
    if m := SHELL_RE.match(line):
        assign = m["assign"] or ""
        return f"{m['indent']}{assign}{API}.shell({m['cmd'].strip()!r}, capture={bool(assign)})"
    if m := HELP_RE.match(line):
        obj = m["obj1"] or m["obj2"]
        level = len(m["pre"] or m["post"])
        return f"{m['indent']}{API}.inspect({obj!r}, {level})"
    return line


def transform(source: str) -> str:
    """Rewrite shell syntax into Python, preserving the line count where possible."""
    if m := CELL_MAGIC_RE.match(source):
        return f"{API}.cell_magic({m['name']!r}, {m['args'].strip()!r}, {(m['body'] or '')!r})"
    out: list[str] = []
    seen = ""
    for line in source.split("\n"):
        out.append(line if _in_triple_string(seen) else transform_line(line))
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
    if len(lines) > 1 and re.match(r"\s*(def|class|if|for|while|with|try|async|match)\b", lines[0]):
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

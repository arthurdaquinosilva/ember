"""Color palettes shared by the prompt (prompt_toolkit), output (rich) and syntax (pygments)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.styles import merge_styles, style_from_pygments_cls
from pygments.style import Style as PygmentsStyle
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    Token,
)
from rich.syntax import PygmentsSyntaxTheme
from rich.theme import Theme as RichTheme


@dataclass(frozen=True)
class Palette:
    name: str
    fg: str
    muted: str
    faint: str
    border: str
    surface: str
    selection: str
    bar: str  # filled input bar
    label: str  # key-bar labels and banner values
    accent: str
    accent2: str
    ok: str
    err: str
    warn: str
    info: str
    # syntax
    keyword: str
    builtin: str
    function: str
    klass: str
    string: str
    number: str
    comment: str
    operator: str
    decorator: str


PALETTES: dict[str, Palette] = {
    # Near-black monochrome with a single warm accent.
    "void": Palette(
        name="void",
        fg="#e7e7e7",
        muted="#8b8b8b",
        faint="#555555",
        border="#3b3b3b",
        surface="#161616",
        selection="#2b2b2b",
        bar="#24262b",
        label="#86c7c0",
        accent="#ff8a4c",
        accent2="#ffc46b",
        ok="#7ee2a8",
        err="#ff6b6b",
        warn="#f2c14e",
        info="#7cc4ff",
        keyword="#ff9e6b",
        builtin="#7cc4ff",
        function="#e7e7e7",
        klass="#ffd08a",
        string="#a8d8a0",
        number="#f5a97f",
        comment="#5f5f5f",
        operator="#9a9a9a",
        decorator="#c9a0ff",
    ),
    "nebula": Palette(
        name="nebula",
        fg="#e4e1f5",
        muted="#8c87a8",
        faint="#56516e",
        border="#3a3552",
        surface="#15131f",
        selection="#2a2640",
        bar="#262238",
        label="#6ee7f9",
        accent="#b18cff",
        accent2="#6ee7f9",
        ok="#6ee7b7",
        err="#fb7185",
        warn="#fcd34d",
        info="#6ee7f9",
        keyword="#c4a5ff",
        builtin="#6ee7f9",
        function="#f0ecff",
        klass="#f9a8d4",
        string="#86efac",
        number="#fda4af",
        comment="#5c5776",
        operator="#a39fc0",
        decorator="#f9a8d4",
    ),
    "matrix": Palette(
        name="matrix",
        fg="#d7f5dd",
        muted="#7a9a80",
        faint="#46604b",
        border="#2e4533",
        surface="#0f1a12",
        selection="#1f3324",
        bar="#18261c",
        label="#5eead4",
        accent="#4ade80",
        accent2="#a3e635",
        ok="#4ade80",
        err="#f87171",
        warn="#facc15",
        info="#5eead4",
        keyword="#4ade80",
        builtin="#5eead4",
        function="#ecfdf0",
        klass="#a3e635",
        string="#bef264",
        number="#fde68a",
        comment="#4b6b52",
        operator="#8fb396",
        decorator="#5eead4",
    ),
}

DEFAULT_THEME = "void"


class Theme:
    def __init__(self, palette: Palette):
        self.p = palette

    @property
    def name(self) -> str:
        return self.p.name

    @cached_property
    def pygments_style(self) -> type[PygmentsStyle]:
        p = self.p
        return type(
            f"Ember{p.name.title()}Style",
            (PygmentsStyle,),
            {
                "background_color": None,
                "highlight_color": p.selection,
                "styles": {
                    Token: p.fg,
                    Text: p.fg,
                    Comment: f"italic {p.comment}",
                    Keyword: p.keyword,
                    Keyword.Constant: p.number,
                    Keyword.Namespace: p.keyword,
                    Operator: p.operator,
                    Operator.Word: p.keyword,
                    Punctuation: p.operator,
                    Name: p.fg,
                    Name.Builtin: p.builtin,
                    Name.Builtin.Pseudo: f"italic {p.builtin}",
                    Name.Function: p.function,
                    Name.Function.Magic: p.builtin,
                    Name.Class: f"bold {p.klass}",
                    Name.Decorator: p.decorator,
                    Name.Exception: p.klass,
                    Name.Namespace: p.klass,
                    Name.Variable.Magic: p.builtin,
                    String: p.string,
                    String.Doc: f"italic {p.comment}",
                    String.Escape: p.number,
                    String.Interpol: p.accent2,
                    String.Affix: p.keyword,
                    Number: p.number,
                    Generic.Deleted: p.err,
                    Generic.Inserted: p.ok,
                    Generic.Heading: f"bold {p.fg}",
                    Generic.Subheading: p.muted,
                    Generic.Error: p.err,
                    Generic.Traceback: p.err,
                    Error: p.err,
                },
            },
        )

    @cached_property
    def syntax_theme(self) -> PygmentsSyntaxTheme:
        return PygmentsSyntaxTheme(self.pygments_style)

    @cached_property
    def pt_style(self) -> PTStyle:
        p = self.p
        ui = PTStyle.from_dict(
            {
                "": p.fg,
                "bar": f"bg:{p.bar}",
                "bar.prompt": f"bg:{p.bar} bold {p.accent}",
                "bar.cont": f"bg:{p.bar} {p.faint}",
                "bar.count": f"bg:{p.bar} {p.faint}",
                "placeholder": p.faint,
                "keybar.label": f"bold {p.label}",
                "keybar.key": p.fg,
                "keybar.sep": p.faint,
                "modeline.mode": f"bold {p.label}",
                "box.border": p.border,
                "box.border.active": p.faint,
                "box.title": f"bold {p.accent}",
                "box.label": p.faint,
                "prompt": f"bold {p.accent}",
                "prompt.cont": p.faint,
                "status": p.muted,
                "status.dim": p.faint,
                "status.accent": p.accent,
                "status.ok": p.ok,
                "status.err": p.err,
                "status.warn": p.warn,
                "status.key": f"{p.fg}",
                "status.sep": p.faint,
                "sig.icon": p.accent,
                "sig.name": f"bold {p.builtin}",
                "sig.param": p.muted,
                "sig.param.current": f"bold underline {p.accent}",
                "sig.type": p.klass,
                "sig.type.inferred": f"italic {p.muted}",
                "sig.return": f"bold {p.klass}",
                "sig.default": p.faint,
                "sig.punct": p.faint,
                "auto-suggestion": p.faint,
                "matching-bracket.cursor": f"bg:{p.selection} bold",
                "matching-bracket.other": f"bg:{p.selection} bold",
                "selected": f"bg:{p.selection}",
                "completion-menu": f"bg:{p.surface} {p.fg}",
                "completion-menu.completion": f"bg:{p.surface} {p.fg}",
                "completion-menu.completion.current": f"bg:{p.selection} bold {p.accent}",
                "completion-menu.meta.completion": f"bg:{p.surface} {p.faint}",
                "completion-menu.meta.completion.current": f"bg:{p.selection} {p.muted}",
                "completion-menu.multi-column-meta": f"bg:{p.surface} {p.muted}",
                "comp.icon": p.faint,
                "comp.icon.function": p.builtin,
                "comp.icon.class": p.klass,
                "comp.icon.module": p.decorator,
                "comp.icon.keyword": p.keyword,
                "comp.icon.instance": p.string,
                "comp.icon.magic": p.accent,
                "comp.icon.path": p.accent2,
                "scrollbar.background": f"bg:{p.surface}",
                "scrollbar.button": f"bg:{p.border}",
                "search": f"bg:{p.selection}",
                "search.current": f"bg:{p.accent} #000000",
                "search-toolbar": p.muted,
                "search-toolbar.prompt": f"bold {p.accent}",
                "search-toolbar.text": p.fg,
            }
        )
        return merge_styles([style_from_pygments_cls(self.pygments_style), ui])

    @cached_property
    def rich_theme(self) -> RichTheme:
        p = self.p
        return RichTheme(
            {
                "ember.fg": p.fg,
                "ember.muted": p.muted,
                "ember.faint": p.faint,
                "ember.border": p.border,
                "ember.accent": p.accent,
                "ember.accent2": p.accent2,
                "ember.ok": p.ok,
                "ember.err": p.err,
                "ember.warn": p.warn,
                "ember.info": p.info,
                "ember.label": f"bold {p.label}",
                "ember.accent.bold": f"bold {p.accent}",
                "ember.accent.blink": f"bold blink {p.accent}",
                "ember.err.bold": f"bold {p.err}",
                "ember.fg.bold": f"bold {p.fg}",
                "ember.info.bold": f"bold {p.info}",
                "ember.keyword": p.keyword,
                "ember.class": p.klass,
                "ember.string": p.string,
                "repr.number": p.number,
                "repr.number_complex": p.number,
                "repr.str": p.string,
                "repr.bool_true": f"italic {p.ok}",
                "repr.bool_false": f"italic {p.err}",
                "repr.none": f"italic {p.muted}",
                "repr.ellipsis": p.faint,
                "repr.brace": p.operator,
                "repr.comma": p.faint,
                "repr.call": p.builtin,
                "repr.attrib_name": p.klass,
                "repr.attrib_equal": p.faint,
                "repr.attrib_value": p.fg,
                "repr.tag_name": p.klass,
                "repr.tag_start": p.faint,
                "repr.tag_end": p.faint,
                "repr.tag_contents": p.fg,
                "repr.url": f"underline {p.info}",
                "repr.path": p.decorator,
                "repr.filename": p.accent2,
                "repr.uuid": p.accent2,
                "repr.ipv4": p.info,
                "repr.ipv6": p.info,
                "repr.eui48": p.info,
                "repr.eui64": p.info,
                "repr.indent": p.border,
                "pretty.indent": p.border,
                "traceback.border": p.err,
                "traceback.border.syntax_error": p.err,
                "traceback.title": f"bold {p.err}",
                "traceback.exc_type": f"bold {p.err}",
                "traceback.exc_value": p.fg,
                "traceback.offset": f"bold {p.err}",
                "traceback.error": f"bold {p.err}",
                "traceback.error_range": f"underline {p.err}",
                "traceback.note": p.warn,
                "traceback.group.border": p.warn,
                "table.header": f"bold {p.accent}",
                "table.footer": p.muted,
                "table.caption": f"italic {p.muted}",
                "rule.line": p.border,
            }
        )


def get_theme(name: str | None) -> Theme:
    return Theme(PALETTES.get(name or DEFAULT_THEME, PALETTES[DEFAULT_THEME]))

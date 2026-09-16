"""`display()` and the IPython.display object zoo, rendered for a terminal."""

from __future__ import annotations

import html
import json as _json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.json import JSON as RichJSON
from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.text import Text


def _active_shell():
    from ember.shell import Shell

    return Shell.active


def html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style).*?</\1>", "", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h\d|li)>", "\n", markup)
    markup = re.sub(r"(?i)</t[dh]>", "  ", markup)
    markup = re.sub(r"<[^>]+>", "", markup)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in html.unescape(markup).splitlines()]
    return "\n".join(ln for ln in lines if ln)


class DisplayObject:
    """Base for rich-displayable data loaded from `data`, a `filename` or a `url`."""

    kind = "data"

    def __init__(self, data: Any = None, url: str | None = None, filename: str | None = None, metadata: dict | None = None):
        if url is None and filename is None:
            if isinstance(data, Path):
                filename, data = str(data), None
            elif isinstance(data, str) and data.startswith(("http://", "https://")):
                url, data = data, None
            elif isinstance(data, str) and len(data) < 1024 and "\n" not in data and os.path.isfile(data):
                filename, data = data, None
        self.data = data
        self.url = url
        self.filename = filename
        self.metadata = metadata or {}
        if filename is not None and data is None:
            self.reload()

    def reload(self) -> None:
        if self.filename:
            mode = "rb" if self.kind == "binary" else "r"
            with open(self.filename, mode) as f:
                self.data = f.read()

    def __repr__(self) -> str:
        return f"<{type(self).__module__.split('.')[0]}.{type(self).__name__} object>"


class TextDisplayObject(DisplayObject):
    def _source(self) -> str:
        if self.data is None and self.url:
            return f"({self.url})"
        return str(self.data or "")


class Pretty(TextDisplayObject):
    def __rich__(self) -> RenderableType:
        return Text(self._source())


class Markdown(TextDisplayObject):
    def _repr_markdown_(self) -> str:
        return self._source()

    def __rich__(self) -> RenderableType:
        return RichMarkdown(self._source())


class HTML(TextDisplayObject):
    def _repr_html_(self) -> str:
        return self._source()

    def __rich__(self) -> RenderableType:
        return Text(html_to_text(self._source()))


class Latex(TextDisplayObject):
    def _repr_latex_(self) -> str:
        return self._source()

    def __rich__(self) -> RenderableType:
        return Text(self._source(), style="ember.accent2")


class Math(Latex):
    def _repr_latex_(self) -> str:
        s = self._source().strip("$")
        return f"$\\displaystyle {s}$"


class JSON(DisplayObject):
    def __init__(self, data: Any = None, url: str | None = None, filename: str | None = None, expanded: bool = False,
                 metadata: dict | None = None, root: str = "root", **kwargs: Any):
        super().__init__(data, url, filename, metadata)
        if isinstance(self.data, str):
            try:
                self.data = _json.loads(self.data)
            except ValueError:
                pass

    def _repr_json_(self) -> Any:
        return self.data

    def __rich__(self) -> RenderableType:
        return RichJSON(_json.dumps(self.data, default=str))


class Code(TextDisplayObject):
    def __init__(self, data: Any = None, url: str | None = None, filename: str | None = None, language: str | None = None):
        self.language = language
        super().__init__(data, url, filename)

    def __rich__(self) -> RenderableType:
        from ember.shell import Shell

        lexer = self.language or (Syntax.guess_lexer(self.filename, self._source()) if self.filename else "python")
        theme = Shell.active.theme.syntax_theme if Shell.active else "ansi_dark"
        return Syntax(self._source(), lexer, theme=theme, background_color="default", line_numbers=True)


class Javascript(TextDisplayObject):
    def __rich__(self) -> RenderableType:
        return Text("⟨javascript — not runnable in a terminal⟩", style="ember.faint")


class _Placeholder(DisplayObject):
    kind = "binary"
    label = "media"

    def __init__(self, data: Any = None, url: str | None = None, filename: str | None = None, **kwargs: Any):
        self.options = kwargs
        super().__init__(data, url, filename)

    def __rich__(self) -> RenderableType:
        where = self.filename or self.url or (f"{len(self.data):,} bytes" if isinstance(self.data, (bytes, str)) else "")
        dims = " × ".join(str(self.options[k]) for k in ("width", "height") if self.options.get(k))
        bits = [b for b in (where, dims) if b]
        return Text.assemble(("▣ ", "ember.accent"), (self.label, "ember.fg"), ("  " + " · ".join(bits) if bits else "", "ember.faint"))


class Image(_Placeholder):
    label = "image"


class SVG(_Placeholder):
    label = "svg"


class Audio(_Placeholder):
    label = "audio"


class Video(_Placeholder):
    label = "video"


class IFrame(_Placeholder):
    label = "iframe"

    def __init__(self, src: str, width: Any = None, height: Any = None, **kwargs: Any):
        super().__init__(url=src, width=width, height=height, **kwargs)


class YouTubeVideo(IFrame):
    label = "youtube"

    def __init__(self, id: str, width: Any = 400, height: Any = 300, **kwargs: Any):
        super().__init__(f"https://www.youtube.com/watch?v={id}", width, height, **kwargs)


class FileLink:
    def __init__(self, path: str, url_prefix: str = "", result_html_prefix: str = "", result_html_suffix: str = ""):
        self.path = path

    def __rich__(self) -> RenderableType:
        full = os.path.abspath(self.path)
        return Text(self.path, style=f"link file://{full} underline ember.info")

    def __repr__(self) -> str:
        return os.path.abspath(self.path)


class FileLinks(FileLink):
    def __rich__(self) -> RenderableType:
        entries = sorted(Path(self.path).rglob("*")) if os.path.isdir(self.path) else []
        return Group(*(FileLink(str(p)).__rich__() for p in entries if p.is_file()))


class DisplayHandle:
    def __init__(self, display_id: str | None = None):
        self.display_id = display_id or uuid.uuid4().hex

    def display(self, obj: Any, **kwargs: Any) -> None:
        display(obj, **kwargs)

    def update(self, obj: Any, **kwargs: Any) -> None:
        display(obj, **kwargs)

    def __repr__(self) -> str:
        return f"<DisplayHandle display_id={self.display_id}>"


def display(*objs: Any, include: Any = None, exclude: Any = None, metadata: Any = None, transient: Any = None,
            display_id: Any = None, raw: bool = False, clear: bool = False, **kwargs: Any) -> DisplayHandle | None:
    shell = _active_shell()
    for obj in objs:
        if raw and isinstance(obj, dict):
            text = obj.get("text/markdown") or obj.get("text/plain") or ""
            renderable: RenderableType | None = RichMarkdown(text) if "text/markdown" in obj else Text(str(text))
        elif shell is not None:
            renderable = shell.render_display(obj)
        else:
            renderable = Text(repr(obj))
        if renderable is None:
            continue
        if shell is not None:
            shell.print(renderable)
        else:
            from rich import print as rprint

            rprint(renderable)
    if display_id:
        return DisplayHandle(None if display_id is True else str(display_id))
    return None


def update_display(obj: Any, *, display_id: str, **kwargs: Any) -> None:
    display(obj, **kwargs)


def clear_output(wait: bool = False) -> None:
    """No-op in a terminal (output above the prompt is history)."""


def publish_display_data(data: dict, metadata: dict | None = None, **kwargs: Any) -> None:
    display(data, raw=True)


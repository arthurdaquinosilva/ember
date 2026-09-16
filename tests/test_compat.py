"""IPython compatibility: get_ipython(), stand-in modules, events, display protocol, custom magics, extensions."""

import sys
import textwrap

from rich.markdown import Markdown
from rich.text import Text

from ember import display
from ember.magics import LINE_MAGICS
from tests.conftest import last_out


def test_get_ipython_available(shell):
    shell.run_cell("ip = get_ipython()")
    ip = shell.ns["ip"]
    assert ip is shell.ipy
    assert ip.user_ns is shell.ns


def test_stand_in_ipython_modules(shell):
    shell.run_cell("import IPython\nfrom IPython.display import display, Markdown\nfrom IPython.core.magic import register_line_magic")
    assert shell.last_ok
    assert sys.modules["IPython"].get_ipython() is shell.ipy


def test_register_line_magic_decorator(shell):
    shell.run_cell("from IPython.core.magic import register_line_magic\n@register_line_magic\ndef shout(line):\n    return line.upper()")
    shell.run_cell("%shout hello")
    assert last_out(shell) == "HELLO"
    assert LINE_MAGICS["shout"].user


def test_magics_class_with_parse_options(shell):
    shell.run_cell(textwrap.dedent('''
        from IPython.core.magic import Magics, magics_class, line_magic, cell_magic
        @magics_class
        class Mine(Magics):
            @line_magic
            def opts(self, line):
                o, rest = self.parse_options(line, "n:v", list_all=True)
                return (o.get("n"), "v" in o, rest)
            @cell_magic("twice")
            def twice(self, line, cell):
                return cell * 2
        get_ipython().register_magics(Mine)
    '''))
    assert shell.last_ok
    shell.run_cell("%opts -n 3 -v file.py")
    assert last_out(shell) == (["3"], True, "file.py")
    shell.run_cell("%%twice\nab")
    assert last_out(shell) == "ab\nab\n"


def test_magic_arguments(shell):
    shell.run_cell(textwrap.dedent('''
        from IPython.core.magic import register_line_magic
        from IPython.core.magic_arguments import magic_arguments, argument, parse_argstring
        @magic_arguments()
        @argument("--count", type=int, default=1)
        @argument("word")
        @register_line_magic
        def rep(line):
            args = parse_argstring(rep, line)
            return args.word * args.count
    '''))
    shell.run_cell("%rep --count 3 ha")
    assert last_out(shell) == "hahaha"


def test_events_fire(shell):
    shell.run_cell("seen = []\nip = get_ipython()\nip.events.register('pre_run_cell', lambda info: seen.append(info.raw_cell))\nip.events.register('post_run_cell', lambda r: seen.append(r.success))")
    shell.run_cell("1 + 1")
    # the post_run_cell hook registered in the first cell already fires for that cell
    assert shell.ns["seen"] == [True, "1 + 1", True]


def test_input_and_ast_transformers(shell):
    shell.run_cell(textwrap.dedent('''
        import ast
        class Doubler(ast.NodeTransformer):
            def visit_Constant(self, node):
                return ast.Constant(node.value * 2) if isinstance(node.value, int) else node
        get_ipython().ast_transformers.append(Doubler())
        get_ipython().input_transformers_post.append(lambda lines: [l.replace("PLUS", "+") for l in lines])
    '''))
    shell.run_cell("20 PLUS 1")
    assert last_out(shell) == 42


def test_load_ipython_extension(shell, profile, monkeypatch):
    ext = profile.config_dir / "myext.py"
    ext.write_text("def load_ipython_extension(ip):\n    ip.user_ns['loaded_by'] = 'ext'\n")
    monkeypatch.syspath_prepend(str(profile.config_dir))
    shell.run_cell("%load_ext myext")
    assert shell.ns["loaded_by"] == "ext"
    shell.run_cell("%load_ext myext")
    assert shell.last_ok


def test_line_profiler_extension(shell):
    import pytest

    pytest.importorskip("line_profiler")
    shell.run_cell("%load_ext line_profiler")
    assert shell.last_ok, "line_profiler should load through the IPython stand-ins"
    shell.run_cell("def work(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total\n")
    shell.run_cell("%lprun -f work work(1000)")
    assert shell.last_ok


def test_display_protocols():
    class Md:
        def _repr_markdown_(self):
            return "# hi"

    class Pretty:
        def _repr_pretty_(self, p, cycle):
            p.text("pretty!")

    class Bundle:
        def _repr_mimebundle_(self, include=None, exclude=None):
            return {"text/plain": "from bundle"}

    class Claims:
        def __getattr__(self, name):
            return lambda *a: "should not be used"

    assert isinstance(display.render_value(Md()), Markdown)
    assert str(display.render_value(Pretty())) == "pretty!"
    assert str(display.render_value(Bundle())) == "from bundle"
    assert not isinstance(display.render_value(Claims()), Text)


def test_display_function_and_type_printers(shell):
    shell.run_cell("get_ipython().display_formatter.formatters['text/plain'].for_type(int, lambda n, p, cycle: p.text(hex(n)))")
    rendered = shell.render(255)
    assert str(rendered) == "0xff"
    shell.run_cell("from IPython.display import Markdown\ndisplay(Markdown('**bold**'))")
    assert shell.last_ok


def test_precision(shell):
    shell.run_cell("%precision 2")
    assert str(shell.render(3.14159)) == "3.14"
    rendered = shell.render([1.23456, {"x": 2.5}])
    from rich.console import Console

    console = Console(width=80, record=True)
    console.print(rendered)
    text = console.export_text()
    assert "1.23" in text and "2.50" in text
    shell.run_cell("%precision")
    assert shell.float_format == ""

import jedi
import pytest

from ember import signature
from ember.signature import split_param


def _text(frags):
    return "".join(t for _, t, *_ in frags)


def _info(code, ns):
    sigs = jedi.Interpreter(code, [ns]).get_signatures(1, len(code))
    assert sigs, code
    return signature.build(sigs[0], code, ns)


@pytest.fixture(scope="module")
def ns():
    namespace = {}
    exec(
        "def add(a: int, b: int = 2) -> int:\n    return a + b\n"
        "def untyped(x, y=3, *args, flag=False, **kw):\n    return x\n"
        "class Point:\n"
        "    def __init__(self, x: float, y: float = 0.0): ...\n"
        "    def norm(self, p=2) -> float:\n        return 1.5\n"
        "pt = Point(1)\n",
        namespace,
    )
    return namespace


@pytest.mark.parametrize(
    "text, expected",
    [
        ("a", ("", "a", None, None)),
        ("a: int", ("", "a", "int", None)),
        ("b: int=2", ("", "b", "int", "2")),
        ('sep: str | None=" "', ("", "sep", "str | None", '" "')),
        ("key: Callable[[int], str]=None", ("", "key", "Callable[[int], str]", "None")),
        ("*values: object", ("*", "values", "object", None)),
        ("**kw", ("**", "kw", None, None)),
        ("v: 'list[float]'", ("", "v", "list[float]", None)),
        ("d: dict[str, int]={'a': 1}", ("", "d", "dict[str, int]", "{'a': 1}")),
    ],
)
def test_split_param(text, expected):
    p = split_param(text)
    assert (p.stars, p.name, p.annotation, p.default) == expected


def test_declared_types_and_return(ns):
    assert _text(signature.render(_info("add(", ns), 200)) == "ƒ add(a: int, b: int = 2) -> int"


def test_types_inferred_from_defaults(ns):
    info = _info("untyped(", ns)
    by_name = {p.name: p for p in info.params}
    assert by_name["y"].annotation == "int" and by_name["y"].inferred
    assert by_name["flag"].annotation == "bool"
    assert by_name["x"].annotation is None


def test_constructor_returns_class(ns):
    assert _text(signature.render(_info("Point(", ns), 200)) == "ƒ Point(x: float, y: float = 0.0) -> Point"


def test_method_return_from_live_annotation(ns):
    assert _text(signature.render(_info("pt.norm(", ns), 200)).endswith("-> float")


def test_current_param_highlighted(ns):
    frags = signature.render(_info("add(1, ", ns), 200)
    current = [t for style, t, *_ in frags if style == "class:sig.param.current"]
    assert current == ["b"]


def test_narrow_width_keeps_current_param_and_return(ns):
    info = _info("print(1, sep='', ", ns)
    out = _text(signature.render(info, 50))
    assert "end" in out and out.endswith("-> None") and "…" in out

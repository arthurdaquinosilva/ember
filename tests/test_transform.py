from ember.transform import is_complete, next_indent, transform


def test_line_magic():
    assert transform("%timeit x") == "__ember__.magic('timeit', 'x')"


def test_indented_magic_keeps_indent():
    assert transform("if 1:\n    %pwd") == "if 1:\n    __ember__.magic('pwd', '')"


def test_shell_capture():
    assert transform("files = !ls -la") == "files = __ember__.shell('ls -la', capture=True)"
    assert transform("!echo hi") == "__ember__.shell('echo hi', capture=False)"


def test_help_syntax():
    assert transform("os.path?") == "__ember__.inspect('os.path', 1)"
    assert transform("??len") == "__ember__.inspect('len', 2)"


def test_cell_magic():
    assert transform("%%time\nx = 1") == "__ember__.cell_magic('time', '', 'x = 1')"


def test_magic_inside_triple_string_untouched():
    src = 's = """\n%notmagic\n"""'
    assert transform(src) == src


def test_regular_python_untouched():
    src = "a = b % c\nx != y"
    assert transform(src) == src


def test_is_complete():
    assert is_complete("x = 1")
    assert is_complete("%pwd")
    assert is_complete("await foo()")
    assert is_complete("1 +")  # syntax error surfaces instead of waiting
    assert not is_complete("def f():")
    assert not is_complete("def f():\n    return 1")
    assert is_complete("def f():\n    return 1\n")
    assert not is_complete("foo(1,")
    assert not is_complete("%%time\nx = 1")
    assert is_complete("%%time\nx = 1\n")


def test_next_indent():
    assert next_indent("def f():") == "    "
    assert next_indent("    return x") == ""
    assert next_indent("    x = 1") == "    "

# IPython compatibility

ember aims to run code written for IPython without changes. This page explains how, and where the two differ.

## `get_ipython()`

`get_ipython()` is available as a builtin inside ember and returns an object with IPython's `InteractiveShell` API:

| API | Notes |
| --- | --- |
| `user_ns`, `user_global_ns`, `push()`, `drop_by_id()`, `del_var()` | The session namespace |
| `run_cell()`, `run_line_magic()`, `run_cell_magic()`, `magic()`, `ex()`, `ev()` | Run code and magics |
| `system()`, `getoutput()` | Shell commands (`getoutput` returns an `SList`) |
| `register_magics()`, `register_magic_function()`, `find_line_magic()` | Custom magics |
| `events.register(name, callback)` | `pre_execute`, `pre_run_cell`, `post_execute`, `post_run_cell`, `shell_initialized` |
| `input_transformers_cleanup`, `input_transformers_post`, `ast_transformers` | Rewrite source lines or the AST before execution |
| `display_formatter.formatters['text/plain'].for_type(...)` | Custom text printers (`for_type_by_name` too) |
| `extension_manager`, `history_manager`, `set_next_input()`, `ask_exit()` | |
| `enable_gui()`, `enable_matplotlib()` | Event loop integration |

## Stand-in `IPython` modules

When IPython **isn't** installed, ember registers lightweight stand-ins for the modules IPython code usually imports, so imports like these work:

```python
from IPython import get_ipython
from IPython.display import display, Markdown, JSON, Code
from IPython.core.magic import Magics, magics_class, line_magic, cell_magic, register_line_magic
from IPython.core.magic_arguments import magic_arguments, argument, parse_argstring
from IPython.core.error import UsageError
from IPython.utils.text import SList
```

Provided: `IPython`, `IPython.display`, `IPython.core.{getipython, magic, magic_arguments, error, page, display, display_functions, interactiveshell}`, `IPython.lib.pretty`, `IPython.utils.{ipstruct, text, process}`.

When the real IPython **is** installed, ember doesn't touch it. `get_ipython()` inside your session still returns ember's shell, but libraries that import `IPython.get_ipython` directly get `None` and behave as in plain Python.

## Writing magics

Any of IPython's styles work:

```python
from IPython.core.magic import register_line_magic, register_cell_magic

@register_line_magic
def shout(line):
    "Upper-case the argument."
    return line.upper()

@register_cell_magic
def lines(line, cell):
    return len(cell.splitlines())
```

```python
from IPython.core.magic import Magics, magics_class, line_magic

@magics_class
class Counter(Magics):
    @line_magic
    def count(self, line):
        opts, rest = self.parse_options(line, "n:")
        return int(opts.get("n", 1)) * len(rest.split())

get_ipython().register_magics(Counter)
```

`%name` arguments go through `$var` / `{expr}` expansion unless the function is decorated with `@no_var_expand`; `@needs_local_scope` passes `local_ns`. `%help name` shows a magic's docstring.

## Extensions

`%load_ext module` imports the module and calls `load_ember_extension(ip)` if it exists, otherwise `load_ipython_extension(ip)`. `%unload_ext` and `%reload_ext` call the matching unload functions. List extensions to load at startup in `extensions = [...]` in [config.toml](configuration.md).

Known to work: **line_profiler** (`%load_ext line_profiler`, then `%lprun -f func func()`), and IPython's built-in `autoreload` and `storemagic` extension names (ember implements those natively).

`memory_profiler`'s magics import `distutils`, which Python 3.12 removed, so they fail to load on 3.12+ in any shell.

## Display protocol

See [Rich display](features.md#rich-display) for the order in which `_repr_*_` methods are used. Objects that answer every attribute lookup (for example mocks) are detected with IPython's canary check and shown with their `repr`.

## Differences from IPython

| | |
| --- | --- |
| Notebooks | ember is terminal-only; there is no Jupyter kernel |
| Images | `Image`, `SVG`, `Audio`, `Video` and `%matplotlib inline` show a placeholder |
| Configuration | `config.toml` instead of `ipython_config.py` (IPython's setting names are accepted) |
| Debugger | Python's `pdb`, prompt `(ember-pdb)` |
| `%run` | Same flags; `.ipy` files are supported, notebooks are not |
| Interactive shell programs | `!vim` / `!less` don't work because output is streamed through a pipe |
| History | Separate database from IPython's; `%history` range syntax is the same |
| `%reset` | Doesn't ask for confirmation (`-f` is accepted) |

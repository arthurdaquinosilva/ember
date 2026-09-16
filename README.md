# ✦ ember

A modern interactive Python shell — IPython's power, rebuilt around a calm, minimal terminal UI.

```
❯ x = [i**2 for i in range(8)]
╰─ ✓ 735µs


❯ x
│
│ [0, 1, 4, 9, 16, 25, 36, 49]
│
╰─ ✓ 2.6ms · list · 8 items · Out[2]


╭─ In [3] ───────────────────────────────────────────────────────────╮
│ ❯ say_my_name("Arthur"                                             │
╰────────────────────────────────────────────────────────────────────╯

 ƒ say_my_name(name: str) -> None
```

## Install

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/ember
```

## The interface

- **Boxed input editor** — syntax highlighting, auto-indent, bracket matching, inline history suggestions
- **Smart Enter** — runs complete code, adds a newline inside unfinished blocks (a blank line runs a block)
- **Typed signature hints** — declared, stub and inferred parameter/return types while you type a call
- **Cell blocks** — code, output on a rail, and a footer with status, time, result type and `Out[N]`
- **Spinner** for slow cells; `ctrl+c` interrupts
- **Paste anything** — `>>>` and `In [1]:` prompts (and their output lines) are stripped automatically
- **Background output** from threads appears above the prompt instead of scrambling it
- **emacs or vi** key bindings (`--vi`, `%vi`, `%emacs`) with a mode indicator
- **Themes**: `void` (default), `nebula`, `matrix`

## IPython, but everything

| area | what you get |
| --- | --- |
| syntax | `obj?` `obj??` · `np.*load*?` wildcard search · `!cmd` · `x = !cmd` / `!!cmd` → `SList` (`.s .n .p .grep() .fields()`) · `$var` / `{expr}` expansion · automagic (`cd ..`, `ls`, `pwd`) · top-level `await` |
| variables | `_ __ ___ _N Out` · `_i _ii _iii _iN In` · `_ih _oh _dh` |
| display | `display()`, `IPython.display` objects (Markdown, JSON, Code, HTML…), `_repr_pretty_`, `_repr_markdown_`, `_repr_mimebundle_`, `_repr_json_`, `_ipython_display_`, `display_formatter.formatters['text/plain'].for_type(...)`, pandas/polars tables, `%precision` |
| errors | `%xmode minimal·plain·context·verbose` · `%tb` · `%pdb` (automatic post-mortem) · `%debug` |
| running | `%run -i -n -e -t -d -p -m` · `%timeit -n -r -p -q -o` · `%time` · `%prun`/`%%prun` · `%%capture` · `%paste` · `%cpaste` · `%autoawait asyncio·trio·curio·off` · `%config ast_node_interactivity=all` |
| history | SQLite history grouped by session · `%history` with ranges (`4-6`, `~1/`, `~2/3-5`), `-g`, `-l`, `-o`, `-p`, `-f` · `%recall` · `%rerun` · `%macro` · `%save`/`%load` with ranges (`%load -s func file.py`) · `%store` · `%logstart`/`%logstop` |
| shell | `%cd -b bookmark`/`-N`/`-` · `%bookmark` · `%pushd`/`%popd`/`%dirs`/`%dhist` · `%alias`/`%unalias` (`%s`, `%l`) · `%sx` · `%%bash %%sh %%zsh %%python %%ruby %%perl %%node` · `%%script --bg --out var` · `%killbgscripts` |
| namespace | `%who`/`%whos`/`%who_ls` with type filters · `%xdel` · `%reset in·out·dhist` · `%reset_selective` · `%pinfo %pinfo2 %pdef %pdoc %psource %pfile %page` |
| gui | `%gui qt·tk·osx·gtk3·gtk4·wx·asyncio` keeps event loops running while the prompt waits · `%matplotlib [backend]` for responsive plot windows |
| completion | jedi · magics · paths · dictionary/DataFrame keys (`d["ap⇥`) · `\alpha⇥` → α · `\N{GREEK SMALL LETTER BETA}⇥` · `\α⇥` → `\alpha` |
| reload | `%autoreload 0·1·2·now` patches existing functions, classes and instances in place · `%aimport` |
| extensibility | `get_ipython()` · events (`pre_run_cell`, `post_execute`, …) · `input_transformers_*` · `ast_transformers` · custom magics · `%load_ext` for ember **and IPython** extensions |

`%help` lists every key, syntax and magic; `%help name` explains one magic.

### Using IPython code and extensions

When IPython isn't installed, ember provides stand-in `IPython.*` modules, so code written for IPython runs unchanged:

```python
from IPython.core.magic import register_line_magic

@register_line_magic
def shout(line):
    return line.upper()
```

The same layer lets extensions load — `%load_ext line_profiler` then `%lprun -f func func()` works — and lets matplotlib hook its redraw into ember. If the real IPython *is* installed, ember leaves it alone; `get_ipython()` is still available inside ember.

## Configuration & profiles

`~/.config/ember/config.toml` (IPython-style names like `"InteractiveShell.xmode"` also work):

```toml
theme = "nebula"
editing_mode = "vi"
xmode = "context"
pdb = false
autoreload = 2
precision = "3"
ast_node_interactivity = "last_expr"
autoawait = "asyncio"
matplotlib = "macosx"          # or gui = "qt"
store_autorestore = true
exec_lines = ["import numpy as np"]
extensions = ["line_profiler"]

[aliases]
gs = "git status"
```

- Startup files: every `*.py` / `*.ipy` in `~/.config/ember/startup/`, in name order
- Profiles: `ember --profile work` uses `~/.config/ember/profiles/work/` with its own config, startup files, history and `%store`
- Data lives in `~/.local/share/ember/` (history database, stored variables, bookmarks)
- `%config` lists and changes settings for the current session

## Keys

| key | action |
| --- | --- |
| `enter` | run (or newline when incomplete) |
| `alt+enter` / `ctrl+j` | newline |
| `tab` / `shift+tab` | complete · indent / dedent |
| `→` | accept suggestion |
| `↑` `↓` | history, filtered by what you've typed |
| `ctrl+r` | search history |
| `ctrl+o` | edit in `$EDITOR` |
| `ctrl+l` | clear screen |
| `ctrl+c` | clear input / interrupt |
| `ctrl+d` | exit |

## CLI

```sh
ember                       # interactive
ember script.py args…       # run a file
ember -m package.module     # run a module
ember -i script.py          # run, then stay interactive
ember -c "1 + 1"            # run a command
ember --profile work --vi --theme nebula --no-startup
```

## Known limits

- Terminal only: no Jupyter kernel, and rich image output (`Image`, `SVG`, `%matplotlib inline`) shows a placeholder
- `!cmd` output is streamed through a pipe, so fully interactive programs (vim, less) should be run with `%edit` or outside ember
- `memory_profiler`'s magics import `distutils`, which Python 3.12 removed; they fail to load there regardless of shell

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

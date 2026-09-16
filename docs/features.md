# Features

## The interface

Each cell you run becomes a block:

```text
> greet("Arthur", times=2)
│
│ 'hi Arthur! hi Arthur! '
│
╰─ ✓ 2.8ms · str · 22 chars · Out[2]
```

- The footer shows success or the exception name, how long the cell took, the result's type and size, and where it's stored (`Out[2]`, also `_2`).
- Output printed while the cell runs appears on the rail as it happens. Cells slower than a quarter second show a spinner; Ctrl+C interrupts.
- Output from background threads printed while you're typing appears above the input instead of corrupting it.

### Typing

- **Enter** runs the cell when it's complete. Inside an unfinished block (`def`, `for`, an open bracket) it adds an indented new line; press Enter on a blank line to run the block.
- **Shift+Enter**, Alt+Enter or Ctrl+J always insert a newline.
- **Auto-indent** after `:` and brackets, dedent after `return`/`pass`/`break`/`continue`/`raise`; Backspace in indentation removes a whole level.
- **Grey suggestions** come from your history; → accepts them. ↑/↓ search history by what you've typed so far.
- **Pasting** code copied from docs or another shell works: `>>> ` / `... ` and `In [1]: ` / `   ...: ` prompts are removed, and the output lines between them are dropped.
- **Ctrl+O** opens the cell in `$EDITOR`.
- **vi mode**: `--vi`, `%vi` or `editing_mode = "vi"`. The mode shows as `[INSERT]` / `[NORMAL]`; Enter runs the cell from normal mode.

### Signature hints

While you type inside a call, the signature appears below the input with the current argument highlighted:

```text
ƒ greet(name: str, times: int = 1) -> str
```

Types come from, in order: declared annotations and the standard library's type stubs, the value you're passing (`"Arthur"` → `str`), the parameter's default, and for return types, the function's body (`None` when it never returns a value, `Generator` for generators, simple literal returns). Inferred types are shown in muted italics. Long signatures collapse to fit: defaults go first, then parameters far from the cursor.

## Input syntax

| Syntax | Meaning |
| --- | --- |
| `obj?` / `obj??` | Inspect an object: type, signature, file, docstring / plus source |
| `np.*load*?` | Search names with wildcards (`%psearch` for options) |
| `!cmd` | Run a shell command, streaming its output |
| `x = !cmd`, `!!cmd` | Capture output as an `SList`: a list of lines with `.s` (space-joined), `.n` (newline-joined), `.p` (paths), `.grep(pattern)`, `.fields(0, 2)` |
| `$name`, `{expr}` | Insert Python values into shell commands and magic arguments; `$$` for a literal `$` |
| `%magic args` | Line magic ([reference](magics.md)); with automagic on, `cd ..`, `ls`, `pwd` work without `%` |
| `%%magic` | Cell magic, on the first line |
| `await …` | Top-level await with asyncio (or trio/curio via `%autoawait`) |
| `name` of a macro | Runs the macro (`%macro`) |

Variables kept for you: `_`, `__`, `___`, `_N`, `Out` (results); `_i`, `_ii`, `_iii`, `_iN`, `In` (inputs); `_ih`, `_oh`, `_dh` (input, output and directory history).

What gets displayed is controlled by `ast_node_interactivity`: the last expression (default), every expression (`all`), or also the value of a final assignment (`last_expr_or_assign`). End a line with `;` to hide its result.

## Rich display

ember picks the richest rendering an object offers:

1. Printers registered with `get_ipython().display_formatter.formatters['text/plain'].for_type(...)`
2. pandas and polars DataFrames as tables
3. Rich renderables (anything with `__rich__` or `__rich_console__`)
4. `_repr_mimebundle_`, `_repr_markdown_`, `_repr_pretty_`, `_repr_json_`, `_repr_latex_`
5. `_repr_html_` for objects with no useful `repr`
6. A pretty-printed `repr`, honouring `%precision`

`display(obj, ...)` is available without importing it, and the `IPython.display` classes (`Markdown`, `JSON`, `Code`, `HTML`, `Pretty`, `FileLink`, …) render in the terminal. Images, SVG, audio and video show a placeholder.

## Errors and debugging

- `%xmode` chooses how exceptions look: `minimal` (one line), `plain` (Python's standard traceback), `context` (highlighted source around each frame, the default) or `verbose` (also the local variables of each function). ember's own frames are hidden.
- `%tb` shows the last traceback again, optionally in another mode: `%tb verbose`.
- `%debug` opens the post-mortem debugger on the last exception; `%debug statement` runs a statement under the debugger.
- `%pdb on` opens the debugger automatically whenever a cell raises.

## History and sessions

History is stored in SQLite, grouped by session, including a `repr` of each output.

```python
%history              # this session
%history -n 4-6 ~1/   # lines 4–6 of this session and all of the previous one
%history -g "import*" # search every session
%history -l 20 -o     # last 20 lines with their outputs
%history -p -f log.py # with >>> prompts, written to a file
%recall 12            # put line 12 back into the input for editing
%rerun -l 3           # run the last three lines again
%macro setup 1-4      # typing `setup` now runs lines 1–4
%save work.py 1-10    # write lines to a file
%load -s helper utils.py  # load one function from a file into the input
%store df             # keep a variable across sessions (%store -r to restore)
%logstart -o -t       # log input, outputs and timestamps to a file
```

Range syntax: `4`, `4-6` (inclusive), `4:6` (end exclusive), `~1/` (the whole previous session), `~2/3-5`.

## Running and timing

- `%run script.py` runs a file in a fresh namespace and copies its variables into yours (`-i` shares your namespace). Options: `-t` time it, `-p` profile it, `-d` step through it in the debugger, `-m module`, `-e` ignore `sys.exit()`, `-n` don't set `__name__` to `"__main__"`.
- `%timeit` picks a loop count automatically; `-o` returns a result object (`.average`, `.stdev`, `.best`, `.all_runs`), `-q` hides the output. `%%timeit` times a whole cell, using the first line as setup.
- `%time` / `%%time` show wall and CPU time.
- `%prun` / `%%prun` profile with cProfile and show a sortable table (`-s tottime -l 20`); `-r` returns the stats.
- `%%capture out` captures stdout, stderr and displays into `out`; call `out()` to show them.
- `%paste` runs the clipboard and `%cpaste` reads a pasted block until `--`; both strip prompts.

## Shell and files

- `%cd` with `-` (previous directory), `-N` (entry N of `%dhist`), `-b name` (bookmark), and bookmark names as a fallback.
- `%bookmark name [dir]`, `%pushd` / `%popd` / `%dirs`, `%dhist`.
- `%alias name command` with `%s` placeholders or `%l` for the whole line; defaults include `ll`, `cat`, `cp`, `mv`, `rm`, `mkdir`.
- `%%bash`, `%%sh`, `%%zsh`, `%%python`, `%%ruby`, `%%perl`, `%%node`, or `%%script program` run a cell with another program. `--out var` / `--err var` capture output, `--bg` runs it in the background (`%killbgscripts` stops them).
- `%%writefile path` writes a cell to a file.
- `%env`, `%pip` (for ember's own Python), `%ls`, `%pwd`.

## Reloading code

`%autoreload 2` reloads modules you edit before each cell and updates what you already have: functions imported with `from module import f`, classes, and instances of those classes pick up the new code. `%autoreload 1` limits this to modules marked with `%aimport module`; `%autoreload` alone reloads everything now.

## GUI event loops and plotting

GUI windows only respond when an event loop runs, and at the prompt nothing does — unless ember keeps it going while it waits for your input:

```python
%matplotlib            # the current backend, e.g. macosx
%matplotlib qt         # or tk, osx, gtk3, gtk4, wx
%gui asyncio           # background asyncio tasks keep running between cells
```

`plt.ion()` alone also hooks matplotlib into ember. `%matplotlib inline` needs a notebook and isn't available.

## Completion

- Python names and attributes via Jedi, with an icon for each kind (function, class, module, keyword, value).
- Magic names after `%`, file paths after `%run`, `%cd`, `%load`, `!cmd` and friends.
- Dictionary keys and DataFrame columns: `data["ap` → `data["apple"]`.
- Unicode: `\alpha` Tab → `α`, `\N{GREEK SMALL LETTER BETA}` Tab → `β`, and `\α` Tab → `\alpha`.

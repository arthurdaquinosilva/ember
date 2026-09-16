# ✦ ember

A modern interactive Python shell — IPython's power, rebuilt around a calm, minimal terminal UI.

```
❯ x = [i**2 for i in range(8)]
╰─ ✓ 735µs

❯ x
│ [0, 1, 4, 9, 16, 25, 36, 49]
╰─ ✓ 2.6ms · list · 8 items · Out[2]

╭─ In [3] ─────────────────────────────────────────────────────────────╮
│ ❯ print(                                                             │
╰──────────────────────────────────────────────────────────────────────╯
 ƒ print(*values: object, sep: str | None=" ", end: str | None="\n", …
```

## Install

```sh
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/ember
```

## What's inside

- **Boxed input editor** with syntax highlighting, auto-indent, bracket matching and inline suggestions from history
- **Smart Enter**: runs complete code, adds a newline for unfinished blocks (a blank line runs a block; `alt+enter` always adds a newline)
- **Jedi completions** with type icons, and **live signature hints** in the status bar that highlight the current argument
- **Cell blocks**: each run shows its code, output on a left rail, and a footer with status, time, result type and `Out[N]`
- **Live spinner** for slow cells; `ctrl+c` interrupts
- **Rich output**: pretty-printed values, tables for pandas/polars DataFrames, rich renderables shown as-is
- **Readable tracebacks** that include the source of your cells
- **Top-level `await`**
- IPython-style extras: `obj?` / `obj??`, `!cmd`, `x = !cmd`, `_`, `__`, `_N`, `In`, `Out`
- **Magics**: `%timeit`, `%time`, `%whos`, `%run`, `%load`, `%edit`, `%pip`, `%cd`, `%ls`, `%history`, `%save`, `%autoreload`, `%debug`, `%copy`, `%env`, `%theme`, `%%time`, `%%timeit`, `%%writefile`, `%%bash` — see `%help`
- **Themes**: `void` (default), `nebula`, `matrix`

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
ember                  # interactive
ember script.py        # run a file
ember -i script.py     # run, then stay interactive
ember -c "1 + 1"       # run a command
ember --theme nebula
```

Pick a default theme with `EMBER_THEME=nebula` or `~/.config/ember/config.toml` (`theme = "nebula"`).
History is stored in `~/.local/share/ember/history`.

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

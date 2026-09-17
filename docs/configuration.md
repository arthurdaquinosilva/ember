# Configuration

## Where things live

| Path | Contents |
| --- | --- |
| `~/.config/ember/config.toml` | Settings (this page) |
| `~/.config/ember/startup/` | `*.py` / `*.ipy` files run at startup, in name order |
| `~/.local/share/ember/history.sqlite` | Input and output history, grouped by session |
| `~/.local/share/ember/store/` | Variables saved with `%store` |
| `~/.local/share/ember/bookmarks.json` | Directory bookmarks from `%bookmark` |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` are respected.

## config.toml

Every setting is optional. This example shows each one with its default:

```toml
theme = "void"                     # void · nebula · matrix
layout = "block"                   # block (full-width input bar) · box (rounded box)
editing_mode = "emacs"             # emacs · vi
automagic = true                   # run magics without the % prefix (cd .., ls, pwd)
autoreload = 0                     # 0 off · 1 only %aimport-ed modules · 2 all modules
pdb = false                        # open the debugger automatically on errors
xmode = "context"                  # minimal · plain · context · verbose
autoawait = "asyncio"              # asyncio · trio · curio · off
precision = ""                     # float display: "3" or a %-format like "%.2e"
ast_node_interactivity = "last_expr"  # last_expr · all · last · none · last_expr_or_assign
gui = ""                           # keep an event loop running: qt · tk · osx · gtk3 · gtk4 · wx · asyncio
matplotlib = ""                    # activate a matplotlib backend at startup, e.g. "macosx"
store_autorestore = false          # restore %store variables at startup
history_log_output = true          # save a repr of each output in the history database
exec_lines = []                    # code to run at startup, e.g. ["import numpy as np"]
exec_files = []                    # files to run at startup
extensions = []                    # extensions to load, e.g. ["line_profiler"]

[aliases]                          # shell aliases; %s = positional argument, %l = rest of the line
gs = "git status"
serve = "python -m http.server %s"
```

IPython's names are accepted too, so you can reuse settings you already know:

```toml
"InteractiveShell.xmode" = "Verbose"
"TerminalInteractiveShell.editing_mode" = "vi"
"InteractiveShellApp.extensions" = ["autoreload"]
```

Unknown or invalid keys are reported as a warning when ember starts; they never stop it from starting.

### Changing settings in a session

```python
%config                         # table of every setting and its value
%config xmode                   # show one
%config xmode=verbose           # change it for this session
%config InteractiveShell.pdb = True
```

Changes made with `%config` (and shortcuts like `%vi`, `%theme`, `%xmode`) last for the session. Put them in `config.toml` to keep them.

## Layouts and themes

- `block` — a pixel `EMBER:` banner, a full-width filled input bar, a key bar with context-aware shortcuts (replaced by the signature while you type a call) and a mode line with `[INSERT]`/`[NORMAL]` and session status.
- `box` — a compact banner, a rounded input box titled `In [N]`, and a single status line.

Switch live with `%config layout=box`. List and preview themes with `%theme`, switch with `%theme nebula`.

## Profiles

A profile is a separate set of settings, startup files, history and stored variables:

```sh
ember --profile work
```

uses `~/.config/ember/profiles/work/` and `~/.local/share/ember/profiles/work/`. `EMBER_PROFILE=work` does the same. `%profile` shows the active profile and its directories.

## Startup

At startup ember defines aliases, then runs `exec_lines`, the files in the startup directory, `exec_files`, loads `extensions`, restores `%store` variables (if enabled) and turns on `gui`/`matplotlib`. Errors are shown but don't stop ember from starting. `ember --no-startup` skips startup code and extensions.

## Command-line options

| Option | |
| --- | --- |
| `ember file.py [args…]` | Run a file and exit (like `python file.py`) |
| `-m module` | Run a module and exit |
| `-c code` | Run code and exit |
| `-i` | Stay interactive after `file`, `-m` or `-c` |
| `--profile NAME` | Use a named profile |
| `--theme NAME` | Theme for this run |
| `--vi` | vi key bindings for this run |
| `--no-startup` | Skip `exec_lines`, startup files and extensions |
| `--version` | Print the version |

Piping code in (`echo 'print(1)' | ember`) runs it as a single cell and exits with status 1 if it failed.

## Environment variables

| Variable | |
| --- | --- |
| `EMBER_THEME` | Overrides `theme` |
| `EMBER_PROFILE` | Default profile name |
| `VISUAL` / `EDITOR` | Editor for Ctrl+O, `%edit` |
| `XDG_CONFIG_HOME`, `XDG_DATA_HOME` | Base directories |

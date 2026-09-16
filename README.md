<div align="center">

<img src="https://raw.githubusercontent.com/arthurdaquinosilva/ember/main/docs/assets/cover.png" alt="ember's start screen: the pixel EMBER_ wordmark, version and environment info, the input bar and the key bar" width="900">

# ✦ ember

**A modern, beautiful interactive Python shell.**
IPython's power — magics, history, debugging, extensions — rebuilt around a calm terminal UI.

[![tests](https://github.com/arthurdaquinosilva/ember/actions/workflows/tests.yml/badge.svg)](https://github.com/arthurdaquinosilva/ember/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://github.com/arthurdaquinosilva/ember/blob/main/pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](https://github.com/arthurdaquinosilva/ember/blob/main/LICENSE)

</div>

## See it in action

<p align="center">
<img src="https://raw.githubusercontent.com/arthurdaquinosilva/ember/main/docs/assets/demo.svg?sanitize=true" alt="ember running in a terminal: cells with results and timing, %timeit, and a typed signature hint" width="820">
</p>

## Why ember

- **Readable sessions.** Every cell is a block: your code, its output on a rail, and a footer with status, time, result type and `Out[N]`.
- **Help while you type.** Completions with type icons, and live signatures with declared *and* inferred types — `greet(name: str, times: int = 1) -> str` — even for functions without annotations.
- **Everything you use IPython for.** 85 magics, `obj?`, `!shell`, session history in SQLite, `%autoreload`, `%debug`, `%timeit`, `%prun`, top-level `await`, GUI event loops…
- **Runs IPython code.** `get_ipython()`, `IPython.display`, custom magics and IPython extensions like `line_profiler` work unchanged.
- **Feels good.** Paste code straight from docs (`>>>` prompts are stripped), Shift+Enter for new lines, vi or emacs keys, three themes, two layouts.

## Install

```sh
pip install git+https://github.com/arthurdaquinosilva/ember.git
```

Or with [pipx](https://pipx.pypa.io/) to get the `ember` command everywhere without touching your projects:

```sh
pipx install git+https://github.com/arthurdaquinosilva/ember.git
```

Then run `ember`. Requires Python 3.10+ on macOS or Linux.

> **Tip:** ember runs code with the Python it's installed into. To work with a project's packages, install ember inside that project's virtual environment.

## Quick tour

```python
> import json
> data = {"name": "ember", "tags": ["repl", "python"]}
> data?                     # inspect any object (?? shows the source)
> json.*load*?              # wildcard name search
> files = !ls               # shell output as a list with .grep() / .fields()
> %timeit sorted(range(1000))
> %history -g json          # search history across sessions
> %xmode verbose            # tracebacks with local variables
> %help                     # every key, syntax and magic
```

| | |
| --- | --- |
| **Enter** | run the cell (adds a newline while a block is unfinished) |
| **Shift+Enter** · Alt+Enter · Ctrl+J | insert a newline |
| **Tab** / Shift+Tab | complete · indent / dedent |
| **→** | accept the grey suggestion from history |
| **↑ ↓** · Ctrl+R | history · search history |
| **Ctrl+O** | edit the cell in `$EDITOR` |
| **Ctrl+C** · **Ctrl+D** | clear input / interrupt · exit |

Shift+Enter needs a terminal that reports modified keys (iTerm2, WezTerm, Ghostty, kitty, xterm; inside tmux set `extended-keys on`). Alt+Enter and Ctrl+J work everywhere.

## Documentation

| Guide | What's inside |
| --- | --- |
| [Features](https://github.com/arthurdaquinosilva/ember/blob/main/docs/features.md) | The interface, input syntax, display, errors & debugging, history, shell, GUI and completion |
| [Magic reference](https://github.com/arthurdaquinosilva/ember/blob/main/docs/magics.md) | All 85 magics with options (generated from the code) |
| [Configuration](https://github.com/arthurdaquinosilva/ember/blob/main/docs/configuration.md) | `config.toml`, layouts and themes, profiles, startup files, command-line options |
| [IPython compatibility](https://github.com/arthurdaquinosilva/ember/blob/main/docs/ipython-compatibility.md) | `get_ipython()`, custom magics, extensions, display protocol, what's different |
| [Releasing](https://github.com/arthurdaquinosilva/ember/blob/main/docs/releasing.md) | How versions are published to PyPI |

## Command line

```sh
ember                        # interactive
ember script.py args…        # run a file (-i to stay interactive afterwards)
ember -m package.module      # run a module
ember -c "print('hi')"       # run a command
ember --profile work --vi --theme nebula --no-startup
```

## Development

```sh
git clone https://github.com/arthurdaquinosilva/ember.git && cd ember
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest              # unit tests
.venv/bin/python scripts/gen_magic_docs.py   # regenerate docs/magics.md
.venv/bin/python scripts/screenshot.py       # re-record docs/assets/demo.svg
```

ember is built on [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) (input and layout), [Rich](https://github.com/Textualize/rich) (output), [Jedi](https://github.com/davidhalter/jedi) (completion and signatures) and [Pygments](https://pygments.org/) (highlighting).

## Known limits

- Terminal only — no Jupyter kernel; images (`Image`, `SVG`, `%matplotlib inline`) show a placeholder.
- `!cmd` streams through a pipe, so fully interactive programs (vim, less) should run outside ember.
- With the real IPython installed, ember leaves it untouched, so libraries calling IPython's own `get_ipython()` see no shell.

## License

[MIT](https://github.com/arthurdaquinosilva/ember/blob/main/LICENSE) © Arthur D'Aquino

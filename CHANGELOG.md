# Changelog

## 0.2.1

- The startup wordmark now reads `EMBER:`.
- Docs: debugging with `breakpoint()`, `%debug`, `%pdb`, `%run -d` and pdb commands.

## 0.2.0

- **Block layout** (new default): pixel `EMBER_` banner, full-width input bar, context-aware key bar and mode line. The rounded box is still available with `layout = "box"`.
- **IPython compatibility**: `get_ipython()`, events, input/AST transformers, display formatters, custom magics (`Magics`, `magic_arguments`), extensions (e.g. `line_profiler`), stand-in `IPython.*` modules, `display()` and the `_repr_*_` protocol.
- **Input**: pasted `>>>`/`In [N]:` prompts are stripped, Shift+Enter inserts a newline, automagic, `!!cmd`, `SList`, `$var`/`{expr}` expansion, wildcard `obj*?` search, vi mode with a mode indicator.
- **Errors**: `%xmode` (minimal, plain, context, verbose), `%tb`, `%pdb`.
- **History**: SQLite history grouped by session with IPython's range syntax; `%recall`, `%rerun`, `%macro`, `%store`, `%logstart`; `_ii`, `_iii`, `_ih`, `_oh`, `_dh`.
- **Running**: `%run` flags (`-i -n -e -t -d -p -m`), `%timeit -o -q`, `%prun`, `%%capture`, `%paste`, `%cpaste`, `%autoawait` with trio/curio, `ast_node_interactivity`.
- **Shell**: bookmarks, directory stack, aliases, `%sx`, `%%script --bg` and interpreter cell magics.
- **GUI**: `%gui` and `%matplotlib` keep event loops running at the prompt; background thread output renders above the input.
- **Configuration**: `config.toml`, profiles, startup files, `exec_lines`, `extensions`, `%config`.
- **Completion**: `\alpha` → α and `\N{…}` unicode input, dictionary and DataFrame key completion.
- **Signature hints** show declared, stub and inferred parameter and return types.
- `%autoreload 2` updates existing functions, classes and instances in place.

## 0.1.0

- First version: boxed prompt with syntax highlighting, cell blocks with timing footers, Jedi completion, live signature hints, top-level `await`, rich tracebacks and output, `obj?`, `!cmd` and a core set of magics, three themes.

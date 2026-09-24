#!/bin/sh
# ember installer — https://github.com/arthurdaquinosilva/ember
#
#   curl -fsSL https://raw.githubusercontent.com/arthurdaquinosilva/ember/main/install.sh | sh
#
# Installs the `ember` command into its own virtual environment, so it never
# interferes with your projects' packages. Uses pipx when available.
#
# Options (environment variables):
#   EMBER_VERSION=0.2.3   install a specific version
#   EMBER_NO_PIPX=1       always use the built-in installer, never pipx
#   EMBER_INSTALL_DIR     where to put the `ember` command (default: ~/.local/bin)
#
# Uninstall:  curl -fsSL <url> | sh -s -- --uninstall

set -eu

MIN_PY_MINOR=10
PACKAGE="ember-shell"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ember-shell"
BIN_DIR="${EMBER_INSTALL_DIR:-$HOME/.local/bin}"
VENV="$DATA_DIR/venv"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    accent=$(printf '\033[1;38;5;209m'); dim=$(printf '\033[2m'); bold=$(printf '\033[1m')
    green=$(printf '\033[32m'); red=$(printf '\033[31m'); reset=$(printf '\033[0m')
else
    accent=''; dim=''; bold=''; green=''; red=''; reset=''
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s▸%s %s\n' "$accent" "$reset" "$*"; }
note() { printf '%s  %s%s\n' "$dim" "$*" "$reset"; }
die()  { printf '%s✗ %s%s\n' "$red" "$*" "$reset" >&2; exit 1; }

banner() {
    printf '\n%s  █▀▀▀▀ █▄ ▄█ █▀▀▀▄ █▀▀▀▀ █▀▀▀▄%s\n'   "$accent" "$reset"
    printf '%s  █▄▄▄  █ █ █ █▄▄▄▀ █▄▄▄  █▄▄▄▀%s\n'     "$accent" "$reset"
    printf '%s  █     █   █ █   █ █     █ ▀▄%s\n'      "$accent" "$reset"
    printf '%s  ▀▀▀▀▀ ▀   ▀ ▀▀▀▀  ▀▀▀▀▀ ▀   ▀ ▀▀ ▀▀%s\n\n' "$accent" "$reset"
    note "a modern interactive Python shell"
    printf '\n'
}

# ── find a suitable python ─────────────────────────────────────────────────

python_ok() {
    [ -x "$(command -v "$1" 2>/dev/null)" ] || return 1
    "$1" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, $MIN_PY_MINOR) else 1)" 2>/dev/null
}

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if python_ok "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

# ── install / uninstall ────────────────────────────────────────────────────

uninstall() {
    removed=0
    if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "$PACKAGE"; then
        step "removing the pipx installation"
        pipx uninstall "$PACKAGE" >/dev/null 2>&1 && removed=1
    fi
    if [ -d "$VENV" ]; then
        step "removing $VENV"
        rm -rf "$DATA_DIR"
        removed=1
    fi
    if [ -L "$BIN_DIR/ember" ]; then
        rm -f "$BIN_DIR/ember"
        removed=1
    fi
    if [ "$removed" -eq 1 ]; then
        printf '%s✓%s ember removed. Your settings and history are untouched:\n' "$green" "$reset"
        note "${XDG_CONFIG_HOME:-$HOME/.config}/ember  ·  ${XDG_DATA_HOME:-$HOME/.local/share}/ember"
    else
        say "ember was not installed by this script."
        note "installed with pip? run: pip uninstall $PACKAGE"
    fi
}

spec() {
    if [ -n "${EMBER_VERSION:-}" ]; then
        printf '%s==%s' "$PACKAGE" "$EMBER_VERSION"
    else
        printf '%s' "$PACKAGE"
    fi
}

# The install_* functions set EMBER_BIN to the installed command.
install_with_pipx() {
    step "installing with pipx"
    if pipx list 2>/dev/null | grep -q "$PACKAGE"; then
        pipx upgrade "$PACKAGE" >/dev/null 2>&1 || pipx install --force "$(spec)" >/dev/null
    else
        pipx install --force "$(spec)" >/dev/null
    fi
    EMBER_BIN=$(command -v ember 2>/dev/null || printf '%s/ember' "$HOME/.local/bin")
}

install_with_venv() {
    python=$1
    step "installing into $(printf '%s' "$VENV" | sed "s|$HOME|~|")"
    mkdir -p "$DATA_DIR" "$BIN_DIR"
    [ -d "$VENV" ] && rm -rf "$VENV"
    "$python" -m venv "$VENV" || die "could not create a virtual environment (is the python3-venv package installed?)"
    "$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    "$VENV/bin/python" -m pip install --quiet "$(spec)" || die "pip could not install $PACKAGE"
    ln -sf "$VENV/bin/ember" "$BIN_DIR/ember"
    EMBER_BIN="$BIN_DIR/ember"
}

path_hint() {
    case ":$PATH:" in
        *":$BIN_DIR:"*) return 0 ;;
    esac
    # shellcheck disable=SC2088  # these are printed for the reader, not expanded
    case "${SHELL:-}" in
        */zsh)  rc="~/.zshrc" ;;
        */bash) rc="~/.bashrc" ;;
        */fish) rc="~/.config/fish/config.fish" ;;
        *)      rc="your shell's startup file" ;;
    esac
    printf '\n%s!%s %s is not on your PATH. Add this line to %s:\n' "$bold" "$reset" "$BIN_DIR" "$rc"
    if [ "${SHELL##*/}" = "fish" ]; then
        printf '\n    fish_add_path %s\n' "$BIN_DIR"
    else
        # shellcheck disable=SC2016  # $PATH must stay literal in the printed line
        printf '\n    export PATH="%s:$PATH"\n' "$BIN_DIR"
    fi
    printf '\nthen open a new terminal.\n'
}

main() {
    case "${1:-}" in
        --uninstall) uninstall; exit 0 ;;
        --help|-h)
            say "usage: install.sh [--uninstall]"
            note "EMBER_VERSION=x.y.z  install a specific version"
            note "EMBER_NO_PIPX=1      don't use pipx"
            note "EMBER_INSTALL_DIR    where to put the command (default: ~/.local/bin)"
            exit 0 ;;
        '') ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac

    banner
    python=$(find_python) || die "ember needs Python 3.$MIN_PY_MINOR or newer — install it from https://python.org and run this again"
    version=$("$python" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
    note "using $(printf '%s' "$python" | sed "s|$HOME|~|") (Python $version)"

    EMBER_BIN=''
    if command -v pipx >/dev/null 2>&1 && [ -z "${EMBER_NO_PIPX:-}" ]; then
        install_with_pipx
    else
        install_with_venv "$python"
    fi

    [ -x "$EMBER_BIN" ] || die "installation finished but $EMBER_BIN is missing"
    reported=$("$EMBER_BIN" --version 2>/dev/null) || die "$EMBER_BIN did not run"

    printf '\n%s✓%s installed %s%s%s\n' "$green" "$reset" "$bold" "$reported" "$reset"
    note "$(printf '%s' "$EMBER_BIN" | sed "s|$HOME|~|")"
    path_hint
    printf '\nstart it with %sember%s — then %s%%help%s for everything it can do.\n' "$bold" "$reset" "$bold" "$reset"
}

main "$@"

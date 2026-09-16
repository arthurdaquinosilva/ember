"""`\\alpha<tab>` → α completions (a curated LaTeX/Julia-style table) and `\\N{NAME}` lookup."""

from __future__ import annotations

import threading
import unicodedata

_GREEK = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu",
    "nu", "xi", "omicron", "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
]


def _build() -> dict[str, str]:
    table: dict[str, str] = {}
    for name in _GREEK:
        lookup = "LAMDA" if name == "lambda" else name.upper()
        table[name] = unicodedata.lookup(f"GREEK SMALL LETTER {lookup}")
        table[name.capitalize()] = unicodedata.lookup(f"GREEK CAPITAL LETTER {lookup}")
    table.update({
        "varepsilon": "ε", "epsilon": "ϵ", "vartheta": "ϑ", "varphi": "φ", "phi": "ϕ", "varpi": "ϖ",
        "varrho": "ϱ", "varsigma": "ς", "varkappa": "ϰ", "digamma": "ϝ",
        # operators & relations
        "pm": "±", "mp": "∓", "times": "×", "div": "÷", "cdot": "⋅", "circ": "∘", "bullet": "∙", "star": "⋆",
        "ast": "∗", "oplus": "⊕", "ominus": "⊖", "otimes": "⊗", "odot": "⊙", "wedge": "∧", "vee": "∨",
        "cap": "∩", "cup": "∪", "setminus": "∖", "sqrt": "√", "cbrt": "∛", "sum": "∑", "prod": "∏",
        "coprod": "∐", "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮", "partial": "∂", "nabla": "∇",
        "infty": "∞", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈",
        "equiv": "≡", "sim": "∼", "simeq": "≃", "cong": "≅", "propto": "∝", "ll": "≪", "gg": "≫",
        "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇",
        "forall": "∀", "exists": "∃", "nexists": "∄", "emptyset": "∅", "varnothing": "∅", "neg": "¬",
        "lnot": "¬", "land": "∧", "lor": "∨", "xor": "⊻", "perp": "⊥", "parallel": "∥", "angle": "∠",
        "therefore": "∴", "because": "∵", "degree": "°", "prime": "′", "dagger": "†", "ddagger": "‡",
        "ldots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱", "aleph": "ℵ", "hbar": "ℏ", "ell": "ℓ",
        "euler": "ℯ", "im": "ℑ", "Re": "ℜ", "wp": "℘", "top": "⊤", "bot": "⊥", "models": "⊨", "vdash": "⊢",
        # arrows
        "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←", "uparrow": "↑", "downarrow": "↓",
        "leftrightarrow": "↔", "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔", "implies": "⟹",
        "iff": "⟺", "mapsto": "↦", "longrightarrow": "⟶", "longleftarrow": "⟵", "nearrow": "↗", "searrow": "↘",
        # blackboard / misc letters
        "bbR": "ℝ", "bbN": "ℕ", "bbZ": "ℤ", "bbQ": "ℚ", "bbC": "ℂ", "bbP": "ℙ", "bbE": "𝔼", "bbone": "𝟙",
        "checkmark": "✓", "xmark": "✗", "euro": "€", "pounds": "£", "yen": "¥", "copyright": "©",
    })
    for d, sub, sup in zip("0123456789", "₀₁₂₃₄₅₆₇₈₉", "⁰¹²³⁴⁵⁶⁷⁸⁹"):
        table[f"_{d}"] = sub
        table[f"^{d}"] = sup
    for c, sub in zip("aehijklmnoprstuvx", "ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"):
        table[f"_{c}"] = sub
    for c, sup in zip("abcdefghijklmnoprstuvwxyz", "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ"):
        table[f"^{c}"] = sup
    table.update({"_+": "₊", "_-": "₋", "_=": "₌", "^+": "⁺", "^-": "⁻", "^=": "⁼", "^(": "⁽", "^)": "⁾"})
    return table


LATEX_SYMBOLS = _build()
REVERSE_SYMBOLS: dict[str, str] = {}
for _name, _char in LATEX_SYMBOLS.items():
    REVERSE_SYMBOLS.setdefault(_char, _name)

_unicode_names: list[tuple[str, str]] | None = None
_names_lock = threading.Lock()


def unicode_names() -> list[tuple[str, str]]:
    """(NAME, char) for every named code point; built lazily (~0.2s) the first time."""
    global _unicode_names
    with _names_lock:
        if _unicode_names is None:
            names = []
            for cp in range(0x20, 0x110000):
                if 0xD800 <= cp <= 0xDFFF:
                    continue
                name = unicodedata.name(chr(cp), None)
                if name:
                    names.append((name, chr(cp)))
            _unicode_names = names
        return _unicode_names

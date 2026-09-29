import re

INTERVAL = re.compile(r"\{\d+(?:,\d*)?\}")

# Character classes use the C locale in both runtimes.
POSIX_CLASSES = {
    "alpha": "A-Za-z",
    "digit": "0-9",
    "alnum": "0-9A-Za-z",
    "upper": "A-Z",
    "lower": "a-z",
    "space": " \\t\\n\\r\\f\\v",
    "blank": " \\t",
    "punct": "!-/:-@\\[-`{-~",
    "print": " -~",
    "graph": "!-~",
    "cntrl": "\\x00-\\x1f\\x7f",
    "xdigit": "0-9A-Fa-f",
}


def translate_bracket(pattern: str, start: int, out: list[str]) -> int:
    """Translate one bracket expression, expanding POSIX classes.

    Args:
        pattern (str): the whole ERE source.
        start (int): index of the opening ``[``.
        out (list[str]): accumulator receiving translated text.

    Returns:
        int: index just past the closing ``]``.
    """
    idx = start + 1
    out.append("[")
    if idx < len(pattern) and pattern[idx] == "^":
        out.append("^")
        idx += 1
    # A `]` in the first position is a literal member in an ERE, but
    # Python would read it as the end of the bracket expression.
    if idx < len(pattern) and pattern[idx] == "]":
        out.append("\\]")
        idx += 1
    while idx < len(pattern):
        ch = pattern[idx]
        if ch == "]":
            out.append("]")
            return idx + 1
        if pattern.startswith("[:", idx):
            close = pattern.find(":]", idx + 2)
            if close == -1:
                out.append("\\[")
                idx += 1
                continue
            name = pattern[idx + 2:close]
            if name not in POSIX_CLASSES:
                raise re.error("Invalid character class name")
            out.append(POSIX_CLASSES[name])
            idx = close + 2
            continue
        if ch == "\\" and idx + 1 < len(pattern):
            out.append(pattern[idx:idx + 2])
            idx += 2
            continue
        if ch == "[":
            out.append("\\[")
            idx += 1
            continue
        out.append(ch)
        idx += 1
    raise re.error("Unmatched [, [^, [:, [., or [=")


def translate_classes(pattern: str, nest: bool = True) -> str:
    """Expand POSIX brackets while preserving regex operators and escapes.

    With ``nest``, a quantifier stacked on a quantified atom repeats that
    whole repetition, the way glibc reads an ERE: ``a++`` is ``(a+)+``
    and ``a+?`` is ``(a+)?``, never the host's possessive or lazy forms.

    Args:
        pattern (str): the regex source, before host compilation.
        nest (bool): read stacked quantifiers as nested repetition.
    """
    out: list[str] = []
    groups: list[int] = []
    atom: int | None = None
    quantified = False
    idx = 0
    while idx < len(pattern):
        ch = pattern[idx]
        interval = INTERVAL.match(pattern, idx) if ch == "{" else None
        if ch in "*+?" or interval is not None:
            token = interval.group() if interval is not None else ch
            if nest and quantified and atom is not None:
                out[atom:] = ["(?:", *out[atom:], ")"]
            out.append(token)
            quantified = atom is not None
            idx += len(token)
            continue
        quantified = False
        if ch == "\\" and idx + 1 < len(pattern):
            atom = len(out)
            out.append(pattern[idx:idx + 2])
            idx += 2
        elif ch == "[":
            atom = len(out)
            idx = translate_bracket(pattern, idx, out)
        elif ch == "(":
            groups.append(len(out))
            atom = None
            out.append(ch)
            idx += 1
        elif ch == ")":
            atom = groups.pop() if groups else None
            out.append(ch)
            idx += 1
        else:
            atom = None if ch in "|^$" else len(out)
            out.append(ch)
            idx += 1
    return "".join(out)


def class_characters(name: str) -> str:
    """Expand a class to its ordered C-locale characters for tr.

    Args:
        name (str): a POSIX character class name.
    """
    if name not in POSIX_CLASSES:
        raise ValueError(f"tr: invalid character class '{name}'")
    pattern = re.compile("[" + POSIX_CLASSES[name] + "]")
    return "".join(chr(n) for n in range(128) if pattern.fullmatch(chr(n)))


def compile_posix_regex(source: str, flags: int = 0) -> re.Pattern[str]:
    """Compile translated POSIX regex source with C-locale case folding.

    Args:
        source (str): regex source in the host engine's syntax.
        flags (int): host regex flags, including IGNORECASE when requested.
    """
    return re.compile(source, flags | re.ASCII)

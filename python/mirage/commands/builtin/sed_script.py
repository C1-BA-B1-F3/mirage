# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import re
import string
from typing import Any, Required, TypedDict

from mirage.shell.bytes import byte_char
from mirage.utils.posix import compile_posix_regex, translate_classes

_SIMPLE_CMDS = frozenset("dDpPhHgGxNq")

_SedAddr = tuple[str, str]


class SedCommand(TypedDict, total=False):
    """One parsed sed command; the fields beyond ``cmd`` vary per verb."""

    cmd: Required[str]
    addr_start: _SedAddr | None
    addr_end: _SedAddr | None
    negate: bool
    pattern: str
    replacement: str
    expr_flags: str
    text: str
    label: str


def _apply_repl(m: "re.Match[str]", repl: str) -> str:
    """Expand a GNU sed replacement against a match.

    `&` is the whole match, `\\1`..`\\9` are groups, `\\&` is a literal `&`,
    `\\n`/`\\t` are newline/tab, and `\\X` is a literal X.

    Args:
        m (re.Match): The regex match for the current substitution.
        repl (str): The sed replacement template.
    """
    out: list[str] = []
    i = 0
    while i < len(repl):
        ch = repl[i]
        if ch == "\\" and i + 1 < len(repl):
            nxt = repl[i + 1]
            if nxt in "0123456789":
                grp = m.group(int(nxt))
                out.append(grp if grp is not None else "")
            elif nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            else:
                out.append(nxt)
            i += 2
        elif ch == "&":
            out.append(m.group(0))
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _parse_address(addr: str) -> tuple[str, str] | None:
    if not addr:
        return None
    if addr.isascii() and addr.isdigit():
        return ("line", addr)
    if addr == "$":
        return ("last", "")
    return None


def _scan_regex_field(rest: str, start: int, delim: str) -> tuple[str, int]:
    """Collect an address regex up to its unescaped closing delimiter.

    A backslash escapes the next character (so ``\\/`` inside ``/re/`` is a
    literal slash) and the pair is kept verbatim: BRE escapes like ``\\+``
    must survive for the regex translator, and both engines accept a
    redundant ``\\/``.

    Args:
        rest (str): the script text, positioned at the address.
        delim (str): the delimiter character to stop at.
        start (int): index of the first regex character.

    Returns:
        tuple[str, int]: the regex and the index after the delimiter.
    """
    out: list[str] = []
    i = start
    while i < len(rest):
        ch = rest[i]
        if ch == "\\" and i + 1 < len(rest):
            out.append(rest[i:i + 2])
            i += 2
            continue
        if ch == delim:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise ValueError("sed: unterminated address regex")


def _consume_address(rest: str) -> tuple[tuple[str, str] | None, str]:
    if not rest:
        return None, rest
    if rest[0] == "/":
        pattern, nxt = _scan_regex_field(rest, 1, "/")
        return ("regex", pattern), rest[nxt:]
    if rest[0] == "\\" and len(rest) > 1:
        # GNU's \cREc form: the character after the backslash delimits the
        # regex in place of `/`.
        pattern, nxt = _scan_regex_field(rest, 2, rest[1])
        return ("regex", pattern), rest[nxt:]
    if rest[0] in "0123456789" or rest[0] == "$":
        num = ""
        while rest and (rest[0] in "0123456789" or rest[0] == "$"):
            num += rest[0]
            rest = rest[1:]
        return _parse_address(num), rest
    return None, rest


_TEXT_ESCAPES = {
    "a": "\x07",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\n": "\n",
}

_TEXT_ESCAPE_BASES = {"d": 10, "o": 8, "x": 16}


def _decode_text_escapes(buf: str) -> str:
    """Decode a/i/c text as GNU's normalize_text does.

    The escapes in ``_TEXT_ESCAPES``, ``\\dNNN``, ``\\oNNN`` and ``\\xHH``
    bytes (one above ASCII carried as its surrogate escape, which
    ``encode_text`` writes back as that raw byte, as GNU writes it), and
    ``\\cX`` control characters; a backslash before any other character is
    dropped. The text always ends
    in the newline that closed it, so ``\\c`` at its end takes that newline
    as X.

    Args:
        buf (str): the text as read, closing newline included.

    Returns:
        str: the decoded text.
    """
    out: list[str] = []
    i = 0
    while i < len(buf):
        ch = buf[i]
        if ch != "\\" or i + 1 >= len(buf):
            out.append(ch)
            i += 1
            continue
        nx = buf[i + 1]
        i += 2
        simple = _TEXT_ESCAPES.get(nx)
        if simple is not None:
            out.append(simple)
            continue
        base = _TEXT_ESCAPE_BASES.get(nx)
        if base is not None:
            value = 0
            digits = 0
            limit = 1
            while i < len(buf) and limit <= 255:
                d = int(buf[i], 16) if buf[i] in string.hexdigits else base
                if d >= base:
                    break
                value = value * base + d
                digits += 1
                i += 1
                limit *= base
            out.append(byte_char(value) if digits else nx)
            continue
        if nx == "c":
            x = buf[i]
            upper = x.upper() if "a" <= x <= "z" else x
            out.append(chr(ord(upper) ^ 0x40))
            i += 1
            if x == "\\":
                if buf[i:i + 1] != "\\":
                    raise ValueError(
                        "sed: recursive escaping after \\c not allowed")
                i += 1
            continue
        out.append(nx)
    return "".join(out)


def _read_text(rest: str) -> tuple[str, str]:
    """Read the text of ``a``, ``i`` or ``c`` as GNU's read_text does.

    Blanks after the letter are skipped. A backslash there starts the
    classic form: a newline after it is dropped and any other character is
    the text's first, so ``a\\  x`` keeps its leading blanks. The text runs
    to the first newline no backslash escapes (a ``;`` is part of it) and
    keeps that newline. A script that ends on a backslash leaves the text as
    read, undecoded, as GNU keeps text still pending when its script runs
    out.

    Args:
        rest (str): the script right after the command letter.

    Returns:
        tuple[str, str]: the text and the script after it.
    """
    i = 0
    while i < len(rest) and rest[i] in " \t":
        i += 1
    if i >= len(rest):
        raise ValueError("sed: expected \\ after `a', `c' or `i'")
    buf: list[str] = []
    if rest[i] == "\\":
        i += 1
        if i >= len(rest):
            return "", ""
        if rest[i] != "\n":
            buf.append(rest[i])
        i += 1
    while i < len(rest) and rest[i] != "\n":
        if rest[i] == "\\":
            if i + 1 >= len(rest):
                return "".join(buf) + "\n", ""
            buf.append(rest[i:i + 2])
            i += 2
            continue
        buf.append(rest[i])
        i += 1
    return _decode_text_escapes("".join(buf) + "\n"), rest[i:]


def parse_one_command(rest: str) -> tuple[SedCommand, str]:
    addr_start = None
    addr_end = None

    addr_start, rest = _consume_address(rest)
    if addr_start and rest.startswith(","):
        addr_end, rest = _consume_address(rest[1:])

    # Optional address negation: `addr!command` (whitespace allowed around `!`)
    # applies the command to every line the address does NOT select.
    negate = False
    probe = rest.lstrip(" ")
    if probe.startswith("!"):
        negate = True
        rest = probe[1:].lstrip(" ")

    if not rest.strip():
        raise ValueError("sed: missing command")

    ch = rest[0]

    if ch == "{":
        return {
            "cmd": "{",
            "addr_start": addr_start,
            "addr_end": addr_end,
            "negate": negate,
        }, rest[1:]
    if ch == "}":
        return {"cmd": "}"}, rest[1:]
    if ch == ":":
        label = ""
        rest = rest[1:]
        while rest and rest[0] not in (";", "}", "\n"):
            label += rest[0]
            rest = rest[1:]
        return {
            "cmd": ":",
            "label": label.strip(),
        }, rest
    if ch == "b":
        label = ""
        rest = rest[1:]
        while rest and rest[0] not in (";", "}", "\n"):
            label += rest[0]
            rest = rest[1:]
        return {
            "cmd": "b",
            "label": label.strip(),
            "addr_start": addr_start,
            "addr_end": addr_end,
            "negate": negate,
        }, rest
    if ch == "t":
        label = ""
        rest = rest[1:]
        while rest and rest[0] not in (";", "}", "\n"):
            label += rest[0]
            rest = rest[1:]
        return {
            "cmd": "t",
            "label": label.strip(),
            "addr_start": addr_start,
            "addr_end": addr_end,
            "negate": negate,
        }, rest
    if ch == "s":
        delim = rest[1]
        # Read pattern and replacement up to the next delimiter, then consume
        # only the trailing flag characters; anything after is a separate
        # command (a plain split would fold `s/a/b/;d` into the flags).
        idx = 2

        # A backslash escapes the next char (incl. the delimiter: s/a\/b/c/).
        def _field() -> str:
            nonlocal idx
            out: list[str] = []
            while idx < len(rest) and rest[idx] != delim:
                if rest[idx] == "\\" and idx + 1 < len(rest):
                    out.append(rest[idx:idx + 2])
                    idx += 2
                    continue
                out.append(rest[idx])
                idx += 1
            idx += 1
            return "".join(out)

        pattern = _field()
        replacement = _field()
        expr_flags = ""
        while idx < len(rest) and rest[idx] in "0123456789gpiImMe":
            expr_flags += rest[idx]
            idx += 1
        cm = re.search(r"[0-9]+", expr_flags)
        if cm and int(cm.group()) == 0:
            raise ValueError(
                "sed: number option to `s' command may not be zero")
        return {
            "cmd": "s",
            "pattern": pattern,
            "replacement": replacement,
            "expr_flags": expr_flags,
            "addr_start": addr_start,
            "addr_end": addr_end,
            "negate": negate,
        }, rest[idx:]
    if ch == "y":
        # y/src/dst/ — transliterate src[i] -> dst[i]; the two sets must match
        # in length. Read both fields up to the delimiter (no trailing flags).
        delim = rest[1]
        idx = 2

        def _yfield() -> str:
            nonlocal idx
            start = idx
            while idx < len(rest) and rest[idx] != delim:
                idx += 1
            value = rest[start:idx]
            idx += 1
            return value

        pattern = _yfield()
        replacement = _yfield()
        if len(pattern) != len(replacement):
            raise ValueError(
                "sed: strings for `y` command are different lengths")
        return {
            "cmd": "y",
            "pattern": pattern,
            "replacement": replacement,
            "addr_start": addr_start,
            "addr_end": addr_end,
            "negate": negate,
        }, rest[idx:]
    if ch in _SIMPLE_CMDS:
        return {
            "cmd": ch,
            "addr_start": addr_start,
            "addr_end": addr_end,
            "negate": negate,
        }, rest[1:]
    if ch in ("a", "i", "c"):
        text, after = _read_text(rest[1:])
        return {
            "cmd": ch,
            "text": text,
            "addr_start": addr_start,
            "addr_end": addr_end,
            "negate": negate,
        }, after

    raise ValueError(f"sed: unsupported command: {ch!r}")


def parse_program(expr: str) -> list[SedCommand]:
    commands: list[SedCommand] = []
    # Only leading blanks go: trailing ones may belong to a/i/c text.
    rest = expr.lstrip()
    while rest:
        if rest[0] in (";", "\n"):
            rest = rest[1:].lstrip()
            continue
        if rest[0] == " ":
            rest = rest[1:]
            continue
        cmd, rest = parse_one_command(rest)
        commands.append(cmd)
        rest = rest.lstrip()
    # A `}` on the line of an a/i/c text is part of the text, so `1{a x;}`
    # leaves its block open, which GNU refuses.
    depth = 0
    for c in commands:
        if c["cmd"] == "{":
            depth += 1
        elif c["cmd"] == "}":
            depth -= 1
    if depth > 0:
        raise ValueError("sed: unmatched `{'")
    return commands


def bre_to_ere(pat: str) -> str:
    """Translate a POSIX Basic Regular Expression to Extended syntax.

    GNU sed scripts are BRE by default and ERE only under -E/-r. In BRE the
    bare metacharacters ``( ) { } + ? |`` are literal and their backslashed
    forms are special; ERE is the reverse. ``^``/``$`` are anchors only at the
    start/end (literal elsewhere) and a leading ``*`` is literal. The Python
    ``re`` engine is ERE-compatible, so feeding it the translated pattern
    reproduces GNU BRE behavior.
    """
    out: list[str] = []
    i = 0
    n = len(pat)
    # True when the next char begins the regex or a subexpression (after \( or
    # \|), where * is literal and ^ is an anchor.
    at_start = True
    while i < n:
        ch = pat[i]
        if ch == "[":
            out.append("[")
            j = i + 1
            if j < n and pat[j] == "^":
                out.append("^")
                j += 1
            if j < n and pat[j] == "]":
                out.append("]")
                j += 1
            while j < n and pat[j] != "]":
                out.append(pat[j])
                j += 1
            if j < n:
                out.append("]")
                j += 1
            i = j
            at_start = False
            continue
        if ch == "\\":
            nx = pat[i + 1] if i + 1 < n else ""
            if nx == "":
                out.append("\\")
                i += 1
                continue
            if nx in "(){}+?|":
                out.append(nx)
                at_start = nx in "(|"
                i += 2
                continue
            out.append("\\" + nx)
            at_start = False
            i += 2
            continue
        if ch in "(){}+?|":
            out.append("\\" + ch)
            at_start = False
            i += 1
            continue
        if ch == "*":
            out.append("\\*" if at_start else "*")
            at_start = False
            i += 1
            continue
        if ch == "^":
            out.append("^" if at_start else "\\^")
            i += 1
            continue
        if ch == "$":
            is_end = (i == n - 1 or (pat[i + 1] == "\\" and i + 2 < n
                                     and pat[i + 2] in ")|"))
            out.append("$" if is_end else "\\$")
            at_start = False
            i += 1
            continue
        out.append(ch)
        at_start = False
        i += 1
    return "".join(out)


def _re_pattern(pat: str, extended: bool) -> str:
    return translate_classes(pat if extended else bre_to_ere(pat), extended)


def _addr_matches(addr: tuple[str, str],
                  line: str,
                  lineno: int,
                  total: int,
                  extended: bool = False) -> bool:
    kind, val = addr
    if kind == "line":
        return lineno == int(val)
    if kind == "last":
        return lineno == total
    if kind == "regex":
        return compile_posix_regex(_re_pattern(
            val, extended)).search(line) is not None
    return False


def _split_content_lines(text: str) -> tuple[list[str], bool]:
    """Line contents WITHOUT trailing newlines (the pattern space excludes the
    separator). The bool records whether the last line ended with a newline, so
    output can preserve a missing final newline. Splits only on ``\\n``."""
    if text == "":
        return [], False
    final_newline = text.endswith("\n")
    body = text[:-1] if final_newline else text
    return body.split("\n"), final_newline


def _text_line(text: str) -> str:
    """Render the text of ``i`` or ``c`` as GNU's output_line does.

    ``a`` writes its text as read, closing newline included; ``i`` and
    ``c`` write all of it but the last character and then a newline, and
    nothing for an empty text (``a\\`` ending the script).

    Args:
        text (str): the command's text, closing newline included.

    Returns:
        str: the text to write.
    """
    return text[:-1] + "\n" if text else ""


def execute_program(text: str,
                    commands: list[SedCommand],
                    suppress: bool = False,
                    extended: bool = False) -> str:
    lines, final_newline = _split_content_lines(text)
    total = len(lines)
    hold = ""
    output: list[str] = []
    label_map: dict[str, int] = {}
    for idx, cmd in enumerate(commands):
        if cmd["cmd"] == ":":
            label_map[cmd["label"]] = idx
    range_active: dict[int, bool] = {}

    # Trailing newline for a pattern space whose last consumed line is `ln`
    # (1-based): every line gets one except a last line that had none on input.
    def tail_nl(ln: int) -> str:
        return "\n" if (ln < total or final_newline) else ""

    i = 0
    while i < total:
        pattern = lines[i]
        i += 1
        lineno = i
        deferred: list[str] = []

        pc = 0
        delete = False
        substituted = False

        while pc < len(commands):
            cmd = commands[pc]
            c = cmd["cmd"]

            if c == ":" or c == "}":
                pc += 1
                continue

            addr_start = cmd.get("addr_start")
            addr_end = cmd.get("addr_end")

            matched = True
            if addr_start is not None:
                if addr_end is not None:
                    rid = id(cmd)
                    if not range_active.get(rid, False):
                        if _addr_matches(addr_start, pattern, lineno, total,
                                         extended):
                            range_active[rid] = True
                        else:
                            matched = False
                    if range_active.get(rid, False):
                        if _addr_matches(addr_end, pattern, lineno, total,
                                         extended):
                            range_active[rid] = False
                else:
                    if not _addr_matches(addr_start, pattern, lineno, total,
                                         extended):
                        matched = False

            # addr!cmd inverts the selection (range state tracked normally).
            if cmd.get("negate"):
                matched = not matched

            if c == "{":
                if not matched:
                    depth = 1
                    pc += 1
                    while pc < len(commands) and depth > 0:
                        if commands[pc]["cmd"] == "{":
                            depth += 1
                        elif commands[pc]["cmd"] == "}":
                            depth -= 1
                        pc += 1
                    continue
                pc += 1
                continue

            if not matched:
                pc += 1
                continue

            if c == "s":
                pat = cmd["pattern"]
                repl = cmd["replacement"]
                eflags = cmd["expr_flags"]
                re_flags = re.IGNORECASE if "i" in eflags.lower() else 0
                # `nth` is the 1-based occurrence the substitution starts at
                # (GNU sed's numeric s///N flag, default 1). Without `g` only
                # that occurrence is replaced; with `g` that one and every
                # later one are. Count matches and decide per match so both
                # `N` and `Ng` work. An empty match touching the previous
                # match is no match at all, so `s/b*/X/g` turns "abbb" into
                # "XaX", not "XaXX".
                digits = re.search(r"[0-9]+", eflags)
                nth = int(digits.group()) if digits else 1
                global_ = "g" in eflags
                counter = [0]
                last_end = [-1]
                replaced = [False]

                # Defaults bind the per-command values early (the closure is
                # defined inside the command loop and used immediately).
                def _repl(m: "re.Match[str]",
                          _repl_s: str = repl,
                          _nth: int = nth,
                          _global: bool = global_,
                          _counter: list[Any] = counter,
                          _last_end: list[int] = last_end) -> str:
                    if m.start() == m.end() == _last_end[0]:
                        return ""
                    if m.end() > m.start():
                        _last_end[0] = m.end()
                    _counter[0] += 1
                    hit = (_counter[0] >= _nth
                           if _global else _counter[0] == _nth)
                    if hit:
                        replaced[0] = True
                    return _apply_repl(m, repl=_repl_s) if hit else m.group(0)

                new_pattern = compile_posix_regex(_re_pattern(pat, extended),
                                                  re_flags).sub(
                                                      _repl, pattern)
                changed = replaced[0]
                if changed:
                    substituted = True
                pattern = new_pattern
                # s///p prints the pattern space when a substitution was made.
                if changed and "p" in eflags:
                    output.append(pattern + tail_nl(lineno))
            elif c == "d":
                delete = True
                break
            elif c == "D":
                nl = pattern.find("\n")
                if nl >= 0:
                    pattern = pattern[nl + 1:]
                    pc = 0
                    continue
                delete = True
                break
            elif c == "p":
                output.append(pattern + tail_nl(lineno))
            elif c == "P":
                nl = pattern.find("\n")
                output.append(pattern[:nl + 1] if nl >= 0 else pattern +
                              tail_nl(lineno))
            elif c == "N":
                if i < total:
                    pattern += "\n" + lines[i]
                    i += 1
                    lineno = i
                else:
                    break
            elif c == "h":
                hold = pattern
            elif c == "H":
                # GNU appends newline + pattern unconditionally (empty hold ->
                # leading newline).
                hold = hold + "\n" + pattern
            elif c == "g":
                pattern = hold
            elif c == "G":
                # GNU appends newline + hold unconditionally (empty hold ->
                # blank line).
                pattern = pattern + "\n" + hold
            elif c == "x":
                pattern, hold = hold, pattern
            elif c == "a":
                deferred.append(cmd["text"])
            elif c == "i":
                output.append(_text_line(cmd["text"]))
            elif c == "y":
                # Transliterate pattern[i] -> replacement[i].
                pattern = pattern.translate(
                    str.maketrans(cmd["pattern"], cmd["replacement"]))
            elif c == "c":
                # Change: delete the pattern space and emit the text. For a
                # single address (or none) emit on each match; for a range emit
                # once, when the range closes (or at EOF), matching GNU sed.
                delete = True
                is_range = addr_end is not None
                range_open = range_active.get(id(cmd), False)
                if (not is_range) or (not range_open) or (lineno == total):
                    output.append(_text_line(cmd["text"]))
                break
            elif c == "q":
                output.append(pattern + tail_nl(lineno))
                return "".join(output)
            elif c == "b":
                label = cmd.get("label", "")
                if label and label in label_map:
                    pc = label_map[label]
                    continue
                break
            elif c == "t":
                if substituted:
                    substituted = False
                    label = cmd.get("label", "")
                    if label and label in label_map:
                        pc = label_map[label]
                        continue
                    break

            pc += 1

        if not delete:
            if not suppress:
                output.append(pattern + tail_nl(lineno))
            output.extend(deferred)

    return "".join(output)

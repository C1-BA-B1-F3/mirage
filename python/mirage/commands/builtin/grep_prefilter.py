import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class _Required:
    exact: str | None = None
    needles: tuple[str, ...] = ()


def _literal(text: str) -> _Required:
    return _Required(text, (text, ) if text else ())


def _sequence(parts: list[_Required]) -> _Required:
    run = ""
    candidates: list[tuple[str, ...]] = []
    for part in parts:
        if part.exact is not None:
            run += part.exact
        else:
            if run:
                candidates.append((run, ))
            run = ""
            if part.needles:
                candidates.append(part.needles)
    if run:
        candidates.append((run, ))
    exact = "".join(p.exact for p in parts if p.exact is not None)
    if all(p.exact is not None for p in parts):
        return _literal(exact)
    return _Required(needles=max(candidates, key=_strength, default=()))


def _strength(needles: tuple[str, ...]) -> int:
    return min(map(len, needles))


class _Parser:

    def __init__(self, source: str) -> None:
        self.source = source
        self.at = 0
        self.safe = True

    def expression(self, depth: int = 0) -> _Required:
        if depth > 32:
            self.safe = False
            return _Required()
        branches: list[_Required] = []
        parts: list[_Required] = []
        while self.at < len(self.source) and self.safe:
            char = self.source[self.at]
            if char == ")":
                break
            self.at += 1
            if char == "|":
                branches.append(_sequence(parts))
                parts = []
                continue
            atom = _Required()
            if char == "(":
                assertion = False
                if self.source.startswith(("?=", "?!", "?<=", "?<!"), self.at):
                    assertion = True
                    self.at += 3 if self.source.startswith("?<",
                                                           self.at) else 2
                elif self.source.startswith("?:", self.at):
                    self.at += 2
                elif self.source.startswith("?", self.at):
                    self.safe = False
                    break
                atom = self.expression(depth + 1)
                if self.at >= len(self.source) or self.source[self.at] != ")":
                    self.safe = False
                    break
                self.at += 1
                if assertion:
                    atom = _Required()
            elif char == "[":
                if self.source[self.at:self.at + 1] == "^":
                    self.at += 1
                if self.source[self.at:self.at + 1] == "]":
                    self.at += 1
                while self.at < len(
                        self.source) and self.source[self.at] != "]":
                    self.at += 2 if self.source[self.at] == "\\" else 1
                self.at += 1
            elif char == "\\":
                escaped = self.source[self.at:self.at + 1]
                self.at += 1
                if escaped not in ("b", "B", "A", "Z", "z", "d", "D", "s", "S",
                                   "w", "W"):
                    if escaped and not escaped.isalnum(
                    ) and " " <= escaped <= "~":
                        atom = _literal(escaped)
                    else:
                        self.safe = False
                        break
            elif char in "*+?{}":
                self.safe = False
                break
            elif char not in ".^$" and " " <= char <= "~":
                atom = _literal(char)
            quantifier = self.source[self.at:self.at + 1]
            if quantifier and quantifier in "*+?":
                self.at += 1
                atom = _Required(
                    needles=atom.needles if quantifier == "+" else ())
            elif quantifier == "{":
                repeat = re.match(r"\{([0-9]+)(?:,([0-9]*))?\}",
                                  self.source[self.at:])
                if repeat is None:
                    self.safe = False
                    break
                self.at += repeat.end()
                atom = _Required(
                    needles=atom.needles if int(repeat[1]) > 0 else ())
            if self.at < len(self.source) and self.source[
                    self.at] in "?+" and quantifier in "*+?{":
                self.at += 1
            parts.append(atom)
        branches.append(_sequence(parts))
        if len(branches) == 1:
            return branches[0]
        if any(not b.needles for b in branches):
            return _Required()
        needles = tuple(dict.fromkeys(n for b in branches for n in b.needles))
        return _Required(needles=needles if len(needles) <= 64 else ())


@lru_cache(maxsize=256)
def required_literal(pat: re.Pattern[str]) -> bytes | re.Pattern[bytes] | None:
    """Build a necessary (never sufficient) byte test for a line match.

    Concatenation keeps its strongest required run; alternation must retain
    a candidate from every branch. Optional atoms contribute nothing.
    Unsupported syntax disables the optimization, never the full matcher.
    The bounded parser ignores lookaround constraints and rejects inline
    flags, backreferences and encoded escapes.

    Args:
        pat (re.Pattern[str]): the authoritative decoded-line matcher.
    """
    if pat.flags & re.VERBOSE:
        return None
    parser = _Parser(pat.pattern)
    needles = parser.expression().needles
    if not parser.safe or parser.at != len(pat.pattern) or not needles:
        return None
    if not pat.flags & re.IGNORECASE and len(needles) == 1:
        return needles[0].encode("ascii")
    alternatives = [re.escape(n.encode("ascii")) for n in needles]
    if pat.flags & re.IGNORECASE and not pat.flags & re.ASCII:
        # Python's Unicode case folding adds these four characters to ASCII.
        # Keep their lines for the matcher, even in invalid UTF-8.
        letters = "".join(needles).lower()
        for letter, folds in (("s", "ſ"), ("k", "K"), ("i", "İı")):
            if letter in letters:
                alternatives.extend(re.escape(c.encode()) for c in folds)
    return re.compile(
        b"|".join(alternatives),
        re.ASCII | (re.IGNORECASE if pat.flags & re.IGNORECASE else 0))

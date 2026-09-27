import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Required:
    literal: str | None
    needles: tuple[str, ...]


UNKNOWN = Required(None, ())
QUANTIFIER = re.compile(r"(?:[?*+]|\{([0-9]+)(?:,[0-9]*)?\})")


def literal(text: str) -> Required:
    return Required(text, (text, ) if text else ())


def strength(needles: tuple[str, ...]) -> int:
    return min(map(len, needles), default=0)


class RequiredLiterals:
    """A bounded partial parser: unsupported syntax disables skipping."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.at = 0
        self.valid = True

    def peek(self) -> str:
        return self.source[self.at:self.at + 1]

    def parse(self, depth: int = 0) -> Required:
        if depth > 32:
            self.valid = False
            return UNKNOWN
        branches: list[Required] = []
        best: tuple[str, ...] = ()
        run = ""
        exact: str | None = ""
        while self.at < len(self.source) and self.peek() != ")":
            if self.peek() == "|":
                branches.append(Required(exact, best))
                best, run, exact = (), "", ""
                self.at += 1
                continue
            atom = self.atom(depth)
            if not self.valid:
                return UNKNOWN
            quantifier = QUANTIFIER.match(self.source, self.at)
            if quantifier is not None:
                self.at = quantifier.end()
                optional = quantifier[0][0] in "?*" or (
                    quantifier[1] is not None and not quantifier[1].strip("0"))
                atom = UNKNOWN if optional else Required(None, atom.needles)
                if self.peek() == "?":
                    self.at += 1
            exact = (exact + atom.literal if exact is not None
                     and atom.literal is not None else None)
            run = "" if atom.literal is None else run + atom.literal
            candidate = (run, ) if run else atom.needles
            if strength(candidate) > strength(best):
                best = candidate
        branches.append(Required(exact, best))
        if depth == 0 and self.at != len(self.source):
            self.valid = False
        if len(branches) == 1:
            return branches[0]
        if any(not branch.needles for branch in branches):
            return UNKNOWN
        needles = tuple(dict.fromkeys(n for b in branches for n in b.needles))
        return Required(None, needles) if len(needles) <= 64 else UNKNOWN

    def atom(self, depth: int) -> Required:
        char = self.peek()
        self.at += 1
        if char == "(":
            assertion = False
            if self.source.startswith(("?=", "?!", "?<=", "?<!"), self.at):
                assertion = True
                self.at += 3 if self.source.startswith("?<", self.at) else 2
            elif self.source.startswith("?:", self.at):
                self.at += 2
            elif self.peek() == "?":
                self.valid = False
                return UNKNOWN
            group = self.parse(depth + 1)
            if self.peek() != ")":
                self.valid = False
            self.at += 1
            return UNKNOWN if assertion else group
        if char == "[":
            if self.peek() == "^":
                self.at += 1
            if self.peek() == "]":
                self.at += 1
            while self.at < len(self.source):
                member = self.peek()
                self.at += 1
                if member == "]":
                    return UNKNOWN
                if member == "\\":
                    self.at += 1
                if member == "[":
                    break
            self.valid = False
            return UNKNOWN
        if char == "\\":
            escaped = self.peek()
            self.at += 1
            if escaped and escaped in "bB":
                return literal("")
            if escaped and escaped in "dDsSwWnrtfv":
                return UNKNOWN
            if escaped and not escaped.isalnum():
                return literal(escaped)
            self.valid = False
            return UNKNOWN
        if char == ".":
            return UNKNOWN
        if char in "^$":
            return literal("")
        if char in "*+?{}":
            self.valid = False
            return UNKNOWN
        return literal(char)


def required_needles(pat: re.Pattern[str]) -> tuple[bytes, ...] | None:
    """Find byte literals, at least one of which every matching line contains.

    Args:
        pat (re.Pattern[str]): the compiled line matcher.
    """
    if (pat.flags & re.VERBOSE or len(pat.pattern) > 4096
            or any(not " " <= char <= "~" for char in pat.pattern)):
        return None
    parser = RequiredLiterals(pat.pattern)
    required = parser.parse().needles
    if not parser.valid or not required:
        return None
    needles = [text.encode("ascii") for text in required]
    if pat.flags & re.IGNORECASE:
        needles = [text.lower() for text in needles]
        # Python's Unicode IGNORECASE includes four non-ASCII ASCII spellings.
        if not pat.flags & re.ASCII:
            for letter, spelling in [(b"s", "ſ"), (b"k", "K"), (b"i", "İ"),
                                     (b"i", "ı")]:
                if any(letter in needle for needle in needles):
                    needles.append(spelling.encode())
    return tuple(needles)

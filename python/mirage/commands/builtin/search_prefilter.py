import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Summary:
    # exact is the consumed text, when fixed; needles is a disjunction that
    # every match must contain. An empty disjunction gives no information.
    exact: str | None
    needles: tuple[str, ...]


UNKNOWN = Summary(None, ())
EMPTY = Summary('', ())
LIMIT = 64


def literal(text: str) -> Summary:
    return Summary(text, (text, ) if text else ())


def score(part: Summary) -> int:
    return min(map(len, part.needles), default=0)


def sequence(left: Summary, right: Summary) -> Summary:
    if left.exact is not None and right.exact is not None:
        return literal(left.exact + right.exact)
    return Summary(None,
                   (left if score(left) >= score(right) else right).needles)


def alternative(left: Summary, right: Summary) -> Summary:
    if left.exact is not None and left.exact == right.exact:
        return left
    if not left.needles or not right.needles:
        return UNKNOWN
    needles = tuple(dict.fromkeys(left.needles + right.needles))
    return Summary(None, needles) if len(needles) <= LIMIT else UNKNOWN


class Literals:
    # Necessary conditions only: unknown syntax disables the filter.
    def __init__(self, source: str) -> None:
        self.source = source
        self.at = 0
        self.safe = True

    def peek(self) -> str:
        return self.source[self.at:self.at + 1]

    def read(self) -> tuple[str, ...]:
        result = self.expression(0)
        return result.needles if self.safe and self.at == len(
            self.source) else ()

    def expression(self, depth: int) -> Summary:
        if depth > LIMIT:
            self.safe = False
            return UNKNOWN
        result = self.concatenation(depth)
        while self.safe and self.peek() == '|':
            self.at += 1
            result = alternative(result, self.concatenation(depth))
        return result

    def concatenation(self, depth: int) -> Summary:
        result = run = EMPTY
        while self.safe and self.peek() and self.peek() not in ')|':
            atom = self.atom(depth)
            next_char = self.peek()
            if next_char and next_char in '*+?{':
                self.at += 1
                required = next_char == '+'
                if next_char == '{':
                    match = re.match(r'(\d+)(?:,(\d*)?)?\}',
                                     self.source[self.at:])
                    if match is None:
                        self.safe = False
                        return UNKNOWN
                    required = int(match[1]) > 0
                    self.at += len(match[0])
                atom = Summary(None, atom.needles) if required else UNKNOWN
                if self.peek() == '?':
                    self.at += 1
            if atom.exact is not None:
                run = sequence(run, atom)
            else:
                result = sequence(sequence(result, run), atom)
                run = EMPTY
        return sequence(result, run)

    def atom(self, depth: int) -> Summary:
        char = self.peek()
        self.at += 1
        if char == '(':
            assertion = next((prefix for prefix in ('?=', '?!', '?<=', '?<!')
                              if self.source.startswith(prefix, self.at)),
                             None)
            if assertion is not None:
                self.at += len(assertion)
            elif self.source.startswith('?:', self.at):
                self.at += 2
            elif self.peek() == '?':
                self.safe = False
                return UNKNOWN
            value = self.expression(depth + 1)
            if self.peek() != ')':
                self.safe = False
            self.at += 1
            return value if assertion is None else EMPTY
        if char == '[':
            if self.peek() == '^':
                self.at += 1
            if self.peek() == ']':
                self.safe = False
                return UNKNOWN
            while self.at < len(self.source):
                member = self.peek()
                self.at += 1
                if member == ']':
                    return UNKNOWN
                if member == '\\':
                    self.at += 1
            self.safe = False
            return UNKNOWN
        if char == '\\':
            escaped = self.peek()
            self.at += 1
            if escaped and escaped in 'bB':
                return EMPTY
            if escaped and escaped in 'dDsSwW':
                return UNKNOWN
            if not escaped or escaped.isalnum():
                self.safe = False
                return UNKNOWN
            return literal(escaped)
        if char == '.':
            return UNKNOWN
        if char in '^$':
            return EMPTY
        if char in '*+?{}':
            self.safe = False
            return UNKNOWN
        return literal(char)


def search_prefilter(pat: re.Pattern[str]) -> bytes | re.Pattern[bytes] | None:
    """Build a necessary byte search, leaving matching to the line regex.

    Args:
        pat (re.Pattern[str]): the compiled line matcher.
    """
    if pat.flags & re.VERBOSE or any(not ' ' <= c <= '~' for c in pat.pattern):
        return None
    needles = Literals(pat.pattern).read()
    if not needles:
        return None
    if not pat.flags & re.IGNORECASE and len(needles) == 1:
        return needles[0].encode('ascii')
    alternatives = [re.escape(s.encode('ascii')) for s in needles]
    # Preserve Unicode folding by retaining all non-ASCII candidate lines.
    if pat.flags & re.IGNORECASE and not pat.flags & re.ASCII:
        alternatives.append(rb'[\x80-\xff]')
    return re.compile(b'|'.join(alternatives), pat.flags & re.IGNORECASE)

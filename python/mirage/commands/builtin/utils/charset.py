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

from dataclasses import dataclass

MAX_CODE_POINT = 0x10FFFF
SURROGATE_LOW = 0xD800
SURROGATE_HIGH = 0xDFFF

# The characters a host pattern must escape to mean themselves, outside
# and inside a bracket expression. Both are the subset python `re` and
# JavaScript's `u`-flag `RegExp` agree on: under `u` an identity escape
# is only legal for a syntax character, so nothing else is escaped.
OUTSIDE_SPECIAL = "\\^$.|?*+()[]{}/"
INSIDE_SPECIAL = "\\]^-["

Range = tuple[int, int]


@dataclass(frozen=True, slots=True)
class CharSet:
    """A set of code points as sorted, disjoint, non-adjacent ranges.

    The algebra a character class needs -- union, intersection,
    difference, symmetric difference and negation -- done on the ranges
    rather than left to the host, which spells none of the set operations
    and whose own negation also matches a lone surrogate. Negation is
    over the Unicode scalar values, as a Rust or PCRE2 class is, so a
    surrogate (an undecodable byte in mirage's text) is never a member of
    a negated class.

    Args:
        ranges (tuple[Range, ...]): inclusive ``(low, high)`` pairs.
    """
    ranges: tuple[Range, ...] = ()

    @staticmethod
    def of(*ranges: Range) -> "CharSet":
        """The set of the given ranges, normalized.

        Args:
            *ranges (Range): inclusive ``(low, high)`` pairs, any order.
        """
        merged: list[list[int]] = []
        for low, high in sorted(r for r in ranges if r[0] <= r[1]):
            if merged and low <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])
        return CharSet(tuple((low, high) for low, high in merged))

    @staticmethod
    def chars(*code_points: int) -> "CharSet":
        """The set of the given code points.

        Args:
            *code_points (int): the members.
        """
        return CharSet.of(*((cp, cp) for cp in code_points))

    def union(self, other: "CharSet") -> "CharSet":
        """Every code point in either set.

        Args:
            other (CharSet): the other operand.
        """
        return CharSet.of(*self.ranges, *other.ranges)

    def negate(self) -> "CharSet":
        """Every scalar value not in the set."""
        out: list[Range] = []
        low = 0
        for start, end in self.ranges:
            if start > low:
                out.append((low, start - 1))
            low = end + 1
        if low <= MAX_CODE_POINT:
            out.append((low, MAX_CODE_POINT))
        return CharSet.of(*out).minus_surrogates()

    def minus_surrogates(self) -> "CharSet":
        """The set without the surrogate block."""
        out: list[Range] = []
        for low, high in self.ranges:
            if high < SURROGATE_LOW or low > SURROGATE_HIGH:
                out.append((low, high))
                continue
            if low < SURROGATE_LOW:
                out.append((low, SURROGATE_LOW - 1))
            if high > SURROGATE_HIGH:
                out.append((SURROGATE_HIGH + 1, high))
        return CharSet(tuple(out))

    def intersect(self, other: "CharSet") -> "CharSet":
        """Every code point in both sets.

        Args:
            other (CharSet): the other operand.
        """
        out: list[Range] = []
        i = j = 0
        while i < len(self.ranges) and j < len(other.ranges):
            low = max(self.ranges[i][0], other.ranges[j][0])
            high = min(self.ranges[i][1], other.ranges[j][1])
            if low <= high:
                out.append((low, high))
            if self.ranges[i][1] < other.ranges[j][1]:
                i += 1
            else:
                j += 1
        return CharSet(tuple(out))

    def minus(self, other: "CharSet") -> "CharSet":
        """Every code point in this set and not the other.

        Args:
            other (CharSet): the set to take away.
        """
        return self.intersect(other.negate().union(self.surrogates()))

    def xor(self, other: "CharSet") -> "CharSet":
        """Every code point in exactly one of the sets.

        Args:
            other (CharSet): the other operand.
        """
        return self.minus(other).union(other.minus(self))

    def surrogates(self) -> "CharSet":
        """The part of this set inside the surrogate block."""
        return self.intersect(CharSet.of((SURROGATE_LOW, SURROGATE_HIGH)))

    def contains(self, cp: int) -> bool:
        """Whether a code point is a member.

        Args:
            cp (int): the code point.
        """
        low, high = 0, len(self.ranges)
        while low < high:
            mid = (low + high) // 2
            start, end = self.ranges[mid]
            if cp < start:
                high = mid
            elif cp > end:
                low = mid + 1
            else:
                return True
        return False

    def is_empty(self) -> bool:
        """Whether the set has no member."""
        return not self.ranges

    def single(self) -> int | None:
        """The one member of a one-member set, else None."""
        if len(self.ranges) == 1 and self.ranges[0][0] == self.ranges[0][1]:
            return self.ranges[0][0]
        return None


ALL = CharSet.of((0, MAX_CODE_POINT)).minus_surrogates()
EMPTY = CharSet()


def host_code_point(cp: int) -> str:
    """One code point as python ``re`` source reads it inside or out.

    Args:
        cp (int): the code point.
    """
    if cp <= 0xFF:
        return "\\x%02x" % cp
    if cp <= 0xFFFF:
        return "\\u%04x" % cp
    return "\\U%08x" % cp


def host_char(cp: int) -> str:
    """One literal code point outside a bracket expression.

    Printable ASCII stays readable (the grep prefilter reads host source
    for its needles and gives up at an escaped letter); everything else
    is a numeric escape.

    Args:
        cp (int): the code point.
    """
    if 0x20 <= cp <= 0x7E:
        ch = chr(cp)
        return "\\" + ch if ch in OUTSIDE_SPECIAL else ch
    return host_code_point(cp)


def class_member(cp: int) -> str:
    """One code point inside a host bracket expression.

    Args:
        cp (int): the code point.
    """
    if 0x20 <= cp <= 0x7E:
        ch = chr(cp)
        return "\\" + ch if ch in INSIDE_SPECIAL else ch
    return host_code_point(cp)


def class_body(ranges: tuple[Range, ...]) -> str:
    """The members of a host bracket expression for some ranges.

    Args:
        ranges (tuple[Range, ...]): inclusive ranges.
    """
    parts: list[str] = []
    for low, high in ranges:
        if low == high:
            parts.append(class_member(low))
        elif high == low + 1:
            parts.append(class_member(low) + class_member(high))
        else:
            parts.append(class_member(low) + "-" + class_member(high))
    return "".join(parts)


def host_class(cs: CharSet) -> str:
    """A set as one host atom that matches exactly its members.

    The shorter of the positive and the negated spelling; the negated one
    names the surrogate block among the excluded, so a host that reads a
    lone surrogate as a character still never matches one.

    Args:
        cs (CharSet): the members.
    """
    single = cs.single()
    if single is not None:
        return host_char(single)
    if cs.is_empty():
        return "[^" + class_body(((0, MAX_CODE_POINT), )) + "]"
    complement = cs.negate()
    if len(complement.ranges) < len(cs.ranges):
        excluded = complement.union(CharSet.of(
            (SURROGATE_LOW, SURROGATE_HIGH)))
        return "[^" + class_body(excluded.ranges) + "]"
    return "[" + class_body(cs.ranges) + "]"

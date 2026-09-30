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
from collections.abc import Sequence

from dulwich.config import ConfigFile

from mirage.commands.cli.builtin.git.constants import HEAD
from mirage.commands.cli.builtin.git.errors import (  # yapf: disable
    BadConfigValueError, GitError, UnrecognizedArgumentError)
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.stream import yield_bytes
from mirage.io.types import ByteSource, IOResult
from mirage.ops.types import LinkView, MountView

ROOT = "/"
STDOUT = "stdout"
# The end-of-options marker, which the parser consumes.
MARKER = "--"
TRUE_WORDS = (b"true", b"yes", b"on")
FALSE_WORDS = (b"false", b"no", b"off", b"")
# git_parse_signed: strtoimax in base 0 after C-locale space, then at most
# one unit, and the product has to fit an int.
INTEGER = re.compile(rb"[ \t\n\v\f\r]*([-+]?)"
                     rb"(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)([kKmMgG]?)")
UNIT_SHIFTS = {b"": 0, b"k": 10, b"m": 20, b"g": 30}
INT_BITS = 31
VALUE_ESCAPES = {"\n": "\\n", "\t": "\\t", '"': '\\"', "\\": "\\\\"}
COMMENT_STARTS = (";", "#")
SECTION_HEADER = re.compile(
    rb'[ \t]*\[[ \t]*([A-Za-z0-9.-]+)(?:[ \t]+"((?:[^"\\]|\\.)*)")?[ \t]*\]')
ESCAPED = re.compile(rb"\\(.)")


def links_of(doors: CLIDoors) -> LinkView | None:
    """The name plane's link facts, None when no namespace is wired.

    git walks the working tree itself rather than through a generic, so
    it is one of the bespoke commands that has to ask for links or
    silently cannot see one: without this a symlink reads as whatever
    it points at, and a link to nothing reads as absent.

    Args:
        doors (CLIDoors): the invocation's doors, one per state plane.
    """
    return doors.ns.links if doors.ns is not None else None


def mounts_of(doors: CLIDoors) -> MountView | None:
    """The name plane's mount boundaries, None when no namespace is wired.

    A mount nested inside the repository is served by another VFS
    entirely, so the backend holding the parent path cannot see it and
    cannot carry it along in a rename. A verb that moves a directory has
    to ask here or it silently leaves the mount at its old prefix with
    the index pointing at files that never moved.

    Args:
        doors (CLIDoors): the invocation's doors, one per state plane.
    """
    return doors.ns.mounts if doors.ns is not None else None


def start_point(fl: FlagView) -> str:
    """Where repository discovery begins for this invocation.

    ``-C`` changes directory before anything else happens, git's own
    reading of the option. It needs no separate session-cwd fact: the
    option is declared with a ``"."`` default, and a PATH default lands
    as if typed, so an absent ``-C`` resolves to the session cwd and a
    relative ``-C build`` is already absolute by the time it arrives.

    Read as a string, not a PathSpec: group-level values are resolved by
    the walk and reach a leaf as absolute virtual paths, while a leaf's
    own PATH flags are recovered as PathSpec by ``parse_flags``.

    Args:
        fl (FlagView): spec-validated view over the leaf's flag bag.
    """
    return fl.as_str("C") or ROOT


def revision_arg(texts: tuple[str, ...], default: str = HEAD) -> str:
    """The revision operand a verb was given, or git's own default.

    Args:
        texts (tuple[str, ...]): positional text operands.
        default (str): what an absent operand means.
    """
    return texts[0] if texts else default


def escaped(argv: tuple[str, ...]) -> frozenset[str]:
    """The words a ``--`` on the line marked as operands, not options.

    ``--`` is exactly how a caller names a file whose name begins with a
    dash, and git says so in every synopsis that ends
    ``[--] [<pathspec>...]``: ``git rm -draft`` is a refused switch and
    ``git rm -- -draft`` removes the file. The parser consumes the
    marker, so the words themselves are what carries the fact forward,
    read back off the verbatim argv the record already holds.

    A set is enough. A dash word before the marker was read as an
    option and never reached the operands, so a word that is here and
    also spelled earlier on the line is still the escaped one.

    Args:
        argv (tuple[str, ...]): the line's verbatim tokens after the
            head word, subcommand words included.
    """
    if MARKER not in argv:
        return frozenset()
    return frozenset(argv[argv.index(MARKER) + 1:])


def switches(inv: CLIInvocation[None]) -> frozenset[str]:
    """The one-letter switches the leaf declares, without their dash.

    Read off the spec the line was parsed against, so the set is the
    verb's own and never a copy of it; empty where no executor built
    the record.

    Args:
        inv (CLIInvocation): the invocation, carrying its leaf.
    """
    if inv.spec is None:
        return frozenset()
    return frozenset(option.short[1:] for option in inv.spec.options
                     if option.short is not None and len(option.short) == 2)


def offending_switch(text: str, known: frozenset[str] | None) -> str:
    """The part of a dash word parse-options would refuse.

    git reads a short cluster letter by letter, consumes the ones the
    verb declares and stops at the first it does not, so ``git mv -nx``
    says `x' and ``git mv -draft`` says `d' (git 2.50.1); a verb that
    declares no switch at all (``reset``) still names the first letter.
    A long option is refused as typed, and so is a cluster for a verb
    that hands over no set: log, show and diff word the whole argument.

    Args:
        text (str): the dash word as the user spelled it.
        known (frozenset[str] | None): the verb's one-letter switches,
            None for a verb that refuses the word whole.
    """
    if known is None or text.startswith("--"):
        return text
    for letter in text[1:]:
        if letter not in known:
            return f"-{letter}"
    return text


def check_operands(
    texts: tuple[str, ...],
    error: type[GitError] = UnrecognizedArgumentError,
    marked: frozenset[str] = frozenset(),
    known: frozenset[str] | None = None,
) -> None:
    """Refuse an operand that is really an option this build lacks.

    A verb taking a revision accepts free text, so every flag mirage
    does not declare reaches it as one. Resolving it as a revision is
    the wrong answer twice over: it fails, and it fails saying the
    repository has no such commit, when what happened is that mirage
    has no such flag. Refused here, before any object is read, so the
    message names the real problem.

    Unless the caller said otherwise. A word after ``--`` is an operand
    by the caller's own instruction whatever it starts with, so it is
    never read as an option here; see ``escaped``, which is where the
    marker survives the parser.

    Which side of the marker an operand fell on says nothing about what
    it *means*: a verb taking a revision reads an escaped word as one
    and fails with git's own "unknown revision or path" wording, where
    git would narrow the walk by it instead. That divergence is
    unchanged and deliberate, because limiting by nothing would print
    every commit and look like an answer.

    Which refusal to raise is the caller's, because git words this
    differently per verb and means each one: see ``UnknownSwitchError``
    for the three.

    Args:
        texts (tuple[str, ...]): positional text operands, as typed.
        error (type[GitError]): the refusal this verb words it with.
        marked (frozenset[str]): operands a ``--`` on the line escaped.
        known (frozenset[str] | None): the verb's one-letter switches,
            which narrow a refused cluster to its first unknown letter
            the way parse-options does; None refuses the whole word.
    """
    for text in texts:
        if text.startswith("-") and text not in marked:
            raise error(offending_switch(text, known))


def fatal(exc: GitError) -> tuple[ByteSource | None, IOResult]:
    """Render a git error: ``<prefix>: <message>``, on its own stream.

    git uses 128 for a fatal, which is neither the dispatcher's usage
    exit (2) nor its generic handler-error exit (1), so leaves return
    the code rather than raising into the catch-all. A refused option
    carries its own prefix and code instead, which is git's own split,
    and a refusal that is really a report ("nothing to commit") carries
    no prefix and goes to stdout.

    An error carrying a ``report`` puts that on stdout beside the
    stderr line, because git writes some refusals to both streams at
    once: ``<path>: needs merge`` is the diagnosis and "you need to
    resolve your current index first" is the refusal.

    Args:
        exc (GitError): the error to render.
    """
    body = f"{exc}\n" if exc.prefix is None else f"{exc.prefix}: {exc}\n"
    data = body.encode()
    if exc.stream == STDOUT:
        return yield_bytes(data), IOResult(exit_code=exc.code)
    told = yield_bytes(exc.report.encode()) if exc.report else None
    return told, IOResult(exit_code=exc.code, stderr=data)


def git_bool(values: Sequence[bytes], key: str, default: bool) -> bool:
    """A config boolean read the way git's config callbacks read one.

    Every occurrence is parsed and the last one wins, so a value git
    cannot read fails even when a later line would have read fine. A
    value is ``true``/``yes``/``on`` or ``false``/``no``/``off`` in any
    case, empty for false, or an integer for whether it is nonzero
    (pinned against git 2.54).

    Args:
        values (Sequence[bytes]): every value the variable takes, in file
            order; a bare name arrives as ``b"true"``.
        key (str): the variable, section and name lowercased.
        default (bool): the answer when the variable is unset.

    Raises:
        BadConfigValueError: a value git cannot read as a boolean.
    """
    answer = default
    for value in values:
        word = value.lower()
        if word in TRUE_WORDS:
            answer = True
        elif word in FALSE_WORDS:
            answer = False
        else:
            number = _integer(value)
            if number is None:
                raise BadConfigValueError(value.decode(errors="replace"), key)
            answer = number != 0
    return answer


def multivar(config: ConfigFile, section: tuple[bytes, ...],
             name: bytes) -> list[bytes]:
    """Every value of one variable, empty when it is not set.

    Args:
        config (ConfigFile): the parsed config.
        section (tuple[bytes, ...]): section and subsection.
        name (bytes): the variable.
    """
    try:
        return list(config.get_multivar(section, name))
    except KeyError:
        return []


def config_section(section: str, name: str,
                   pairs: Sequence[tuple[str, str]]) -> str:
    """One ``[section "name"]`` block the way git's config writer spells it.

    The subsection escapes ``"`` and ``\\``; a value escapes those plus
    newline and tab, and is quoted when it starts or ends with a space
    or holds ``;`` or ``#``. A branch may be named ``a"b`` or ``a#b``,
    and either one written raw reads back as a different name (pinned
    against git 2.50.1).

    Args:
        section (str): the section, e.g. ``branch``.
        name (str): the subsection, e.g. the branch name.
        pairs (Sequence[tuple[str, str]]): variables and values, in order.
    """
    quoted = name.replace("\\", "\\\\").replace('"', '\\"')
    text = f'[{section} "{quoted}"]\n'
    for key, value in pairs:
        body = "".join(VALUE_ESCAPES.get(ch, ch) for ch in value)
        if value.startswith(" ") or value.endswith(" ") or any(
                ch in value for ch in COMMENT_STARTS):
            body = f'"{body}"'
        text += f"\t{key} = {body}\n"
    return text


def without_section(data: bytes, section: str, name: str) -> bytes:
    """A config's text with every ``[section "name"]`` block taken out.

    ``git branch -d`` drops the deleted branch's settings this way, so a
    branch made again under the same name starts with no upstream
    rather than with two (pinned against git 2.50.1).

    Args:
        data (bytes): the config file's contents.
        section (str): the section, lowercase, e.g. ``branch``.
        name (str): the subsection, e.g. the branch name.
    """
    kept: list[bytes] = []
    dropping = False
    for line in data.splitlines(keepends=True):
        header = SECTION_HEADER.match(line)
        if header is not None:
            sub = header.group(2)
            dropping = (header.group(1).decode().lower() == section
                        and sub is not None
                        and ESCAPED.sub(rb"\1", sub) == name.encode())
        if not dropping:
            kept.append(line)
    return b"".join(kept)


def _integer(value: bytes) -> int | None:
    """git_parse_int: the integer a config value spells, None for none.

    Hex after ``0x`` and octal after a leading zero, then an optional
    ``k``, ``m`` or ``g``; a product outside an int is no integer.

    Args:
        value (bytes): the value as the config file spells it.
    """
    match = INTEGER.fullmatch(value)
    if match is None:
        return None
    sign, digits, unit = match.groups()
    if digits[1:2] in (b"x", b"X"):
        magnitude = int(digits[2:], 16)
    else:
        magnitude = int(digits, 8 if digits.startswith(b"0") else 10)
    number = -magnitude if sign == b"-" else magnitude
    shift = UNIT_SHIFTS[unit.lower()]
    lowest = -(1 << INT_BITS) >> shift
    highest = ((1 << INT_BITS) - 1) >> shift
    if not lowest <= number <= highest:
        return None
    return number << shift

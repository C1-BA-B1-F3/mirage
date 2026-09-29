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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from mirage.commands.spec.constants import FLOAT_VALUE, INT_VALUE
from mirage.commands.spec.types import CommandSpec, ValueType


@dataclass(frozen=True, slots=True)
class CompiledSpec:
    """A CommandSpec lowered into the lookup tables the parser walks.

    Built once per spec (cached) instead of rebuilt on every
    parse_command call. Spellings are the dashed forms as typed
    (``-e``, ``--regexp``); ``dest`` maps every spelling to its
    canonical spelling, the long form when an option declares both, so
    the parsed flag bag holds ONE entry per option regardless of which
    spelling appeared on the line (click/argparse dest semantics).

    Args:
        bool_spellings (frozenset[str]): short spellings parsed as bare
            booleans (true booleans plus optional-value shorts).
        value_spellings (tuple[str, ...]): short spellings expecting a
            value, longest first so ``-name`` can never lose an
            attached match to ``-n``.
        attach_spellings (tuple[str, ...]): short spellings whose value
            may attach to the same token (``split -d10``), longest
            first.
        long_bool_spellings (frozenset[str]): long spellings parsed as
            bare booleans (true booleans plus optional-value longs).
        long_value_spellings (frozenset[str]): long spellings that
            require a value.
        long_optional_spellings (frozenset[str]): long spellings whose
            value only attaches via ``=`` (GNU optional argument).
        kind_of (dict[str, ValueType]): value kind per spelling.
        kind_by_dest (dict[str, ValueType]): value kind per canonical
            spelling, for post-parse PATH/TEXT value collection.
        dest (dict[str, str]): spelling -> canonical spelling.
        multiple_dests (frozenset[str]): canonical spellings that
            accumulate repeated values into a list.
        pair_dests (frozenset[str]): canonical spellings that consume two
            tokens per occurrence and accumulate both, flattened.
        count_dests (frozenset[str]): canonical spellings of boolean
            flags whose occurrences accumulate into an int (click count,
            ``-vvv``).
        long_spellings (tuple[str, ...]): every long spelling in
            declaration order (the order GNU's ambiguity refusal lists
            possibilities), for getopt_long prefix expansion.
        int_dests (frozenset[str]): canonical spellings of int-typed
            options; the parser refuses a non-integer value at parse
            time (argparse ``type=int``).
        float_dests (frozenset[str]): canonical spellings of float-typed
            options, refused the same way (argparse ``type=float``).
        choices_by_dest (dict[str, tuple[str, ...]]): allowed values per
            canonical spelling, in declaration order (the order GNU's
            ARGMATCH refusal lists them).
        required_dests (tuple[str, ...]): canonical spellings that must
            appear, in declaration order; a default satisfies the
            requirement.
        defaults (dict[str, str]): value recorded per canonical spelling
            when the flag is absent from the line.
        numeric_dest (str | None): canonical spelling fed by the
            ``-<digits>`` shorthand, when one option declares it.
        rest_kind (ValueType | None): kind of the rest operand.
        remainder (bool): the rest operand gathers every word from the
            first operand on, options included (``Operand.remainder``,
            argparse's ``nargs=REMAINDER``).
        base_dest (str | None): canonical spelling of the option that
            re-bases the path operands after it (``CommandSpec.
            operand_base``, tar's -C).
    """

    bool_spellings: frozenset[str] = frozenset()
    value_spellings: tuple[str, ...] = ()
    attach_spellings: tuple[str, ...] = ()
    long_bool_spellings: frozenset[str] = frozenset()
    long_value_spellings: frozenset[str] = frozenset()
    long_optional_spellings: frozenset[str] = frozenset()
    long_spellings: tuple[str, ...] = ()
    int_dests: frozenset[str] = frozenset()
    float_dests: frozenset[str] = frozenset()
    kind_of: dict[str, ValueType] = field(default_factory=dict)
    kind_by_dest: dict[str, ValueType] = field(default_factory=dict)
    dest: dict[str, str] = field(default_factory=dict)
    multiple_dests: frozenset[str] = frozenset()
    pair_dests: frozenset[str] = frozenset()
    count_dests: frozenset[str] = frozenset()
    choices_by_dest: dict[str, tuple[str, ...]] = field(default_factory=dict)
    required_dests: tuple[str, ...] = ()
    defaults: dict[str, str] = field(default_factory=dict)
    env_by_dest: dict[str, str] = field(default_factory=dict)
    numeric_dest: str | None = None
    rest_kind: ValueType | None = None
    base_dest: str | None = None
    remainder: bool = False

    def dest_of(self, spelling: str) -> str:
        """Canonical spelling for a typed spelling.

        Args:
            spelling (str): dashed spelling as typed.
        """
        return self.dest.get(spelling, spelling)


# git's notation for an option parse-options also answers as
# `--no-<name>`, and the prefix itself.
NEGATABLE = "[no-]"
NO = "no-"


def _git_spelling(long: str, unset: bool) -> str:
    """The long spelling one of git's options answers to, negated or not.

    Args:
        long (str): the option's name in git's table.
        unset (bool): whether it was matched negated.
    """
    if not unset:
        return f"--{long}"
    return f"--{long[len(NO):]}" if long.startswith(NO) else f"--{NO}{long}"


def _git_shown(long: str, unset: bool) -> str:
    """How git names a candidate in its ambiguity refusal.

    Args:
        long (str): the option's name in git's table.
        unset (bool): whether it was matched negated.
    """
    return f"--{NO if unset else ''}{long}"


def expand_git_long(table: Sequence[str],
                    typed: str) -> str | tuple[str, str] | None:
    """git's parse-options resolution of one long option against the
    program's own table, which lists each option in git's ``--[no-]``
    notation.

    An exact name wins at once, a negatable option answering to its
    ``--no-`` form too. Otherwise the word may abbreviate one option,
    ``--no-`` abbreviating a negation, and a word that abbreviates two
    is ambiguous: git names the last two it found, each with the ``no-``
    it was matched under. A word matching nothing is None, and the
    caller decides what that is. A string is the spelling the table
    resolves to, which the spec may or may not declare; a pair is the
    two candidates of an ambiguity.

    Args:
        table (Sequence[str]): the program's long options, e.g.
            ``("[no-]verbose", "contains")``.
        typed (str): the word as typed, ``--`` included and any
            ``=value`` removed.
    """
    arg = typed[2:]
    found: tuple[str, bool] | None = None
    earlier: tuple[str, bool] | None = None
    for entry in table:
        negatable = entry.startswith(NEGATABLE)
        long = entry[len(NEGATABLE):] if negatable else entry
        inverted = (not arg.startswith(NO) and negatable
                    and long.startswith(NO))
        name = long[len(NO):] if inverted else long
        unset = False
        exact = arg == name
        abbreviated = not exact and name.startswith(arg)
        if not exact and not abbreviated and negatable:
            if NO.startswith(arg):
                unset = True
                abbreviated = True
            elif arg.startswith(NO):
                unset = True
                exact = arg[len(NO):] == name
                abbreviated = not exact and name.startswith(arg[len(NO):])
        if exact:
            return _git_spelling(long, unset != inverted)
        if abbreviated:
            earlier = found
            found = (long, unset != inverted)
    if found is None:
        return None
    if earlier is not None:
        return _git_shown(*earlier), _git_shown(*found)
    return _git_spelling(*found)


def expand_long(cs: CompiledSpec,
                spelling: str,
                synonyms: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """getopt_long prefix matching for a long spelling.

    An exact declared spelling always wins (GNU: ``--binary`` never
    trips over ``--binary-files``); otherwise the candidates are every
    declared long the typed spelling prefixes. Two declared options are
    two options, so a prefix of both is ambiguous (``ls --re`` is
    ``--reverse`` or ``--recursive``), unless ``synonyms`` names them
    one option under two names, the way glibc treats several table
    entries sharing one ``val`` (``grep --colo`` resolves despite
    ``--color``/``--colour`` being separate entries); then the prefix
    resolves to the first. The result length tells the caller
    everything: 0 unknown, 1 match, 2+ ambiguous (every matching
    spelling in declaration order, the order GNU lists possibilities,
    synonyms included like GNU's own listing).

    Args:
        cs (CompiledSpec): compiled tables to match against.
        spelling (str): the typed long spelling, without any ``=value``.
        synonyms (Mapping[str, str] | None): long spelling to the long it
            is another name for, from LONG_SYNONYMS; None when the
            grammar has none.
    """
    if spelling in cs.dest:
        return (spelling, )
    if len(spelling) <= 2:
        return ()
    matches = tuple(declared for declared in cs.long_spellings
                    if declared.startswith(spelling))
    if not matches:
        return ()
    same = synonyms or {}
    if len({same.get(declared, declared) for declared in matches}) == 1:
        return (matches[0], )
    return matches


def expand_table_long(table: Sequence[Sequence[str]],
                      spelling: str) -> tuple[str, ...]:
    """getopt_long prefix matching against a program's whole table.

    An entry spelled exactly names its option; otherwise every entry the
    typed spelling prefixes is a candidate. glibc sets aside a later
    candidate that names the same option as the first one, so one
    option's aliases resolve where two options are ambiguous. The result
    length tells the caller everything: 0 unknown, 1 the option's primary
    spelling, 2+ the possibilities glibc lists (the first candidate and
    every later one naming another option, in table order).

    Args:
        table (Sequence[Sequence[str]]): each option's primary spelling
            then its aliases, in the program's table order
            (LONG_OPTION_TABLES).
        spelling (str): the typed long spelling, without any ``=value``.
    """
    entries = [(name, group[0]) for group in table for name in group]
    for name, primary in entries:
        if name == spelling:
            return (primary, )
    if len(spelling) <= 2:
        return ()
    matches = [(name, primary) for name, primary in entries
               if name.startswith(spelling)]
    if not matches:
        return ()
    first = matches[0][1]
    listed = (matches[0][0],
              *(name for name, primary in matches[1:] if primary != first))
    return (first, ) if len(listed) == 1 else listed


@lru_cache(maxsize=512)
def compile_spec(spec: CommandSpec) -> CompiledSpec:
    """Lower a CommandSpec into parser lookup tables.

    Args:
        spec (CommandSpec): the declarative spec to compile.
    """
    seen_spellings: set[str] = set()
    bool_spellings: set[str] = set()
    value_spellings: list[str] = []
    attach_spellings: list[str] = []
    long_bool_spellings: set[str] = set()
    long_value_spellings: set[str] = set()
    long_optional_spellings: set[str] = set()
    long_spellings: list[str] = []
    int_dests: set[str] = set()
    float_dests: set[str] = set()
    kind_of: dict[str, ValueType] = {}
    kind_by_dest: dict[str, ValueType] = {}
    dest: dict[str, str] = {}
    multiple_dests: set[str] = set()
    pair_dests: set[str] = set()
    count_dests: set[str] = set()
    choices_by_dest: dict[str, tuple[str, ...]] = {}
    required_dests: list[str] = []
    defaults: dict[str, str] = {}
    env_by_dest: dict[str, str] = {}
    numeric_dest: str | None = None

    for opt in spec.options:
        canonical = opt.long if opt.long else opt.short
        if canonical is None:
            raise ValueError("option requires a short or long spelling")
        for spelling in (opt.short, opt.long):
            if spelling is None:
                continue
            if spelling in seen_spellings:
                raise ValueError(f"duplicate option spelling {spelling!r}")
            seen_spellings.add(spelling)
        if opt.count and opt.type != "bool":
            raise ValueError(f"option {canonical!r}: count requires a "
                             "boolean flag (type 'bool')")
        if opt.pair and opt.type == "bool":
            raise ValueError(f"option {canonical!r}: pair requires a value "
                             "flag (a boolean consumes no token)")
        if opt.pair and opt.value_optional:
            raise ValueError(f"option {canonical!r}: pair and value_optional "
                             "are mutually exclusive")
        if opt.pair and opt.short:
            # A short spelling clusters and takes an attached value, both
            # of which are single-token rules; jq's own two-token options
            # are long-only for the same reason.
            raise ValueError(f"option {canonical!r}: pair requires a long "
                             "spelling only")
        if opt.type == "bool" and (opt.choices or opt.default is not None):
            raise ValueError(f"option {canonical!r}: choices and default "
                             "require a value flag")
        if (opt.choices and opt.default is not None
                and opt.default not in opt.choices):
            raise ValueError(f"option {canonical!r}: default "
                             f"{opt.default!r} is not one of its choices")
        if opt.type == "int":
            if opt.default is not None and not INT_VALUE.match(opt.default):
                raise ValueError(f"option {canonical!r}: default "
                                 f"{opt.default!r} is not an integer")
            int_dests.add(canonical)
        if opt.type == "float":
            if opt.default is not None and not FLOAT_VALUE.match(opt.default):
                raise ValueError(f"option {canonical!r}: default "
                                 f"{opt.default!r} is not a number")
            float_dests.add(canonical)
        if opt.short:
            dest[opt.short] = canonical
        if opt.long:
            dest[opt.long] = canonical
        if opt.type != "bool":
            kind_by_dest[canonical] = opt.type
        if opt.multiple or opt.pair:
            multiple_dests.add(canonical)
        if opt.pair:
            pair_dests.add(canonical)
        if opt.count:
            count_dests.add(canonical)
        if opt.choices:
            choices_by_dest[canonical] = opt.choices
        if opt.required:
            required_dests.append(canonical)
        if opt.default is not None:
            defaults[canonical] = opt.default
        if opt.env is not None:
            env_by_dest[canonical] = opt.env

        if opt.short:
            if opt.type == "bool":
                bool_spellings.add(opt.short)
            elif opt.value_optional:
                # GNU optional argument: the bare short is boolean and a
                # value only rides attached to the same token.
                bool_spellings.add(opt.short)
                if opt.short_value:
                    attach_spellings.append(opt.short)
                kind_of[opt.short] = opt.type
            else:
                value_spellings.append(opt.short)
                kind_of[opt.short] = opt.type
                if opt.numeric_shorthand:
                    numeric_dest = canonical
        if opt.long:
            long_spellings.append(opt.long)
            if opt.type == "bool":
                long_bool_spellings.add(opt.long)
            elif opt.value_optional:
                # GNU optional argument: bare form is boolean, value only
                # attaches via `=`; a detached next token is an operand.
                long_bool_spellings.add(opt.long)
                long_optional_spellings.add(opt.long)
                kind_of[opt.long] = opt.type
            else:
                long_value_spellings.add(opt.long)
                kind_of[opt.long] = opt.type

    base_dest: str | None = None
    if spec.operand_base is not None:
        base_dest = dest.get(spec.operand_base)
        if base_dest is None:
            raise ValueError(f"operand_base {spec.operand_base!r} is not a "
                             "declared option")
        if kind_by_dest.get(base_dest) != "path" or base_dest in pair_dests:
            raise ValueError(f"operand_base {spec.operand_base!r} must be a "
                             "single-token path option")

    # Longest first so an attached match can never be stolen by a
    # shorter spelling that happens to prefix it (-name vs -n).
    value_spellings.sort(key=len, reverse=True)
    attach_spellings.sort(key=len, reverse=True)

    return CompiledSpec(
        bool_spellings=frozenset(bool_spellings),
        value_spellings=tuple(value_spellings),
        attach_spellings=tuple(attach_spellings),
        long_bool_spellings=frozenset(long_bool_spellings),
        long_value_spellings=frozenset(long_value_spellings),
        long_optional_spellings=frozenset(long_optional_spellings),
        long_spellings=tuple(long_spellings),
        int_dests=frozenset(int_dests),
        float_dests=frozenset(float_dests),
        kind_of=kind_of,
        kind_by_dest=kind_by_dest,
        dest=dest,
        multiple_dests=frozenset(multiple_dests),
        pair_dests=frozenset(pair_dests),
        count_dests=frozenset(count_dests),
        choices_by_dest=choices_by_dest,
        required_dests=tuple(required_dests),
        defaults=defaults,
        env_by_dest=env_by_dest,
        numeric_dest=numeric_dest,
        rest_kind=spec.rest.type if spec.rest is not None else None,
        base_dest=base_dest,
        remainder=spec.rest is not None and spec.rest.remainder,
    )

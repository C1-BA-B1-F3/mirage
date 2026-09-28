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

from dataclasses import dataclass, field

from mirage.commands.spec.constants import HELP_OPTION, VERSION_OPTION
from mirage.commands.spec.types import CommandSpec, Operand, Option

SHELL_SPECS: dict[str, CommandSpec] = {
    "xargs":
    CommandSpec(
        description="Build and run command lines from standard input.",
        options=(
            Option(short="-n",
                   long="--max-args",
                   type="str",
                   description="Use at most N arguments per command line."),
            Option(short="-d",
                   long="--delimiter",
                   type="str",
                   description="Input items are separated by this character."),
            Option(short="-0",
                   long="--null",
                   description="Input items are terminated by NUL."),
            Option(short="-r",
                   long="--no-run-if-empty",
                   description="Do not run the command on empty input."),
            Option(short="-I",
                   type="str",
                   description="Replace this string in the initial "
                   "arguments with each input line."),
            Option(short="-i",
                   long="--replace",
                   type="str",
                   value_optional=True,
                   description="Same as -I, with {} when no string is "
                   "attached."),
            Option(short="-L",
                   type="str",
                   description="Use at most N non-blank input lines per "
                   "command line."),
            Option(short="-l",
                   long="--max-lines",
                   type="str",
                   value_optional=True,
                   description="Same as -L, with 1 when no count is "
                   "attached."),
            Option(short="-P",
                   long="--max-procs",
                   type="str",
                   description="Run up to N commands at a time; 0 runs "
                   "them all at once."),
            HELP_OPTION,
            VERSION_OPTION,
        ),
        rest=Operand(type="str"),
    ),
    "timeout":
    CommandSpec(
        description="Run a command with a time limit.",
        options=(
            Option(short="-s",
                   long="--signal",
                   type="str",
                   description="Signal to send on timeout (not supported)."),
            Option(short="-k",
                   long="--kill-after",
                   type="str",
                   description="Also send KILL after this long "
                   "(not supported)."),
            Option(long="--preserve-status",
                   description="Exit with the command's status on timeout "
                   "(not supported)."),
        ),
        rest=Operand(type="str"),
    ),
    "read":
    CommandSpec(
        description="Read a line from standard input into variables.",
        options=(
            Option(short="-r",
                   description="Raw mode: backslash is not an escape "
                   "character."),
            Option(short="-a",
                   type="str",
                   description="Store the words in the named array."),
            Option(short="-d",
                   type="str",
                   description="Read up to this character instead of "
                   "newline."),
            Option(short="-n",
                   type="str",
                   description="Return after at most N characters."),
            Option(short="-N",
                   type="str",
                   description="Return after exactly N characters, "
                   "delimiters included."),
            Option(short="-t",
                   type="str",
                   description="Time out after N seconds."),
            Option(short="-p",
                   type="str",
                   description="Prompt (shown only on a terminal)."),
            Option(short="-s", description="Do not echo (terminal only)."),
            Option(short="-e", description="Use readline (terminal only)."),
            Option(short="-i",
                   type="str",
                   description="Initial text for readline (terminal "
                   "only)."),
            Option(short="-u",
                   type="str",
                   description="Read from this descriptor."),
        ),
        rest=Operand(type="str"),
    ),
    "mapfile":
    CommandSpec(
        description="Read lines from standard input into an array.",
        options=(
            Option(short="-d",
                   type="str",
                   description="Line delimiter instead of newline."),
            Option(short="-n", type="str",
                   description="Copy at most N lines."),
            Option(short="-O",
                   type="str",
                   description="Start storing at this index."),
            Option(short="-s",
                   type="str",
                   description="Discard the first N lines."),
            Option(short="-t", description="Strip the delimiter."),
            Option(short="-u",
                   type="str",
                   description="Read from this descriptor."),
            Option(short="-C",
                   type="str",
                   description="Call this every quantum lines."),
            Option(short="-c",
                   type="str",
                   description="Lines between callback calls."),
        ),
        rest=Operand(type="str"),
    ),
}


@dataclass(frozen=True, slots=True)
class ShellParse:
    """Result of a strict leading-option scan for a shell builtin.

    Wrapper builtins (xargs, timeout) stop option parsing at the first
    operand, since everything after it belongs to the wrapped command;
    the mount-command parser scans the whole line and warns-ignores
    unknown flags, which is wrong on both counts here. The builtin owns
    the error message and exit code (GNU shapes differ per tool), so
    the parse only reports what went wrong.

    Args:
        flags (dict[str, str | bool]): parsed options keyed by their
            dashless short or long name; an optional-value option
            given bare is True.
        given (list[tuple[str, str | bool]]): every option in the order
            it was given, for a builtin whose options act in turn
            (xargs -I, -L and -n cancel one another).
        operands (list[str]): everything from the first non-option on.
        invalid (str | None): unknown option char or long token.
        needs_value (str | None): value option with no value: the short
            char, or the long token with its dashes.
    """
    flags: dict[str, str | bool] = field(default_factory=dict)
    given: list[tuple[str, str | bool]] = field(default_factory=list)
    operands: list[str] = field(default_factory=list)
    invalid: str | None = None
    needs_value: str | None = None


def parse_shell_options(spec: CommandSpec, argv: list[str]) -> ShellParse:
    """Scan leading options the way getopt does for a shell builtin.

    An optional-value option takes its value only when attached
    (``-iR``, ``--replace=R``), as getopt's ``::`` does.

    Args:
        spec (CommandSpec): options table (SHELL_SPECS entry).
        argv (list[str]): builtin arguments, command name excluded.
    """
    short_bool: set[str] = set()
    short_value: set[str] = set()
    short_optional: set[str] = set()
    long_bool: set[str] = set()
    long_value: set[str] = set()
    long_optional: set[str] = set()
    alias: dict[str, str] = {}
    for opt in spec.options:
        short = opt.short.lstrip("-") if opt.short else None
        long = opt.long.lstrip("-") if opt.long else None
        name = short or long or ""
        if short is not None:
            (short_bool if opt.type == "bool" else
             short_optional if opt.value_optional else short_value).add(short)
            alias[short] = name
        if long is not None:
            (long_bool if opt.type == "bool" else
             long_optional if opt.value_optional else long_value).add(long)
            alias[long] = name
    flags: dict[str, str | bool] = {}
    given: list[tuple[str, str | bool]] = []

    def record(key: str, value: str | bool) -> None:
        flags[key] = value
        given.append((key, value))

    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            i += 1
            break
        if tok.startswith("--") and len(tok) > 2:
            name, eq, value = tok[2:].partition("=")
            if name in long_bool:
                record(alias[name], True)
            elif name in long_optional:
                record(alias[name], value if eq else True)
            elif name in long_value:
                if eq:
                    record(alias[name], value)
                elif i + 1 < len(argv):
                    i += 1
                    record(alias[name], argv[i])
                else:
                    return ShellParse(flags=flags,
                                      given=given,
                                      operands=list(argv[i + 1:]),
                                      needs_value=f"--{name}")
            else:
                return ShellParse(flags=flags,
                                  given=given,
                                  operands=list(argv[i + 1:]),
                                  invalid=tok)
            i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            chars = tok[1:]
            j = 0
            while j < len(chars):
                ch = chars[j]
                if ch in short_bool:
                    record(alias[ch], True)
                    j += 1
                    continue
                if ch in short_optional:
                    record(alias[ch], chars[j + 1:] or True)
                    break
                if ch in short_value:
                    rest = chars[j + 1:]
                    if rest:
                        record(alias[ch], rest)
                    elif i + 1 < len(argv):
                        i += 1
                        record(alias[ch], argv[i])
                    else:
                        return ShellParse(flags=flags,
                                          given=given,
                                          operands=list(argv[i + 1:]),
                                          needs_value=ch)
                    break
                return ShellParse(flags=flags,
                                  given=given,
                                  operands=list(argv[i + 1:]),
                                  invalid=ch)
            i += 1
            continue
        break
    return ShellParse(flags=flags, given=given, operands=list(argv[i:]))

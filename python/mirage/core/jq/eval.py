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

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import jq as _libjq

from mirage.core.jq.errors import JqCompileError
from mirage.core.jq.types import (ARGS_VAR, ERROR_KEY, HALT_KEY, INPUTS_VAR,
                                  JqError, JqHalt, JqOptions, JqRun,
                                  StreamReads)
from mirage.types import JsonValue

logger = logging.getLogger(__name__)

INPUT_REF = re.compile(r"(?<![\w$.:])input(?![\w:])")
INPUTS_REF = re.compile(r"(?<![\w$.:])inputs(?![\w:])")
INPUT_DEF = re.compile(r"(?<![\w$.:])def\s+input\s*[:(]")
INPUTS_DEF = re.compile(r"(?<![\w$.:])def\s+inputs\s*[:(]")
ARGS_REF = re.compile(r"\$ARGS(?![\w:])")
HALT_REF = re.compile(r"(?<![\w$.:])halt(?:_error)?(?![\w:])")
TOP_LEVEL_LINE = re.compile(r"(at <top-level>, line )(\d+)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
TO_STREAM = "tostream"
INTERP = "\\("
OPENERS = "([{"
CLOSERS = ")]}"

# `halt` and `halt_error` stop jq itself, which libjq's binding reports as
# nothing but the end of the outputs, so the prelude redefines both to
# hand the stop back first: the text jq writes to stderr for it (a string
# as it is, null as nothing, anything else dumped on a line of its own)
# and the exit code. The builtins stay reachable under names of their
# own, which is also how a code that is not a number meets halt_error's
# own refusal.
_STOPS = ("def __mirage_jq_halt: halt; "
          "def __mirage_jq_halt_error($code): halt_error($code); "
          'def halt: {"' + HALT_KEY + '": [null, ""]}, __mirage_jq_halt; '
          'def halt_error($code): if ($code | type) == "number" then {"' +
          HALT_KEY + '": [$code, (if type == "string" then . '
          'elif . == null then "" else tojson + "\\n" end)]}, '
          "__mirage_jq_halt else __mirage_jq_halt_error($code) end; "
          "def halt_error: halt_error(5); ")

# The error no `try` inside the program caught: whether it was a string,
# and its text as jq prints it.
_CATCH = (' catch {"' + ERROR_KEY + '": [(type == "string"), '
          '(if type == "string" then . else tojson end)]}')


def code_only(expr: str) -> str:
    """Blank out every part of a jq program that cannot be a call.

    Three things are replaced by spaces: string bodies, `#` comments,
    and the field names an object shorthand abbreviates (`{a, inputs}`
    is `{a: .a, inputs: .inputs}`). Interpolations stay code, because
    `"\\(inputs)"` really does call the builtin, so everything between
    `\\(` and its closing paren survives, nested strings included.

    Args:
        expr (str): jq program text.
    """
    out: list[str] = []
    # Open brackets, innermost last, with an interpolation recorded as
    # one too; empty means the scan is at the top level of the program.
    stack: list[str] = []
    in_string = False
    prev = ""
    i = 0
    while i < len(expr):
        ch = expr[i]
        if in_string:
            if ch == "\\" and i + 1 < len(expr):
                if expr[i + 1] == "(":
                    in_string = False
                    stack.append(INTERP)
                out.append("  ")
                i += 2
                continue
            in_string = ch != '"'
            out.append(" ")
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(" ")
            i += 1
            continue
        if ch == "#":
            while i < len(expr) and expr[i] != "\n":
                out.append(" ")
                i += 1
            continue
        word = IDENT.match(expr, i)
        if word is not None:
            text = word.group()
            key = bool(stack) and stack[-1] == "{" and prev in ("{", ",")
            out.append(" " * len(text) if key else text)
            prev = text[-1]
            i = word.end()
            continue
        if ch in OPENERS:
            stack.append(ch)
        elif ch == ")" and stack and stack[-1] == INTERP:
            stack.pop()
            in_string = True
            out.append(" ")
            prev = ""
            i += 1
            continue
        elif ch in CLOSERS and stack and stack[-1] != INTERP:
            stack.pop()
        out.append(ch)
        if not ch.isspace():
            prev = ch
        i += 1
    return "".join(out)


def references_args(expr: str) -> bool:
    """Report whether a jq program reads the `$ARGS` variable.

    Args:
        expr (str): jq program text.
    """
    return ARGS_REF.search(code_only(expr)) is not None


def halts(expr: str) -> bool:
    """Report whether a jq program can call `halt` or `halt_error`.

    Args:
        expr (str): jq program text.
    """
    return HALT_REF.search(code_only(expr)) is not None


def args_object(opts: JqOptions) -> dict[str, Any]:
    """The value `$ARGS` resolves to for a run.

    Args:
        opts (JqOptions): resolved options carrying both binding kinds.
    """
    return {
        "positional": list(opts.positional_args),
        "named": dict(opts.named_args),
    }


def stream_events(doc: JsonValue) -> list[JsonValue]:
    """The `[path, leaf]` events `--stream` reads a document as.

    jq's own `tostream` emits exactly the events `--stream` produces for
    a complete document; the two differ only for input too truncated to
    parse, which never reaches here because mirage reads whole values.

    Args:
        doc (object): one parsed input document.
    """
    return jq_eval(doc, TO_STREAM)


def stream_reads(expr: str) -> StreamReads:
    """Report which of the builtins that read the input stream a program
    calls.

    Binding the unread documents is what makes `input` and `inputs`
    work, and it also changes how many documents a run consumes, so only
    the builtins may answer here: the words also spell a field
    (`.inputs`, `{inputs}`), a variable (`$inputs`), an object key
    (`{inputs: 1}`), a module member (`m::inputs`), a function the
    program defines for itself (`def input: ...`), and anything at all
    inside a string or a comment, none of which read the stream.

    Args:
        expr (str): jq program text.
    """
    code = code_only(expr)
    return StreamReads(
        input=INPUT_REF.search(code) is not None
        and INPUT_DEF.search(code) is None,
        inputs=INPUTS_REF.search(code) is not None
        and INPUTS_DEF.search(code) is None,
    )


def _stream_defs(expr: str) -> str:
    """The definitions `input` and `inputs` read the unread documents
    through.

    `input` takes the first of them and, once none is left, fails the
    way jq 1.7 and 1.8 both do, with the error `break`. `inputs` yields
    the ones after it, or all of them when the program never calls
    `input`: the stream as the two builtins leave it for each other when
    `input` runs once, ahead of `inputs`.

    Args:
        expr (str): jq program text.
    """
    docs = f"${INPUTS_VAR}"
    rest = f"{docs}[1:]" if stream_reads(expr).input else docs
    return (f"def input: if ({docs} | length) > 0 then {docs}[0] "
            f'else error("break") end; def inputs: {rest}[];')


def _unshifted(message: str, shift: int) -> str:
    """A compile error as the program's own lines number it.

    Args:
        message (str): libjq's error text.
        shift (int): lines the prelude put ahead of the program.
    """
    if shift == 0:
        return message
    return TOP_LEVEL_LINE.sub(
        lambda match: f"{match.group(1)}{int(match.group(2)) - shift}",
        message)


def _balanced(code: str) -> bool:
    """Whether every bracket in a program's code closes the one opened
    last, which is what keeps the program whole inside the prelude's own
    parentheses: code that closes one early could otherwise pair with
    them into a program jq itself would refuse.

    Args:
        code (str): the program as code_only leaves it.
    """
    stack: list[str] = []
    for ch in code:
        if ch in OPENERS:
            stack.append(ch)
        elif ch in CLOSERS and (not stack
                                or OPENERS[CLOSERS.index(ch)] != stack.pop()):
            return False
    return not stack


def _stop_of(value: JsonValue) -> JqError | JqHalt | None:
    """The stop the prelude hands back as a run's last output, when this
    output is one (see _STOPS and _CATCH).

    Args:
        value (JsonValue): one output of the run.
    """
    if not isinstance(value, dict) or len(value) != 1:
        return None
    error = value.get(ERROR_KEY)
    if isinstance(error, list) and len(error) == 2:
        return JqError(str(error[1]), error[0] is True)
    halt = value.get(HALT_KEY)
    if isinstance(halt, list) and len(halt) == 2:
        code = halt[0]
        if isinstance(code, bool) or not isinstance(code, (int, float)):
            return JqHalt(str(halt[1]), None)
        return JqHalt(str(halt[1]), code)
    return None


def _collected(results: Iterable[JsonValue]) -> JqRun:
    """A run's outputs, up to the stop the prelude hands back.

    Only a program the prelude could not wrap raises its error here, and
    libjq's binding says no more of that error than its text.

    Args:
        results (Iterable[JsonValue]): the program's outputs, as libjq
            yields them.
    """
    outputs: list[JsonValue] = []
    try:
        for value in results:
            stop = _stop_of(value)
            if stop is not None:
                return JqRun(outputs, stop)
            outputs.append(value)
    except ValueError as exc:
        return JqRun(outputs, JqError(str(exc), True))
    return JqRun(outputs)


def _bindings(
    expr: str,
    named_args: Mapping[str, Any] | None,
    inputs: Sequence[JsonValue] | None,
    args_value: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """The named arguments a run compiles with, and the prelude steps
    that read them.

    Args:
        expr (str): jq program text.
        named_args (Mapping[str, Any] | None): $name bindings.
        inputs (Sequence[JsonValue] | None): the unread documents.
        args_value (Mapping[str, Any] | None): the value of `$ARGS`.
    """
    args: dict[str, Any] = dict(named_args) if named_args else {}
    steps: list[str] = []
    if inputs is not None:
        args[INPUTS_VAR] = list(inputs)
        steps.append(_stream_defs(expr))
    if args_value is not None:
        args[ARGS_VAR] = dict(args_value)
        steps.append(f"${ARGS_VAR} as $ARGS |")
    return args, steps


def _compiled(expr: str, args: dict[str, Any], steps: list[str]) -> Any:
    """The program compiled inside the prelude that hands its stop back
    (see jq_run), or as typed behind the same definitions when its code
    cannot sit whole inside the prelude's parentheses.

    Args:
        expr (str): jq program text.
        args (dict[str, Any]): the named arguments to compile with.
        steps (list[str]): the prelude steps that read them.

    Raises:
        JqCompileError: libjq's refusal of the program, its compile
            errors numbered by the program's own lines.
    """
    code = code_only(expr)
    if code.strip() and _balanced(code):
        prelude = _STOPS + "".join(f"{step} " for step in steps)
        try:
            return _libjq.compile(f"{prelude}try ({expr}\n){_CATCH}",
                                  args=args)
        except ValueError as exc:
            # A refusal names the prelude's text; the program as typed,
            # below, is what says why.
            logger.debug("jq: program refused inside the prelude: %s", exc)
    # As typed, the prelude costs one line, so the line a compile error
    # reports is moved back by it. A program with no code for jq to run
    # at all goes bare, which keeps libjq's own refusal of an empty
    # program.
    shift = 1 if code.strip() else 0
    program = f"{_STOPS}{' '.join(steps)}\n{expr}" if shift else expr
    try:
        return _libjq.compile(program, args=args)
    except ValueError as exc:
        raise JqCompileError(_unshifted(str(exc), shift)) from exc


def jq_run(
    obj: JsonValue,
    expr: str,
    named_args: Mapping[str, Any] | None = None,
    inputs: Sequence[JsonValue] | None = None,
    args_value: Mapping[str, Any] | None = None,
) -> JqRun:
    """Run a jq program on one value using libjq, the way jq's main loop
    runs it on one document.

    A jq program is a stream transformer: it emits zero, one or many
    values, and jq prints each on its own line. That arity is preserved
    here rather than collapsed, so two outputs are never confused with
    one output that happens to be an array. `.a, .b` yields two values;
    `[.a, .b]` yields one.

    An error that no `try` catches ends the run, and jq still prints
    what came before it; `halt` and `halt_error` end the whole
    invocation. libjq's binding reports neither whole (an error that is
    not a string arrives as Python's rendering of it, and a halt as the
    plain end of the outputs), so the program runs inside a prelude that
    catches the error and redefines the two halts, and each hands its
    stop back as the run's last output. The whole prelude sits on the
    program's first line, so the program's lines keep their numbers.

    Args:
        obj (JsonValue): the value the program runs on.
        expr (str): jq program text.
        named_args (Mapping[str, Any] | None): $name bindings from
            --arg / --argjson.
        inputs (Sequence[JsonValue] | None): the documents still unread
            at this point in the stream, which `input` and `inputs` read
            (see _stream_defs). libjq's Python binding owns no input
            stream, so both builtins are bound as definitions over a
            named argument instead; a user program that defines its own
            shadows the binding, as it would shadow the builtin.
        args_value (Mapping[str, Any] | None): the value `$ARGS` should
            resolve to, bound the same way and for the same reason
            (libjq's binding defines no `$ARGS` of its own).

    Raises:
        JqCompileError: libjq's refusal of the program, its compile
            errors numbered by the program's own lines.
    """
    args, steps = _bindings(expr, named_args, inputs, args_value)
    return _collected(_compiled(expr, args, steps).input_value(obj))


def jq_check(
    expr: str,
    named_args: Mapping[str, Any] | None = None,
    inputs: Sequence[JsonValue] | None = None,
    args_value: Mapping[str, Any] | None = None,
) -> None:
    """Compile a program the way a run would, without running it.

    jq compiles its program before it reads any input, so it refuses a
    bad one even when there is no document to run it on.

    Args:
        expr (str): jq program text.
        named_args (Mapping[str, Any] | None): $name bindings.
        inputs (Sequence[JsonValue] | None): the unread documents.
        args_value (Mapping[str, Any] | None): the value of `$ARGS`.

    Raises:
        JqCompileError: libjq's refusal of the program.
    """
    args, steps = _bindings(expr, named_args, inputs, args_value)
    _compiled(expr, args, steps)


def jq_eval(
    obj: JsonValue,
    expr: str,
    named_args: Mapping[str, Any] | None = None,
    inputs: Sequence[JsonValue] | None = None,
    args_value: Mapping[str, Any] | None = None,
) -> list[JsonValue]:
    """Every output of a jq program on one value (see jq_run), for a
    caller that treats an error as a failure of its own.

    Args:
        obj (JsonValue): the value the program runs on.
        expr (str): jq program text.
        named_args (Mapping[str, Any] | None): $name bindings.
        inputs (Sequence[JsonValue] | None): the unread documents.
        args_value (Mapping[str, Any] | None): the value of `$ARGS`.

    Raises:
        ValueError: libjq's refusal of the program, or the error that
            ended the run.
    """
    run = jq_run(obj, expr, named_args, inputs, args_value)
    if isinstance(run.stop, JqError):
        raise ValueError(run.stop.text)
    return run.outputs

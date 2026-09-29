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
import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import jq as _libjq

from mirage.core.jq.errors import JqCompileError
from mirage.core.jq.types import JqError, JqHalt, JqOptions, JqRun, StreamReads
from mirage.types import JsonValue

logger = logging.getLogger(__name__)

INPUT_REF = re.compile(r"(?<![\w$.:])input(?![\w:])")
INPUTS_REF = re.compile(r"(?<![\w$.:])inputs(?![\w:])")
INPUT_DEF = re.compile(r"(?<![\w$.:])def\s+input\s*[:(]")
INPUTS_DEF = re.compile(r"(?<![\w$.:])def\s+inputs\s*[:(]")
ARGS_REF = re.compile(r"\$ARGS(?![\w:])")
HALT_REF = re.compile(r"(?<![\w$.:])halt(?:_error)?(?![\w:])")
HALT_ERROR_REF = re.compile(r"(?<![\w$.:])halt_error(?![\w:])")
TOP_LEVEL_LINE = re.compile(r"(at <top-level>, line )(\d+)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
INTERP = "\\("
OPENERS = "([{"
CLOSERS = ")]}"

# The keys the prelude hands a run's stop back under: the error no `try`
# caught, the halt `halt` or `halt_error` asked for, and the end of a run
# that did not halt. Each carries a token drawn once per process, so no
# output of a program can pass for one.
_TOKEN = uuid.uuid4().hex
ERROR_KEY = f"__mirage_jq_error_{_TOKEN}"
HALT_KEY = f"__mirage_jq_halt_{_TOKEN}"
DONE_KEY = f"__mirage_jq_done_{_TOKEN}"

# The named arguments the prelude reads: the unread documents `input` and
# `inputs` read, the parse error they meet past the last of them, and the
# value it rebinds `$ARGS` to. They carry the same token, so no `--arg` of
# the program's own can take one's place.
INPUTS_VAR = f"__mirage_jq_inputs_{_TOKEN}"
INPUTS_ERROR_VAR = f"__mirage_jq_inputs_error_{_TOKEN}"
ARGS_VAR = f"__mirage_jq_args_{_TOKEN}"

# The error no `try` inside the program caught: whether it was a string,
# and its text as jq prints it.
_ERROR_MARK = ('{"' + ERROR_KEY + '": [(type == "string"), '
               '(if type == "string" then . else tojson end)]}')
_CATCH = f" catch {_ERROR_MARK}"
_DONE = ', {"' + DONE_KEY + '": true}'

# A run keeps jq's own `halt` and `halt_error`, which no `try` catches and
# which end the program wherever they are called; one that halted is the
# run that never reaches the sentinel after the program. libjq's binding
# says nothing more of a halt, so its message and code come from running
# the program again with the two redefined, first to raise them as an
# error the top-level `catch` hands back (which leaves any collector,
# `[halt_error]` or `map`), and when a `try` of the program's own caught
# that, to print them just before the real halt. Either answer counts only
# when the run printed as many outputs up to it as the first run did: the
# runs are one run up to the first halt, so a later halt shows as more
# outputs before it, where the values themselves can differ (`now`). Two
# things still get past that: a `try` that swallows one halt unseen before
# the program reaches another, and a halt whose message or choice rests on
# `now`, which the rerun reads again.
_HALT_MARK = ('{"' + HALT_KEY + '": [$code, (if . == null then null '
              'elif type == "string" then . else tojson end), '
              '(type == "string")]}')
_BUILTINS = ("def __mirage_jq_halt: halt; "
             "def __mirage_jq_halt_error($code): halt_error($code); ")
_RAISE = (_BUILTINS + 'def halt: error({"' + HALT_KEY +
          '": [null, null, false]}); '
          'def halt_error($code): if ($code | type) == "number" then '
          f"error({_HALT_MARK}) else __mirage_jq_halt_error($code) end; "
          "def halt_error: halt_error(5); ")
_RAISED = (' catch (if type == "object" and has("' + HALT_KEY +
           f'") then . else {_ERROR_MARK} end)')
_PRINT = (_BUILTINS + 'def halt: {"' + HALT_KEY +
          '": [null, null, false]}, __mirage_jq_halt; '
          'def halt_error($code): if ($code | type) == "number" then '
          f"{_HALT_MARK}, __mirage_jq_halt_error($code) "
          "else __mirage_jq_halt_error($code) end; "
          "def halt_error: halt_error(5); ")


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


def _stream_defs(expr: str, failed: bool) -> str:
    """The definitions `input` and `inputs` read the unread documents
    through.

    `input` takes the first of them and, once none is left, fails the
    way jq 1.7 and 1.8 both do, with the error `break`. `inputs` yields
    the ones after it, or all of them when the program never calls
    `input`: the stream as the two builtins leave it for each other when
    `input` runs once, ahead of `inputs`. When the stream ended in a
    parse error, the reader past the last document meets that instead,
    and both raise it as an error the program can catch.

    Args:
        expr (str): jq program text.
        failed (bool): whether the stream ended in a parse error, bound
            as its own named argument.
    """
    docs = f"${INPUTS_VAR}"
    rest = f"{docs}[1:]" if stream_reads(expr).input else docs
    end = f"error(${INPUTS_ERROR_VAR})" if failed else 'error("break")'
    tail = f", error(${INPUTS_ERROR_VAR})" if failed else ""
    return (f"def input: if ({docs} | length) > 0 then {docs}[0] "
            f"else {end} end; def inputs: {rest}[]{tail};")


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
    """The stop the prelude hands back as a run's output, when this
    output is one.

    Args:
        value (JsonValue): one output of the run.
    """
    if not isinstance(value, dict) or len(value) != 1:
        return None
    error = value.get(ERROR_KEY)
    if isinstance(error, list) and len(error) == 2:
        return JqError(str(error[1]), error[0] is True)
    halt = value.get(HALT_KEY)
    if isinstance(halt, list) and len(halt) == 3:
        code, message, string = halt
        text = message if isinstance(message, str) else None
        if isinstance(code, bool) or not isinstance(code, (int, float)):
            return JqHalt(text, string is True, None)
        return JqHalt(text, string is True, code)
    return None


def _collected(results: Iterable[JsonValue]) -> tuple[JqRun, bool]:
    """A run's outputs, up to the stop the prelude hands back, and whether
    the run ended by itself rather than stopping at a halt: it reached the
    sentinel, handed back a stop, or failed.

    Only a program the prelude could not wrap raises its error here, and
    libjq's binding says no more of that error than its text.

    Args:
        results (Iterable[JsonValue]): the program's outputs, as libjq
            yields them.
    """
    outputs: list[JsonValue] = []
    try:
        for value in results:
            if isinstance(value, dict) and DONE_KEY in value:
                return JqRun(outputs), True
            stop = _stop_of(value)
            if stop is not None:
                return JqRun(outputs, stop), True
            outputs.append(value)
    except ValueError as exc:
        return JqRun(outputs, JqError(str(exc), True)), True
    return JqRun(outputs), False


def _bindings(
    expr: str,
    named_args: Mapping[str, Any] | None,
    inputs: Sequence[JsonValue] | None,
    args_value: Mapping[str, Any] | None,
    inputs_error: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """The named arguments a run compiles with, and the prelude steps
    that read them.

    Args:
        expr (str): jq program text.
        named_args (Mapping[str, Any] | None): $name bindings.
        inputs (Sequence[JsonValue] | None): the unread documents.
        args_value (Mapping[str, Any] | None): the value of `$ARGS`.
        inputs_error (str | None): the parse error the stream ends in.
    """
    args: dict[str, Any] = dict(named_args) if named_args else {}
    steps: list[str] = []
    if inputs is not None:
        args[INPUTS_VAR] = list(inputs)
        if inputs_error is not None:
            args[INPUTS_ERROR_VAR] = inputs_error
        steps.append(_stream_defs(expr, inputs_error is not None))
    if args_value is not None:
        args[ARGS_VAR] = dict(args_value)
        steps.append(f"${ARGS_VAR} as $ARGS |")
    return args, steps


def _typed(expr: str, args: dict[str, Any], steps: list[str]) -> Any:
    """The program compiled as typed, behind the definitions that print a
    halt just before it: the way a program runs when its code cannot sit
    whole inside the prelude's parentheses.

    The prelude costs one line here, so the line a compile error reports
    is moved back by it. A program with no code for jq to run at all goes
    bare, which keeps libjq's own refusal of an empty program.

    Args:
        expr (str): jq program text.
        args (dict[str, Any]): the named arguments to compile with.
        steps (list[str]): the prelude steps that read them.

    Raises:
        JqCompileError: libjq's refusal of the program, its compile
            errors numbered by the program's own lines.
    """
    shift = 1 if code_only(expr).strip() else 0
    program = f"{_PRINT}{' '.join(steps)}\n{expr}" if shift else expr
    try:
        return _libjq.compile(program, args=args)
    except ValueError as exc:
        raise JqCompileError(_unshifted(str(exc), shift)) from exc


def _wrapped(expr: str, args: dict[str, Any], steps: list[str], stops: str,
             tail: str) -> Any | None:
    """The program compiled inside the prelude (see jq_run), or None when
    its code cannot sit whole inside the prelude's parentheses.

    Args:
        expr (str): jq program text.
        args (dict[str, Any]): the named arguments to compile with.
        steps (list[str]): the prelude steps that read them.
        stops (str): the definitions `halt` and `halt_error` run as.
        tail (str): what follows the program: its `catch`, and the
            sentinel of a run that keeps the real halts.
    """
    code = code_only(expr)
    if not code.strip() or not _balanced(code):
        return None
    prelude = stops + "".join(f"{step} " for step in steps)
    try:
        return _libjq.compile(f"{prelude}(try ({expr}\n){tail}", args=args)
    except ValueError as exc:
        # A refusal names the prelude's text; the program as typed is
        # what says why.
        logger.debug("jq: program refused inside the prelude: %s", exc)
        return None


def _halt_of(obj: JsonValue, expr: str, args: dict[str, Any], steps: list[str],
             printed: int) -> JqHalt:
    """The message and code of the halt a run stopped at, from running the
    program again with the halts redefined (see _RAISE and _PRINT).

    Args:
        obj (JsonValue): the value the program ran on.
        expr (str): jq program text.
        args (dict[str, Any]): the named arguments to compile with.
        steps (list[str]): the prelude steps that read them.
        printed (int): how many outputs the run printed before it halted.
    """
    for stops, tail in ((_RAISE, f"{_RAISED})"), (_PRINT, f"{_CATCH})")):
        compiled = _wrapped(expr, args, steps, stops, tail)
        if compiled is None:
            continue
        again, _ = _collected(compiled.input_value(obj))
        if isinstance(again.stop, JqHalt) and len(again.outputs) == printed:
            return again.stop
    # A halt caught by the program's own `try` inside a collector keeps
    # its message from both, so it reads as halt_error's default.
    if HALT_ERROR_REF.search(code_only(expr)) is None:
        return JqHalt(None, False, None)
    return JqHalt(None, False, 5)


def jq_run(
    obj: JsonValue,
    expr: str,
    named_args: Mapping[str, Any] | None = None,
    inputs: Sequence[JsonValue] | None = None,
    args_value: Mapping[str, Any] | None = None,
    inputs_error: str | None = None,
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
    catches the error and hands it back as the run's last output, with a
    sentinel after the program that only a run that did not halt reaches
    (see _halt_of for what a halt said). The whole prelude sits on the
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
        inputs_error (str | None): the parse error the stream ends in,
            which `input` and `inputs` raise past the last of `inputs`.

    Raises:
        JqCompileError: libjq's refusal of the program, its compile
            errors numbered by the program's own lines.
    """
    args, steps = _bindings(expr, named_args, inputs, args_value, inputs_error)
    compiled = _wrapped(expr, args, steps, "", f"{_CATCH}){_DONE}")
    if compiled is None:
        return _collected(_typed(expr, args, steps).input_value(obj))[0]
    run, ended = _collected(compiled.input_value(obj))
    if ended:
        return run
    halt = _halt_of(obj, expr, args, steps, len(run.outputs))
    return JqRun(run.outputs, halt)


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
    if _wrapped(expr, args, steps, "", f"{_CATCH}){_DONE}") is None:
        _typed(expr, args, steps)


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

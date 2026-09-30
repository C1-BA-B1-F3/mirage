import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from mirage.commands.builtin.generic.program import read_program_file
from mirage.commands.builtin.utils.stream import (is_stdin, resolve_source,
                                                  stdin_bytes, stdin_stream)
from mirage.commands.config import CommandOpts
from mirage.commands.errors import UsageError
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.core.jq import (args_text, decode_utf8, error_report,
                            format_jq_output, halt_report, jq_check,
                            jq_run_texts, load_failure, printable, read_texts,
                            references_args, stream_reads, string_text,
                            value_text)
from mirage.core.jq.errors import JqCompileError
from mirage.core.jq.stream import InputReader
from mirage.core.jq.types import (DEFAULT_INDENT, NO_VALUE, STDIN_NAME,
                                  InputSource, JqError, JqHalt, JqOptions,
                                  JqParseError, JqRun, StreamReads)
from mirage.io.stream import yield_bytes
from mirage.io.types import ByteSource, IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import PathSpec
from mirage.utils.errors import FS_ERRORS

INDENT_MIN = -1
INDENT_MAX = 7

# What jq's process() answers for one run, which its exit status is made
# of (main.c): the last output was not false or null, it was, there was
# none, and an error no `try` caught ended the run.
OK = 0
OK_NULL_KIND = -1
OK_NO_OUTPUT = -4
ERROR_UNKNOWN = 5

# The outputs -e counts as null-kind, as jq dumps them.
NULL_KIND = frozenset(("null", "false"))

# jq's exit status when it refuses the program itself, and when it could
# not read one of its inputs, whatever the runs answered.
ERROR_COMPILE = 3
ERROR_SYSTEM = 2

USAGE_HINT = ("Use jq --help for help with command-line options,\n"
              "or see the jq manpage, or online docs at https://jqlang.org")


def _pair_args(values: Sequence[Any]) -> list[tuple[str, Any]]:
    """Read a pair option's flattened values back as (name, value).

    Args:
        values (Sequence[Any]): the accumulated tokens, name then value.
            A "path" pair (--rawfile, --slurpfile) carries a PathSpec in
            every value slot.
    """
    return [(str(values[i]), values[i + 1])
            for i in range(0,
                           len(values) - 1, 2)]


def _pair_flag(fl: FlagView, name: str) -> list[tuple[str, Any]]:
    """Pairs recorded for one pair option, whatever their value type.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
        name (str): the option's kwarg name.
    """
    raw = fl.raw(name)
    return _pair_args(raw) if isinstance(raw, list) else []


def positional_args(fl: FlagView, texts: Sequence[str],
                    has_program_file: bool) -> tuple[str, ...]:
    """The JSON text of each value `$ARGS.positional` reports, from
    --args / --jsonargs.

    The operands after the program stop being input files once either
    flag appears, so they arrive here as ordinary text.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
        texts (Sequence[str]): text operands, program included unless it
            came from a file.
        has_program_file (bool): whether -f supplied the program, which
            frees the first text slot.

    Raises:
        UsageError: when a --jsonargs value is not one JSON value, as
            jq's own parser reads it.
    """
    as_json = fl.as_bool("jsonargs")
    if not as_json and not fl.as_bool("args"):
        return ()
    rest = list(texts) if has_program_file else list(texts[1:])
    if not as_json:
        return tuple(string_text(value) for value in rest)
    values: list[str] = []
    for value in rest:
        parsed = value_text(value.encode())
        if parsed is NO_VALUE:
            raise UsageError(
                f"jq: invalid JSON text passed to --jsonargs\n{USAGE_HINT}", 2)
        values.append(parsed)
    return tuple(values)


def named_args(fl: FlagView) -> dict[str, str]:
    """Collect the $name bindings from --arg and --argjson, each as the
    JSON text of its value.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.

    Raises:
        UsageError: when an --argjson value is not one JSON value, as
            jq's own parser reads it.
    """
    args: dict[str, str] = {}
    for name, value in _pair_args(fl.as_list("arg")):
        args[name] = string_text(str(value))
    for name, value in _pair_args(fl.as_list("argjson")):
        parsed = value_text(str(value).encode())
        if parsed is NO_VALUE:
            raise UsageError(
                f"jq: invalid JSON text passed to --argjson\n{USAGE_HINT}", 2)
        args[name] = parsed
    return args


async def file_args(
    fl: FlagView,
    read_bytes: Callable[..., Awaitable[bytes]],
) -> dict[str, str]:
    """Collect the $name bindings that read a file, each as the JSON text
    of its value.

    --rawfile binds the file's text, --slurpfile the array of documents
    in it, which is the same difference -R draws on the input stream.
    Both read the bytes the way jq reads its inputs.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
        read_bytes (Callable): byte reader for one path.

    Raises:
        UsageError: when a file cannot be read, or a --slurpfile holds
            bad JSON, reported in jq's words.
    """
    args: dict[str, str] = {}
    for name, path in _pair_flag(fl, "rawfile"):
        data = await _load_file(read_bytes, "rawfile", name, path)
        args[name] = string_text(decode_utf8(data))
    for name, path in _pair_flag(fl, "slurpfile"):
        shown = input_name(path)
        data = await _load_file(read_bytes, "slurpfile", name, path)
        texts, failure = await read_texts(InputSource(shown,
                                                      yield_bytes(data)))
        if failure is not None:
            raise UsageError(
                f"jq: Bad JSON in --slurpfile {name} {shown}: "
                f"{failure.message}", ERROR_SYSTEM)
        args[name] = f"[{','.join(texts)}]"
    return args


async def _load_file(read_bytes: Callable[..., Awaitable[bytes]], option: str,
                     name: str, path: PathSpec) -> bytes:
    """One --rawfile or --slurpfile file's bytes.

    Args:
        read_bytes (Callable): byte reader for one path.
        option (str): the option, without its dashes.
        name (str): the variable it binds.
        path (PathSpec): the file.

    Raises:
        UsageError: when the file cannot be read, which jq words as bad
            JSON too.
    """
    try:
        data: bytes = await read_bytes(path)
    except FS_ERRORS as exc:
        shown = input_name(path)
        raise UsageError(
            f"jq: Bad JSON in --{option} {name} {shown}: "
            f"{load_failure(shown, exc)}", ERROR_SYSTEM) from exc
    return data


def parse_flags(fl: FlagView) -> JqOptions:
    """Read the raw jq flag kwargs into a frozen struct.

    Two deliberate divergences from jq's own parser, both from mirage
    parsing a whole line before acting on it rather than one option at a
    time. jq lets ``-c``, ``--tab`` and ``--indent`` override each other
    in the order typed; here ``-c`` wins whenever it appears. And jq
    reads a non-numeric ``--indent`` as 0 (C atoi), where mirage refuses
    it like every other int-typed option.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.

    Raises:
        UsageError: when --indent is out of range.
    """
    width = fl.as_int("indent")
    if width is not None and not INDENT_MIN <= width <= INDENT_MAX:
        raise UsageError(
            f"jq: --indent takes a number between {INDENT_MIN} and "
            f"{INDENT_MAX}\n{USAGE_HINT}", 2)
    # jq spells tab indentation both ways: --tab, or --indent -1.
    tab = fl.as_bool("tab") or width == INDENT_MIN
    indent = DEFAULT_INDENT if width is None or width == INDENT_MIN else width
    join_output = fl.as_bool("join_output")
    nul_output = fl.as_bool("raw_output0")
    return JqOptions(
        null_input=fl.as_bool("null_input"),
        raw_input=fl.as_bool("raw_input"),
        slurp=fl.as_bool("slurp"),
        stream=fl.as_bool("stream"),
        seq=fl.as_bool("seq"),
        # -j and --raw-output0 are -r plus a different separator.
        raw_output=fl.as_bool("raw_output") or join_output or nul_output,
        join_output=join_output,
        nul_output=nul_output,
        compact=fl.as_bool("compact_output"),
        ascii_output=fl.as_bool("ascii_output"),
        sort_keys=fl.as_bool("sort_keys"),
        tab=tab,
        indent=indent,
        exit_status=fl.as_bool("exit_status"),
        named_args=named_args(fl),
    )


def input_name(path: PathSpec) -> str:
    """An input as jq's reports name it: the operand as typed, and
    `<stdin>` for `-`.

    Args:
        path (PathSpec): the operand.
    """
    if path.raw_path == "-":
        return STDIN_NAME
    return path.raw_path or path.virtual


def run_status(run: JqRun[str]) -> int:
    """What jq's process() answers for one run.

    Args:
        run (JqRun[str]): the run, its outputs jq's compact dumps.
    """
    if isinstance(run.stop, JqHalt):
        return OK if run.stop.code is None else int(run.stop.code)
    if isinstance(run.stop, JqError):
        return ERROR_UNKNOWN
    if not run.outputs:
        return OK_NO_OUTPUT
    return OK_NULL_KIND if run.outputs[-1] in NULL_KIND else OK


def exit_code(statuses: Sequence[int], opts: JqOptions) -> int:
    """Exit status for the program run over the whole input, as jq's
    main loop settles it.

    Only the last run counts, even after one that failed, unless it
    printed nothing, when -e looks back to the last value any run
    printed. Without -e only a failure shows, and a halt's own code.

    Args:
        statuses (Sequence[int]): what each run answered (run_status).
        opts (JqOptions): resolved options.
    """
    ret = OK_NO_OUTPUT
    last_result = -1
    for status in statuses:
        ret = status
        if status <= 0 and status != OK_NO_OUTPUT:
            last_result = 0 if status == OK_NULL_KIND else 1
    if not opts.exit_status:
        code = max(ret, 0)
    elif ret != OK_NO_OUTPUT:
        code = abs(ret)
    else:
        code = {-1: 4, 0: 1, 1: 0}[last_result]
    return code % 256


def parse_report(failure: JqParseError, opts: JqOptions) -> str:
    """jq's report of a parse error its main loop meets: fatal, or under
    --seq a line it prints before reading on.

    Args:
        failure (JqParseError): the error.
        opts (JqOptions): resolved options.
    """
    kind = "ignoring parse error" if opts.seq else "parse error"
    return f"jq: {kind}: {failure.message}\n"


class MainLoop:
    """jq's main loop (main.c) over an invocation's input stream.

    Each document runs as soon as the reader parses it, and its outputs
    stream out. A run's error is reported and the next document runs; a
    halt ends the loop; a parse error is reported with status 5 and ends
    it, except under --seq, which reports it and reads on. Under -n the
    program runs once, on null. The exit status and stderr settle on `io`
    once the stream is drained.

    A run of a program that calls `input` or `inputs` reads what they
    take before the program runs (see _run), and nothing past it, so the
    loop never reads further ahead than jq's own.

    An input that cannot be opened or read is reported when the reader
    reaches it, and the reader goes on to the next. The loop checks for
    such a failure before each document it reads, so it stops after the
    run of the document the failing read went on to, and the exit status
    is 2 whatever the runs answered.

    Args:
        sources (list[InputSource]): the inputs, in order, not yet opened.
        expr (str): jq program text.
        opts (JqOptions): resolved options.
        reads (StreamReads): which stream builtins the program calls.
        args (str | None): the value of `$ARGS`, as text.
        io (IOResult): the result to settle.
    """

    def __init__(self, sources: list[InputSource], expr: str, opts: JqOptions,
                 reads: StreamReads, args: str | None, io: IOResult) -> None:
        self._reports: list[str] = []
        self._reader = InputReader(sources, opts, self._reports.append)
        self._expr = expr
        self._opts = opts
        self._reads = reads
        self._args = args
        self._io = io
        self._statuses: list[int] = []

    async def outputs(self) -> AsyncIterator[bytes]:
        """The invocation's stdout, run by run."""
        try:
            if self._opts.null_input:
                run, position = await self._run("null",
                                                self._reader.position())
                if run.outputs:
                    yield format_jq_output(run.outputs, self._opts)
                self._settle(run, position)
                return
            while not self._reader.failures():
                item = await self._reader.next_input()
                if item is NO_VALUE:
                    return
                if isinstance(item, JqParseError):
                    self._fail(item)
                    if self._opts.seq:
                        continue
                    return
                run, position = await self._run(item, self._reader.position())
                if run.outputs:
                    yield format_jq_output(run.outputs, self._opts)
                if self._settle(run, position):
                    return
        finally:
            self._io.exit_code = (ERROR_SYSTEM if self._reader.failures() else
                                  exit_code(self._statuses, self._opts))
            if self._reports:
                self._io.stderr = "".join(self._reports).encode()

    async def _run(self, doc: str, position: str) -> tuple[JqRun[str], str]:
        """Run the program on one document, and say where the reader
        stands after it, for its error report. The run is what jq's main
        loop gets to print (see printable).

        `input` and `inputs` consume the stream the main loop reads, so a
        run reads what they take first, and the next run starts past it.
        How much a run takes is a runtime fact libjq's Python binding does
        not report, so mirage assumes what the idioms do: `inputs` drains
        the rest (`[., inputs]`, `reduce inputs as $x`), and `input` alone
        takes one (`[., input]` pairs the documents up). A program that
        takes some other count (`first(inputs)`, an `input` in a branch
        not taken) leaves real jq a different remainder for its next run
        than here. A parse error stops the reading: the run raises it
        where `input` or `inputs` would reach it, and the main loop reads
        on past it.

        Args:
            doc (str): the run's own document, null under -n.
            position (str): where the reader stood once it had read it.
        """
        reads = self._reads
        if not (reads.input or reads.inputs):
            run = jq_run_texts(doc, self._expr, self._opts.named_args, None,
                               self._args)
            return printable(run, self._opts), position
        docs: list[str] = []
        failure: JqParseError | None = None
        while True:
            item = await self._reader.next_input()
            position = self._reader.position()
            if item is NO_VALUE:
                break
            if isinstance(item, JqParseError):
                failure = item
                break
            docs.append(item)
            if not reads.inputs:
                break
        run = jq_run_texts(doc, self._expr, self._opts.named_args, docs,
                           self._args,
                           None if failure is None else failure.message)
        return printable(run, self._opts), position

    def _settle(self, run: JqRun[str], position: str) -> bool:
        # Fold one run into the invocation: its answer toward the exit
        # status, and its report when it stopped early. A halt ends the
        # invocation, which is what this answers.
        self._statuses.append(run_status(run))
        if isinstance(run.stop, JqError):
            self._reports.append(error_report(position, run.stop))
        elif isinstance(run.stop, JqHalt):
            self._reports.append(halt_report(run.stop))
            return True
        return False

    def _fail(self, failure: JqParseError) -> None:
        # jq's `ret = JQ_ERROR_UNKNOWN; break`, or under --seq a report
        # that leaves the status alone.
        self._reports.append(parse_report(failure, self._opts))
        if not self._opts.seq:
            self._statuses.append(ERROR_UNKNOWN)


async def jq_generic(
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
    read_bytes: Callable[..., Awaitable[bytes]],
    read_stream: Callable[..., AsyncIterator[bytes]],
) -> tuple[ByteSource | None, IOResult]:
    """Full-command jq entry; mirrors jqGeneric's (paths, texts, opts).

    The kwargs core below keeps the historical shape; this entry is the
    dispatcher-facing seam so the builder stays wiring.
    """
    return await jq(paths,
                    *texts,
                    read_bytes=read_bytes,
                    read_stream=read_stream,
                    stdin=opts.stdin,
                    dispatch=opts.dispatch,
                    **opts.flags)


async def jq(
    paths: list[PathSpec],
    *texts: str,
    read_bytes: Callable[..., Awaitable[bytes]],
    read_stream: Callable[..., AsyncIterator[bytes]],
    stdin: ByteSource | None = None,
    dispatch: DispatchFn | None = None,
    **flags: FlagValue,
) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(flags, spec=SPECS["jq"])
    opts = parse_flags(fl)
    read_bytes = stdin_bytes(read_bytes, stdin)
    read_stream = stdin_stream(read_stream, stdin)

    async def read_flag_file(path: PathSpec) -> bytes:
        # --rawfile / --slurpfile route nothing (the executor's
        # DOOR_FLAG_KEYS), so the file may sit on another mount than the
        # operands: it is read through the door, stdin excepted, which is
        # the invocation's own.
        if dispatch is None or is_stdin(path):
            return await read_bytes(path)
        return await read_program_file("jq", path, dispatch)

    program_file = fl.raw("from_file")
    if isinstance(program_file, PathSpec):
        expression = (await read_bytes(program_file)).decode()
    else:
        # jq defaults the filter to "." when no expression is given.
        expression = texts[0] if texts else "."
    expr = expression.strip()
    reads = stream_reads(expr)
    reads_stream = reads.input or reads.inputs
    # --rawfile / --slurpfile read a file each, so they join the bindings
    # only once the backend reader is in hand.
    opts = dataclasses.replace(
        opts,
        named_args={
            **opts.named_args,
            **await file_args(fl, read_flag_file)
        },
        positional_args=positional_args(fl, texts,
                                        isinstance(program_file, PathSpec)),
    )
    args = args_text(opts) if references_args(expr) else None
    try:
        jq_check(expr, opts.named_args, [] if reads_stream else None, args)
    except JqCompileError as exc:
        # jq compiles its program before it opens a single input, so a
        # refusal is all it prints.
        return None, IOResult(exit_code=ERROR_COMPILE,
                              stderr=f"{exc}\n".encode())

    sources: list[InputSource] = []
    # -n does not read its inputs at all unless the program asks for them
    # through `input` or `inputs`, which is why jq -n never opens a
    # missing file. Each input is opened when the reader reaches it, as
    # jq opens its files one after another.
    if not opts.null_input or reads_stream:
        if paths:
            for path in paths:
                sources.append(InputSource(input_name(path),
                                           read_stream(path)))
        elif stdin is not None:
            sources.append(InputSource(STDIN_NAME, resolve_source(stdin)))
    io = IOResult()
    loop = MainLoop(sources, expr, opts, reads, args, io)
    return loop.outputs(), io


__all__ = ["jq"]

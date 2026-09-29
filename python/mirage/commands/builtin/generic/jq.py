import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import orjson

from mirage.commands.builtin.utils.stream import stdin_bytes, stdin_stream
from mirage.commands.config import CommandOpts
from mirage.commands.errors import UsageError
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.core.jq import (DEFAULT_INDENT, STDIN_NAME, UNKNOWN_POSITION,
                            InputPositions, JqCompileError, JqError, JqHalt,
                            JqOptions, JqRun, StreamReads, args_object,
                            error_report, eval_jsonl_stream, format_jq_output,
                            halts, is_jsonl_path, is_streamable_jsonl_expr,
                            jq_check, jq_run, parse_json_docs, parse_json_text,
                            parse_seq_text, references_args, split_raw_text,
                            stream_events, stream_reads)
from mirage.io.types import ByteSource, IOResult
from mirage.types import JsonValue, PathSpec

INDENT_MIN = -1
INDENT_MAX = 7

# What jq's process() answers for one run, which its exit status is made
# of (main.c): the last output was not false or null, it was, there was
# none, and an error no `try` caught ended the run.
OK = 0
OK_NULL_KIND = -1
OK_NO_OUTPUT = -4
ERROR_UNKNOWN = 5

# jq's exit status when it refuses the program itself.
ERROR_COMPILE = 3

USAGE_HINT = ("Use jq --help for help with command-line options,\n"
              "or see the jq manpage, or online docs  at "
              "https://jqlang.github.io/jq")


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
                    has_program_file: bool) -> tuple[Any, ...]:
    """Values `$ARGS.positional` reports, from --args / --jsonargs.

    The operands after the program stop being input files once either
    flag appears, so they arrive here as ordinary text.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
        texts (Sequence[str]): text operands, program included unless it
            came from a file.
        has_program_file (bool): whether -f supplied the program, which
            frees the first text slot.

    Raises:
        UsageError: when a --jsonargs value is not JSON.
    """
    as_json = fl.as_bool("jsonargs")
    if not as_json and not fl.as_bool("args"):
        return ()
    rest = list(texts) if has_program_file else list(texts[1:])
    if not as_json:
        return tuple(rest)
    values: list[Any] = []
    for value in rest:
        try:
            values.append(orjson.loads(value))
        except orjson.JSONDecodeError as exc:
            raise UsageError(
                f"jq: invalid JSON text passed to --jsonargs\n{USAGE_HINT}",
                2) from exc
    return tuple(values)


def named_args(fl: FlagView) -> dict[str, Any]:
    """Collect the $name bindings from --arg and --argjson.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.

    Raises:
        UsageError: when an --argjson value is not JSON.
    """
    args: dict[str, Any] = {}
    for name, value in _pair_args(fl.as_list("arg")):
        args[name] = value
    for name, value in _pair_args(fl.as_list("argjson")):
        try:
            args[name] = orjson.loads(value)
        except orjson.JSONDecodeError as exc:
            raise UsageError(
                f"jq: invalid JSON text passed to --argjson\n{USAGE_HINT}",
                2) from exc
    return args


async def file_args(
    fl: FlagView,
    read_bytes: Callable[..., Awaitable[bytes]],
) -> dict[str, Any]:
    """Collect the $name bindings that read a file.

    --rawfile binds the file's text, --slurpfile the array of documents
    in it, which is the same difference -R draws on the input stream.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
        read_bytes (Callable): backend byte reader for one path.
    """
    args: dict[str, Any] = {}
    for name, path in _pair_flag(fl, "rawfile"):
        args[name] = (await read_bytes(path)).decode("utf-8", errors="replace")
    for name, path in _pair_flag(fl, "slurpfile"):
        args[name] = parse_json_docs(await read_bytes(path))
    return args


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


def assemble_inputs(sources: Sequence[tuple[str, bytes]],
                    opts: JqOptions) -> tuple[list[JsonValue], InputPositions]:
    """Turn the raw inputs into the value stream the program sees, and
    say where jq's reader stands once it has read each value.

    jq reads every file and stdin as one stream, so slurping spans them
    all rather than restarting per file. Line splitting stays per input:
    a file with no trailing newline ends its last line there instead of
    joining it to the next file's first.

    Args:
        sources (Sequence[tuple[str, bytes]]): each input's name, as jq
            reports it, and its bytes, in order.
        opts (JqOptions): resolved options.
    """
    names = [name for name, _ in sources]
    texts = [raw.decode("utf-8", errors="replace") for _, raw in sources]
    docs: list[JsonValue] = []
    marks: list[tuple[int, int]] = []
    if opts.raw_input and opts.slurp:
        docs.append("".join(texts))
    elif opts.raw_input:
        for i, text in enumerate(texts):
            lines, ends = split_raw_text(text)
            docs.extend(lines)
            marks.extend((i, end) for end in ends)
    else:
        parse = parse_seq_text if opts.seq else parse_json_text
        for i, text in enumerate(texts):
            values, ends = parse(text)
            docs.extend(values)
            marks.extend((i, end) for end in ends)
        if opts.stream:
            # --stream replaces each document with its events, and
            # slurping then collects the events rather than the
            # documents. Each event reads as where its document is whole,
            # where jq's streaming parser hands events over as it goes.
            events = [stream_events(doc) for doc in docs]
            docs = [event for group in events for event in group]
            marks = [mark for mark, group in zip(marks, events) for _ in group]
        if opts.slurp:
            docs = [docs]
    if opts.slurp:
        # One value, and whole only once every input is read.
        marks = [(len(texts) - 1, len(texts[-1]))] if texts else []
    return docs, InputPositions(names, texts, marks)


def run_status(run: JqRun) -> int:
    """What jq's process() answers for one run.

    Args:
        run (JqRun): the run.
    """
    if isinstance(run.stop, JqHalt):
        return OK if run.stop.code is None else int(run.stop.code)
    if isinstance(run.stop, JqError):
        return ERROR_UNKNOWN
    if not run.outputs:
        return OK_NO_OUTPUT
    last = run.outputs[-1]
    return OK_NULL_KIND if last is None or last is False else OK


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


def run_position(positions: InputPositions, reads: StreamReads,
                 first: int | None, taken: int) -> str:
    """Where jq's reader stands after a run, for its error report.

    A run reads its own document, and past it the ones `input` and
    `inputs` take: `inputs` reads to the end, and so does an `input`
    that finds nothing left.

    Args:
        positions (InputPositions): the input stream's positions.
        reads (StreamReads): which stream builtins the program calls.
        first (int | None): the run's own document, None under -n.
        taken (int): how many more documents the run was handed.
    """
    if reads.inputs or (reads.input and taken == 0):
        return positions.end()
    if reads.input:
        return positions.at(0 if first is None else first + 1)
    return UNKNOWN_POSITION if first is None else positions.at(first)


async def _read_stdin_bytes(stdin: ByteSource | None) -> bytes:
    if isinstance(stdin, bytes):
        return stdin
    if stdin is None:
        return b""
    raw = b""
    async for chunk in stdin:
        raw += chunk
    return raw


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
                    **opts.flags)


async def jq(
    paths: list[PathSpec],
    *texts: str,
    read_bytes: Callable[..., Awaitable[bytes]],
    read_stream: Callable[..., AsyncIterator[bytes]],
    stdin: ByteSource | None = None,
    **flags: FlagValue,
) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(flags, spec=SPECS["jq"])
    opts = parse_flags(fl)
    read_bytes = stdin_bytes(read_bytes, stdin)
    read_stream = stdin_stream(read_stream, stdin)
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
            **await file_args(fl, read_bytes)
        },
        positional_args=positional_args(fl, texts,
                                        isinstance(program_file, PathSpec)),
    )
    args_value = args_object(opts) if references_args(expr) else None
    try:
        jq_check(expr, opts.named_args, [] if reads_stream else None,
                 args_value)
    except JqCompileError as exc:
        # jq compiles its program before it opens a single input, so a
        # refusal is all it prints.
        return None, IOResult(exit_code=ERROR_COMPILE,
                              stderr=f"{exc}\n".encode())

    # The per-line path rewrites the program to run on one element, so it
    # can only serve a run whose input stream is the file's documents and
    # whose exit code does not depend on the last of them. A halt reports
    # on stderr and sets the exit code, which a stream of outputs has no
    # room for.
    streamable = (paths and is_jsonl_path(paths[0].virtual)
                  and is_streamable_jsonl_expr(expr) and not opts.null_input
                  and not opts.raw_input and not opts.slurp and not opts.stream
                  and not opts.seq and not opts.exit_status
                  and not reads_stream and not halts(expr))
    if streamable:
        return eval_jsonl_stream(read_stream(paths[0]), expr, opts,
                                 paths[0].raw_path
                                 or paths[0].virtual), IOResult()

    sources: list[tuple[str, bytes]] = []
    # -n does not read its inputs at all unless the program asks for them
    # through `input` or `inputs`, which is why jq -n never opens a
    # missing file.
    if not opts.null_input or reads_stream:
        if paths:
            for path in paths:
                sources.append((path.raw_path or path.virtual, await
                                read_bytes(path)))
        elif stdin is not None:
            sources.append((STDIN_NAME, await _read_stdin_bytes(stdin)))
    docs, positions = assemble_inputs(sources, opts)

    def unread(at: int) -> list[JsonValue]:
        # A run sees only the documents it can read: all of the rest when
        # it calls `inputs`, or the one `input` takes when it calls only
        # that.
        return docs[at:] if reads.inputs else docs[at:at + 1]

    outputs: list[JsonValue] = []
    statuses: list[int] = []
    reports: list[str] = []

    def settle(run: JqRun, first: int | None, taken: int) -> bool:
        # Fold one run into the invocation: its outputs, its answer toward
        # the exit status, and its report when it stopped early. A halt
        # ends the invocation, which is what this answers.
        outputs.extend(run.outputs)
        statuses.append(run_status(run))
        if isinstance(run.stop, JqError):
            reports.append(
                error_report(run_position(positions, reads, first, taken),
                             run.stop))
        elif isinstance(run.stop, JqHalt):
            reports.append(run.stop.text)
            return True
        return False

    if opts.null_input:
        rest = unread(0) if reads_stream else None
        settle(jq_run(None, expr, opts.named_args, rest, args_value), None,
               len(rest or ()))
    elif reads_stream:
        # `input` and `inputs` consume from the same stream the main loop
        # reads, so each run starts past whatever the one before it took.
        # How much a run takes is a runtime fact libjq's Python binding
        # does not report, so mirage assumes what the idioms do: `inputs`
        # drains the rest (`[., inputs]`, `reduce inputs as $x`), and
        # `input` alone takes one (`[., input]` pairs the documents up). A
        # program that takes some other count (`first(inputs)`, an `input`
        # in a branch not taken) leaves real jq a different remainder for
        # its next run than here.
        at = 0
        while at < len(docs):
            rest = unread(at + 1)
            run = jq_run(docs[at], expr, opts.named_args, rest, args_value)
            if settle(run, at, len(rest)):
                break
            at += 1 + len(rest)
    else:
        # jq applies the program to every document in the stream, and goes
        # on past one whose run failed.
        for at, doc in enumerate(docs):
            run = jq_run(doc, expr, opts.named_args, None, args_value)
            if settle(run, at, 0):
                break
    return format_jq_output(outputs, opts), IOResult(
        exit_code=exit_code(statuses, opts),
        stderr="".join(reports).encode() if reports else None)


__all__ = ["jq"]

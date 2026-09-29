import pytest

from mirage.commands.builtin.generic.jq import (exit_code, input_name, jq,
                                                named_args, parse_flags,
                                                positional_args, run_position,
                                                run_status)
from mirage.commands.errors import UsageError
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.core.jq import JqError, JqHalt, JqOptions, JqRun, StreamReads
from mirage.io.types import materialize
from mirage.types import PathSpec

FILES = {
    "/d/user.json": b'{"name":"alice","age":30}\n',
    "/d/multi.json": b'{"a":1}\n{"a":2}\n{"a":3}\n',
    "/d/lines.txt": b"alpha\nbeta\ngamma\n",
    "/d/empty.txt": b"",
    "/d/prog.jq": b".name\n",
    "/d/lines2.txt": b"alpha\nbeta\ngamma\n",
    "/d/a.json": b'{"a":1}\n',
    "/d/b.json": b'{"b":2}\n',
    "/d/fields.json": b'{"inputs":1}\n{"inputs":2}\n',
    "/d/four.json": b"1\n2\n3\n4\n",
    "/d/empty.json": b"",
    "/d/bad.json": b'{"a":1}\n{"a":2}\n[',
    "/d/rows.jsonl": b'{"a":1}\n{"a":2}\n',
    "/d/pairs.jsonl": b"[1,2]\n[3]\n",
    "/d/seq.json": b'\x1e1\n\x1e[1 2]\n\x1e3\n',
    "/d/seq_mid.json": b'\x1e1\n\x1e2\n\x1e[1 2]\n\x1e3\n\x1e4\n',
    "/d/mid.json": b"1\n[1 2]\n3\n4\n",
    "/d/one.json": b"1",
    "/d/two.json": b" 2\n",
}


async def _read_bytes(path: PathSpec) -> bytes:
    return FILES[path.virtual]


async def _read_stream(path: PathSpec):
    data = FILES[path.virtual]
    for at in range(0, len(data), 5):
        yield data[at:at + 5]


def _path(virtual: str) -> PathSpec:
    return PathSpec(virtual, virtual.rsplit("/", 1)[0], virtual.lstrip("/"))


def _spec_flags(**flags: object) -> FlagView:
    return FlagView(flags, spec=SPECS["jq"])


def _printed(*outputs: object) -> int:
    return run_status(JqRun(list(outputs)))


async def _run(paths: list[str], *texts: str, **flags: object) -> tuple:
    source, io = await jq([_path(p) for p in paths],
                          *texts,
                          read_bytes=_read_bytes,
                          read_stream=_read_stream,
                          **flags)
    return await materialize(source) if source is not None else b"", io


def test_join_and_nul_output_imply_raw():
    assert parse_flags(_spec_flags(join_output=True)).raw_output
    assert parse_flags(_spec_flags(raw_output0=True)).raw_output


def test_indent_minus_one_is_tab_indentation():
    opts = parse_flags(_spec_flags(indent="-1"))
    assert opts.tab
    assert opts.indent == 2


def test_indent_out_of_range_is_a_usage_error():
    with pytest.raises(UsageError, match="between -1 and 7"):
        parse_flags(_spec_flags(indent="8"))


def test_named_args_pair_up_the_flattened_tokens():
    args = named_args(_spec_flags(arg=["a", "1", "b", "2"]))
    assert args == {"a": "1", "b": "2"}


def test_argjson_parses_its_value_as_json():
    args = named_args(_spec_flags(argjson=["v", '{"k":[1,2]}']))
    assert args == {"v": {"k": [1, 2]}}


def test_argjson_rejects_invalid_json():
    with pytest.raises(UsageError, match="invalid JSON text"):
        named_args(_spec_flags(argjson=["v", "nope"]))


def test_exit_status_reads_the_last_output_only():
    opts = JqOptions(exit_status=True)
    assert exit_code([_printed(1, False)], opts) == 1
    assert exit_code([_printed(False, 1)], opts) == 0
    assert exit_code([_printed(None)], opts) == 1
    assert exit_code([], opts) == 4


def test_exit_status_is_zero_without_the_flag():
    assert exit_code([], JqOptions()) == 0
    assert exit_code([_printed(None)], JqOptions()) == 0


def test_a_failed_run_counts_only_when_it_is_the_last_one():
    failed = run_status(JqRun([1], JqError("x", True)))
    assert exit_code([failed, _printed(1)], JqOptions()) == 0
    assert exit_code([_printed(1), failed], JqOptions()) == 5
    assert exit_code([failed, _printed(False)],
                     JqOptions(exit_status=True)) == 1


def test_exit_status_looks_back_past_runs_that_printed_nothing():
    opts = JqOptions(exit_status=True)
    assert exit_code([_printed(False), _printed()], opts) == 1
    assert exit_code([_printed(1), _printed()], opts) == 0


@pytest.mark.parametrize("code, exit_status, expected", [
    (None, False, 0),
    (2, False, 2),
    (-1, False, 0),
    (-1, True, 1),
    (1.5, False, 1),
    (300, False, 44),
])
def test_a_halt_exits_with_its_own_code(code, exit_status, expected):
    status = run_status(JqRun([False], JqHalt(None, False, code)))
    assert exit_code([status], JqOptions(exit_status=exit_status)) == expected


def test_a_run_is_placed_where_the_reader_stops_for_it():
    positions = ["f0.json:1", "f0.json:2", "f0.json:3"]
    end = "f0.json:3"
    none = StreamReads(input=False, inputs=False)
    one = StreamReads(input=True, inputs=False)
    rest = StreamReads(input=False, inputs=True)
    assert run_position(positions, end, none, 1, 0, False) == "f0.json:2"
    assert run_position(positions, end, none, None, 0, False) == "<unknown>"
    assert run_position(positions, end, one, 0, 1, False) == "f0.json:2"
    assert run_position(positions, end, one, 2, 0, False) == "f0.json:3"
    assert run_position(positions, end, rest, 0, 2, False) == "f0.json:3"
    # A parse error stops `inputs` where the reader met it.
    assert run_position(positions, "f0.json:9", rest, 0, 1,
                        True) == "f0.json:2"


def test_an_input_is_named_as_typed_and_dash_as_stdin():
    assert input_name(
        PathSpec("/d/a.json", "/d", "d/a.json", raw_path="a.json")) == "a.json"
    assert input_name(PathSpec("/d/a.json", "/d", "d/a.json")) == "/d/a.json"
    assert input_name(PathSpec("/dev/stdin", "/dev", "dev/stdin",
                               raw_path="-")) == "<stdin>"


@pytest.mark.asyncio
async def test_raw_input_reads_each_line_as_a_string():
    out, io = await _run(["/d/lines.txt"], ".", raw_input=True)
    assert out == b'"alpha"\n"beta"\n"gamma"\n'
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_raw_slurp_is_one_string_including_the_last_newline():
    out, _ = await _run(["/d/lines.txt"], ".", raw_input=True, slurp=True)
    assert out == b'"alpha\\nbeta\\ngamma\\n"\n'


@pytest.mark.asyncio
async def test_null_input_with_inputs_collects_the_whole_stream():
    out, _ = await _run(["/d/lines.txt"],
                        "[inputs]",
                        raw_input=True,
                        null_input=True,
                        compact_output=True)
    assert out == b'["alpha","beta","gamma"]\n'


@pytest.mark.asyncio
async def test_null_input_never_reads_its_operands():
    out, io = await _run(["/d/missing.json"], "1+2", null_input=True)
    assert out == b"3\n"
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_inputs_without_null_input_drains_the_stream_once():
    out, _ = await _run(["/d/multi.json"], "[., inputs]", compact_output=True)
    assert out == b'[{"a":1},{"a":2},{"a":3}]\n'


@pytest.mark.asyncio
async def test_null_input_gives_input_the_first_document():
    out, _ = await _run(["/d/four.json"],
                        "input",
                        null_input=True,
                        compact_output=True)
    assert out == b"1\n"


@pytest.mark.asyncio
async def test_inputs_starts_after_what_input_took():
    out, _ = await _run(["/d/four.json"],
                        "input as $h | [inputs]",
                        null_input=True,
                        compact_output=True)
    assert out == b"[2,3,4]\n"
    out, _ = await _run(["/d/four.json"],
                        "[input, inputs]",
                        null_input=True,
                        compact_output=True)
    assert out == b"[1,2,3,4]\n"


@pytest.mark.asyncio
async def test_input_alone_takes_one_document_per_run():
    out, _ = await _run(["/d/four.json"], "[., input]", compact_output=True)
    assert out == b"[1,2]\n[3,4]\n"
    out, _ = await _run(["/d/four.json"], "input", compact_output=True)
    assert out == b"2\n4\n"


@pytest.mark.asyncio
async def test_input_fails_with_break_on_an_empty_stream():
    out, io = await _run(["/d/empty.json"], "input", null_input=True)
    assert (out, io.exit_code) == (b"", 5)
    assert await materialize(io.stderr
                             ) == b"jq: error (at /d/empty.json:0): break\n"


@pytest.mark.asyncio
async def test_a_field_named_inputs_still_runs_per_document():
    out, _ = await _run(["/d/fields.json"], ".inputs", compact_output=True)
    assert out == b"1\n2\n"


@pytest.mark.asyncio
async def test_the_word_inputs_in_a_string_still_runs_per_document():
    out, _ = await _run(["/d/multi.json"], '"no inputs"', compact_output=True)
    assert out == b'"no inputs"\n"no inputs"\n"no inputs"\n'


@pytest.mark.asyncio
async def test_slurp_covers_operands_together():
    out, _ = await _run(["/d/a.json", "/d/b.json"],
                        ".",
                        slurp=True,
                        compact_output=True)
    assert out == b'[{"a":1},{"b":2}]\n'


@pytest.mark.asyncio
async def test_empty_input_prints_nothing_and_exits_zero():
    out, io = await _run(["/d/empty.txt"], ".")
    assert out == b""
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_named_args_reach_the_program():
    out, _ = await _run(["/d/user.json"],
                        "[.name, $v]",
                        arg=["v", "hi"],
                        compact_output=True)
    assert out == b'["alice","hi"]\n'


@pytest.mark.asyncio
async def test_from_file_reads_the_program_off_a_path():
    path = _path("/d/prog.jq")
    out, _ = await _run(["/d/user.json"], from_file=path)
    assert out == b'"alice"\n'


@pytest.mark.asyncio
async def test_exit_status_flag_reports_a_null_output():
    out, io = await _run(["/d/user.json"], ".missing", exit_status=True)
    assert out == b"null\n"
    assert io.exit_code == 1


@pytest.mark.asyncio
async def test_exit_status_flag_reports_no_output_at_all():
    out, io = await _run(["/d/user.json"], "empty", exit_status=True)
    assert out == b""
    assert io.exit_code == 4


def test_positional_args_are_text_by_default():
    fl = _spec_flags(args=True)
    assert positional_args(fl, [".", "a", "b"], False) == ("a", "b")


def test_positional_args_keep_every_operand_when_f_gave_the_program():
    fl = _spec_flags(args=True)
    assert positional_args(fl, ["a", "b"], True) == ("a", "b")


def test_jsonargs_parses_each_operand():
    fl = _spec_flags(jsonargs=True)
    assert positional_args(fl, [".", "1", '{"k":2}'], False) == (1, {"k": 2})


def test_jsonargs_rejects_invalid_json():
    with pytest.raises(UsageError, match="invalid JSON text"):
        positional_args(_spec_flags(jsonargs=True), [".", "nope"], False)


def test_no_positional_args_without_the_flags():
    assert positional_args(_spec_flags(), [".", "a"], False) == ()


@pytest.mark.asyncio
async def test_rawfile_binds_the_files_text():
    out, _ = await _run([],
                        "$x",
                        null_input=True,
                        compact_output=True,
                        rawfile=["x", _path("/d/lines.txt")])
    assert out == b'"alpha\\nbeta\\ngamma\\n"\n'


@pytest.mark.asyncio
async def test_slurpfile_binds_the_files_documents():
    out, _ = await _run([],
                        "$x",
                        null_input=True,
                        compact_output=True,
                        slurpfile=["x", _path("/d/multi.json")])
    assert out == b'[{"a":1},{"a":2},{"a":3}]\n'


@pytest.mark.asyncio
async def test_args_reach_the_program_through_dollar_args():
    out, _ = await _run([],
                        "$ARGS",
                        "a",
                        "b",
                        null_input=True,
                        compact_output=True,
                        args=True)
    assert out == b'{"positional":["a","b"],"named":{}}\n'


@pytest.mark.asyncio
async def test_dollar_args_carries_the_named_bindings():
    out, _ = await _run([],
                        "$ARGS.named",
                        null_input=True,
                        compact_output=True,
                        arg=["v", "hi"])
    assert out == b'{"v":"hi"}\n'


@pytest.mark.asyncio
async def test_dollar_args_is_defined_with_no_bindings_at_all():
    out, _ = await _run([], "$ARGS", null_input=True, compact_output=True)
    assert out == b'{"positional":[],"named":{}}\n'


@pytest.mark.asyncio
async def test_stream_reads_a_document_as_events():
    out, _ = await _run(["/d/a.json"], ".", stream=True, compact_output=True)
    assert out == b'[["a"],1]\n[["a"]]\n'


@pytest.mark.asyncio
async def test_seq_writes_a_separator_before_each_value():
    out, _ = await _run([],
                        "1,2",
                        null_input=True,
                        seq=True,
                        compact_output=True)
    assert out == b"\x1e1\n\x1e2\n"


async def _ran(path: str, program: str) -> tuple[bytes, bytes, int]:
    out, io = await _run([path], program, compact_output=True)
    return out, await materialize(io.stderr), io.exit_code


@pytest.mark.asyncio
async def test_a_run_prints_what_came_before_an_error_and_goes_on():
    assert await _ran("/d/four.json",
                      'if . == 2 then error("two") else . end') == (
                          b"1\n3\n4\n",
                          b"jq: error (at /d/four.json:2): two\n", 0)
    out, _, code = await _ran("/d/four.json",
                              "., error({n: .}) | select(. > 3)")
    assert (out, code) == (b"4\n", 5)


@pytest.mark.asyncio
async def test_a_report_says_when_the_message_was_not_a_string():
    _, err, _ = await _ran("/d/four.json",
                           "if . == 4 then error({n: .}) else empty end")
    assert err == b'jq: error (at /d/four.json:4) (not a string): {"n":4}\n'


@pytest.mark.asyncio
async def test_a_halt_ends_the_whole_invocation():
    assert await _ran(
        "/d/four.json",
        'if . == 2 then "bye\\n" | halt_error(3) else . end') == (b"1\n",
                                                                  b"bye\n", 3)
    assert await _ran("/d/four.json",
                      "if . == 3 then halt else . end") == (b"1\n2\n", b"", 0)


@pytest.mark.asyncio
async def test_a_halt_inside_a_collector_halts_as_from_the_top():
    assert await _ran("/d/four.json",
                      "if . == 2 then [halt_error(3)] else . end") == (b"1\n",
                                                                       b"2\n",
                                                                       3)


@pytest.mark.asyncio
async def test_a_halt_ends_the_command_even_inside_a_try():
    assert await _ran(
        "/d/four.json",
        'try (if . == 2 then halt_error(3) else . end) catch "continued"') == (
            b"1\n", b"2\n", 3)


@pytest.mark.asyncio
async def test_a_program_that_does_not_compile_is_refused_before_any_read():
    out, err, code = await _ran("/d/missing.json", "1 +")
    assert (out, code) == (b"", 3)
    assert err.startswith(b"jq: error: syntax error, ")
    assert err.endswith(b"jq: 1 compile error\n")


async def _flagged(paths: list[str], program: str,
                   **flags: object) -> tuple[bytes, bytes, int]:
    out, io = await _run(paths, program, **flags)
    return out, await materialize(io.stderr), io.exit_code


@pytest.mark.asyncio
async def test_a_parse_error_ends_the_loop_after_the_documents_before_it():
    assert await _ran(
        "/d/bad.json",
        ".a") == (b"1\n2\n",
                  b"jq: parse error: Unfinished JSON term at EOF at line 3, "
                  b"column 1\n", 5)


@pytest.mark.asyncio
async def test_a_parse_error_exits_five_under_exit_status_too():
    out, err, code = await _flagged(["/d/bad.json"], ".a", exit_status=True)
    assert (out, code) == (b"1\n2\n", 5)
    assert err.startswith(b"jq: parse error: ")


@pytest.mark.asyncio
async def test_a_slurp_that_meets_a_parse_error_prints_nothing():
    assert await _flagged(["/d/bad.json"], ".", slurp=True) == (
        b"", b"jq: parse error: Unfinished JSON term at EOF at line 3, "
        b"column 1\n", 5)


@pytest.mark.asyncio
async def test_seq_reports_a_parse_error_and_reads_on():
    assert await _flagged(["/d/seq.json"], ".", seq=True,
                          compact_output=True) == (
                              b"\x1e1\n\x1e3\n",
                              b"jq: ignoring parse error: Expected separator "
                              b"between values at line 2, column 6 (need RS "
                              b"to resync)\n", 0)


@pytest.mark.asyncio
async def test_inputs_meets_the_parse_error_as_a_runtime_error():
    assert await _flagged(["/d/bad.json"], "[inputs]", null_input=True) == (
        b"", b"jq: error (at /d/bad.json:2): Unfinished JSON term at EOF at "
        b"line 3, column 1\n", 5)
    out, err, code = await _flagged(["/d/bad.json"],
                                    "try ([inputs]) catch .",
                                    null_input=True)
    assert (out, err,
            code) == (b'"Unfinished JSON term at EOF at line 3, column 1"\n',
                      b"", 0)


@pytest.mark.asyncio
async def test_input_leaves_the_parse_error_to_the_main_loop():
    assert await _flagged(["/d/bad.json"], "[., input]",
                          compact_output=True) == (
                              b'[{"a":1},{"a":2}]\n',
                              b"jq: parse error: Unfinished JSON term at EOF "
                              b"at line 3, column 1\n", 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("program", ["[., input]", "[., inputs]"])
async def test_a_run_that_reads_a_parse_error_fails_and_the_loop_reads_on(
        program):
    assert await _flagged(["/d/mid.json"], program, compact_output=True) == (
        b"[3,4]\n", b"jq: error (at /d/mid.json:2): Expected separator "
        b"between values at line 2, column 5\n", 0)


@pytest.mark.asyncio
async def test_seq_reads_past_a_parse_error_a_run_or_the_loop_meets():
    assert await _flagged(["/d/seq.json"],
                          "[., inputs]",
                          seq=True,
                          compact_output=True) == (
                              b"\x1e[3]\n",
                              b"jq: error (at /d/seq.json:2): Expected "
                              b"separator between values at line 2, column 6 "
                              b"(need RS to resync)\n", 0)
    assert await _flagged(["/d/seq_mid.json"],
                          "[., input]",
                          seq=True,
                          compact_output=True) == (
                              b"\x1e[1,2]\n\x1e[3,4]\n",
                              b"jq: ignoring parse error: Expected separator "
                              b"between values at line 3, column 6 (need RS "
                              b"to resync)\n", 0)


@pytest.mark.asyncio
async def test_a_halt_ends_the_command_before_the_parse_error():
    assert await _flagged(["/d/bad.json"],
                          "[., input] | halt_error",
                          compact_output=True) == (b"", b'[{"a":1},{"a":2}]\n',
                                                   5)


@pytest.mark.asyncio
async def test_a_value_runs_on_from_one_input_into_the_next():
    assert await _flagged(
        ["/d/one.json", "/d/two.json"],
        "error(tostring)") == (b"", b"jq: error (at /d/two.json:1): 1\n"
                               b"jq: error (at /d/two.json:1): 2\n", 5)


@pytest.mark.asyncio
async def test_json_lines_run_the_program_on_each_line_unchanged():
    assert await _flagged(["/d/rows.jsonl"], ".[]",
                          compact_output=True) == (b"1\n2\n", b"", 0)
    assert await _flagged(["/d/pairs.jsonl"],
                          ".[] | . + 1",
                          compact_output=True) == (b"2\n3\n4\n", b"", 0)
    out, err, code = await _flagged(["/d/rows.jsonl"], ".[].a")
    assert (out, code) == (b"", 5)
    assert err == (b'jq: error (at /d/rows.jsonl:1): Cannot index number with '
                   b'string ("a")\njq: error (at /d/rows.jsonl:2): Cannot '
                   b'index number with string ("a")\n')


@pytest.mark.asyncio
async def test_slurpfile_with_bad_json_is_refused_in_jqs_words():
    with pytest.raises(UsageError) as caught:
        await _run([],
                   "$x",
                   null_input=True,
                   slurpfile=["x", _path("/d/bad.json")])
    assert str(caught.value) == (
        "jq: Bad JSON in --slurpfile x /d/bad.json: Unfinished JSON term at "
        "EOF at line 3, column 1")
    assert caught.value.exit_code == 2


def test_argjson_reads_its_value_as_jqs_parser_does():
    assert named_args(_spec_flags(argjson=["v", "{\"a\":1}"])) == {
        "v": {
            "a": 1
        }
    }
    assert named_args(_spec_flags(argjson=["v", "nan"]))["v"] != 0
    with pytest.raises(UsageError):
        named_args(_spec_flags(argjson=["v", "1 2"]))

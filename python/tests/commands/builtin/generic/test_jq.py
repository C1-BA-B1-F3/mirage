import pytest

from mirage.commands.builtin.generic.jq import (assemble_inputs, exit_code, jq,
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
}


async def _read_bytes(path: PathSpec) -> bytes:
    return FILES[path.virtual]


def _unused_read_stream(_path):
    raise AssertionError("the streaming path must not serve a .json operand")


def _path(virtual: str) -> PathSpec:
    return PathSpec(virtual, virtual.rsplit("/", 1)[0], virtual.lstrip("/"))


def _spec_flags(**flags: object) -> FlagView:
    return FlagView(flags, spec=SPECS["jq"])


def _sources(*texts: bytes) -> list[tuple[str, bytes]]:
    return [(f"f{i}.json", text) for i, text in enumerate(texts)]


def _docs(opts: JqOptions, *texts: bytes) -> list:
    return assemble_inputs(_sources(*texts), opts)[0]


def _printed(*outputs: object) -> int:
    return run_status(JqRun(list(outputs)))


async def _run(paths: list[str], *texts: str, **flags: object) -> tuple:
    source, io = await jq([_path(p) for p in paths],
                          *texts,
                          read_bytes=_read_bytes,
                          read_stream=_unused_read_stream,
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


def test_slurp_spans_every_input_rather_than_each_one():
    assert _docs(JqOptions(slurp=True), b'{"a":1}', b'{"b":2}') == [[{
        "a": 1
    }, {
        "b": 2
    }]]


def test_raw_input_splits_lines_per_input():
    assert _docs(JqOptions(raw_input=True), b"x\ny", b"z\n") == ["x", "y", "z"]


def test_raw_slurp_joins_every_input_into_one_string():
    opts = JqOptions(raw_input=True, slurp=True)
    assert _docs(opts, b"x\n", b"y\n") == ["x\ny\n"]


def test_each_document_is_placed_where_jq_reads_it_whole():
    _, positions = assemble_inputs(_sources(b"1\n2\n", b"[3,\n4]\n5"),
                                   JqOptions())
    assert [positions.at(doc) for doc in range(4)
            ] == ["f0.json:1", "f0.json:2", "f1.json:2", "f1.json:2"]
    assert positions.end() == "f1.json:2"


def test_a_slurp_is_placed_at_the_end_of_the_last_input():
    _, positions = assemble_inputs(_sources(b"1\n", b"2\n3"),
                                   JqOptions(slurp=True))
    assert positions.at(0) == "f1.json:1"


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
    status = run_status(JqRun([False], JqHalt("", code)))
    assert exit_code([status], JqOptions(exit_status=exit_status)) == expected


def test_a_run_is_placed_where_the_reader_stops_for_it():
    _, positions = assemble_inputs(_sources(b"1\n2\n3\n"), JqOptions())
    none = StreamReads(input=False, inputs=False)
    one = StreamReads(input=True, inputs=False)
    rest = StreamReads(input=False, inputs=True)
    assert run_position(positions, none, 1, 0) == "f0.json:2"
    assert run_position(positions, none, None, 0) == "<unknown>"
    assert run_position(positions, one, 0, 1) == "f0.json:2"
    assert run_position(positions, one, 2, 0) == "f0.json:3"
    assert run_position(positions, rest, 0, 2) == "f0.json:3"


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


def test_stream_expands_documents_into_events():
    assert _docs(JqOptions(stream=True), b'{"a":1}') == [[["a"], 1], [["a"]]]


def test_stream_and_slurp_collect_the_events():
    opts = JqOptions(stream=True, slurp=True)
    assert _docs(opts, b'{"a":1}') == [[[["a"], 1], [["a"]]]]


def test_seq_reads_only_rs_introduced_values():
    assert _docs(JqOptions(seq=True), b'\x1e{"a":1}\n\x1e{"a":2}\n') == [{
        "a": 1
    }, {
        "a": 2
    }]


def test_seq_drops_text_before_the_first_separator():
    assert _docs(JqOptions(seq=True), b'{"a":1}\n') == []


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
async def test_a_program_that_does_not_compile_is_refused_before_any_read():
    out, err, code = await _ran("/d/missing.json", "1 +")
    assert (out, code) == (b"", 3)
    assert err.startswith(b"jq: error: syntax error, ")
    assert err.endswith(b"jq: 1 compile error\n")

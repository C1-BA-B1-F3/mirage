import asyncio

import pytest

from mirage.commands.builtin.generic.jq import (exit_code, indent_width,
                                                input_name, jq, jq_generic,
                                                option_refusal, parse_flags,
                                                positional_value, read_options,
                                                run_status)
from mirage.commands.config import CommandOpts, help_page, version_line
from mirage.commands.errors import UsageError
from mirage.commands.spec import SPECS, parse_command, parse_to_kwargs
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.core.jq import JqError, JqHalt, JqOptions, JqRun
from mirage.io.stream import yield_bytes
from mirage.io.types import IOResult, materialize
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
    "/d/nul.jq": b".\0x",
    "/d/-": b"42\n",
}

DIRS = {"/d/dir"}

HINT = ("Use jq --help for help with command-line options,\n"
        "or see the jq manpage, or online docs at https://jqlang.org")


def _stored(path: PathSpec) -> bytes:
    if path.virtual in DIRS:
        raise IsADirectoryError(path.virtual)
    if path.virtual not in FILES:
        raise FileNotFoundError(path.virtual)
    return FILES[path.virtual]


async def _read_bytes(path: PathSpec) -> bytes:
    return _stored(path)


async def _read_stream(path: PathSpec):
    data = _stored(path)
    for at in range(0, len(data), 5):
        yield data[at:at + 5]


def _path(virtual: str) -> PathSpec:
    return PathSpec(virtual, virtual.rsplit("/", 1)[0], virtual.lstrip("/"))


def _spec_flags(**flags: FlagValue) -> FlagView:
    return FlagView(flags, spec=SPECS["jq"])


def _parsed_line(*words: str) -> tuple[dict, list[str]]:
    parsed = parse_command(SPECS["jq"], list(words), "/", "jq")
    bag = parse_to_kwargs(parsed)
    for dest in ("rawfile", "slurpfile"):
        pairs = bag.get(dest)
        if isinstance(pairs, list):
            bag[dest] = [
                _path(str(word)) if at % 2 else word
                for at, word in enumerate(pairs)
            ]
    return bag, parsed.texts()


async def _unread(path: PathSpec) -> bytes:
    raise AssertionError(f"{path.virtual} should not be read")


async def _walk(*words: str) -> JqOptions | bytes:
    bag, texts = _parsed_line(*words)
    return await read_options(FlagView(bag, spec=SPECS["jq"]), texts,
                              "from_file" in bag, _read_bytes)


async def _options(*words: str) -> JqOptions:
    opts = await _walk(*words)
    assert isinstance(opts, JqOptions)
    return opts


async def _bound(**flags: FlagValue) -> dict[str, str]:
    opts = await read_options(_spec_flags(**flags), [], False, _unread)
    assert isinstance(opts, JqOptions)
    return dict(opts.named_args)


def _printed(*outputs: str) -> int:
    return run_status(JqRun(list(outputs)))


async def _run(paths: list[str], *texts: str, **flags: FlagValue) -> tuple:
    source, io = await jq([_path(p) for p in paths],
                          *texts,
                          read_bytes=_read_bytes,
                          read_stream=_read_stream,
                          **flags)
    return await materialize(source) if source is not None else b"", io


def test_join_and_nul_output_imply_raw():
    assert parse_flags(_spec_flags(join_output=True)).raw_output
    assert parse_flags(_spec_flags(raw_output0=True)).raw_output


@pytest.mark.asyncio
async def test_indent_minus_one_is_tab_indentation():
    opts = await read_options(_spec_flags(indent="-1"), [], False, _unread)
    assert opts.tab
    assert opts.indent == 2


@pytest.mark.parametrize("word, width", [("3", 3), ("+3", 3), ("07", 7),
                                         ("-0", 0), ("0", 0), ("-1", -1)])
def test_indent_reads_its_word_as_jqs_strtol_does(word, width):
    assert indent_width(word) == width


@pytest.mark.parametrize("word", [
    "x", "2x", "", " 3", "3 ", "3\n", "1.5", "0x3", "08", "-2",
    "99999999999999999999"
])
def test_indent_refuses_any_other_word_in_jqs_words(word):
    with pytest.raises(UsageError) as caught:
        indent_width(word)
    assert str(caught.value) == (
        f"jq: --indent takes a number between -1 and 7\n{HINT}")
    assert caught.value.exit_code == 2


@pytest.mark.parametrize("sign, digit, width", [("", "7", 7), ("+", "3", 3),
                                                ("-", "1", -1), ("-", "0", 0),
                                                ("", "0", 0)])
def test_indent_accepts_arbitrary_leading_zeroes(sign, digit, width):
    assert indent_width(sign + "0" * 5000 + digit) == width


@pytest.mark.parametrize("sign, digits", [("", "9"), ("-", "9"), ("+", "9"),
                                          ("", "0")])
def test_oversized_indent_stays_a_usage_error(sign, digits):
    with pytest.raises(UsageError) as caught:
        indent_width(sign + digits * 5000 + "8")
    assert str(caught.value) == (
        f"jq: --indent takes a number between -1 and 7\n{HINT}")
    assert caught.value.exit_code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("words, layout", [
    (["-c", "--tab"], "tab"),
    (["--tab", "-c"], "compact"),
    (["--indent", "3", "-c"], "compact"),
    (["-c", "--indent", "3"], 3),
    (["--tab", "--indent", "3"], 3),
    (["--indent", "3", "--tab"], "tab"),
    (["--indent", "-1", "-c"], "compact"),
    (["-c", "--indent", "-1"], "tab"),
    (["-cr", "--tab"], "tab"),
    (["--tab", "-rc"], "compact"),
    (["--indent", "2", "--indent", "5"], 5),
])
async def test_the_last_layout_option_typed_wins(words, layout):
    opts = await _options(*words, ".")
    assert ("compact"
            if opts.compact else "tab" if opts.tab else opts.indent) == layout


@pytest.mark.asyncio
async def test_a_later_indent_word_is_read_too():
    with pytest.raises(UsageError, match="--indent takes a number"):
        await _options("--indent", "2", "--indent", "x", ".")


@pytest.mark.asyncio
async def test_arg_binds_each_name_to_a_string():
    args = await _bound(arg=["a", "1", "b", 'x"y'])
    assert args == {"a": '"1"', "b": '"x\\"y"'}


@pytest.mark.asyncio
async def test_argjson_keeps_its_value_as_the_text_jq_reads():
    args = await _bound(argjson=["v", ' {"b":1.000,"1":2} '])
    assert args == {"v": '{"b":1.000,"1":2}'}


@pytest.mark.asyncio
async def test_argjson_rejects_invalid_json():
    with pytest.raises(UsageError, match="invalid JSON text"):
        await _bound(argjson=["v", "nope"])


@pytest.mark.asyncio
async def test_bindings_keep_the_order_they_were_typed_in():
    opts = await _options("-n", "--slurpfile", "s", "/d/four.json", "--arg",
                          "a", "1", "--rawfile", "r", "/d/one.json",
                          "--argjson", "b", "2", "$ARGS.named")
    assert list(opts.named_args.items()) == [("s", "[1,2,3,4]"), ("a", '"1"'),
                                             ("r", '"1"'), ("b", "2")]


@pytest.mark.asyncio
@pytest.mark.parametrize("words, text", [
    (["--argjson", "v", "1", "--argjson", "v", "2"], "1"),
    (["--arg", "v", "1", "--argjson", "v", "2"], '"1"'),
    (["--rawfile", "v", "/d/one.json", "--arg", "v", "2"], '"1"'),
    (["--slurpfile", "v", "/d/two.json", "--rawfile", "v", "/d/one.json"
      ], "[2]"),
])
async def test_the_first_binding_of_a_name_wins(words, text):
    opts = await _options("-n", *words, "$v")
    assert opts.named_args == {"v": text}


@pytest.mark.asyncio
@pytest.mark.parametrize("words", [
    ["--argjson", "v", "nope"],
    ["--rawfile", "v", "/d/missing.txt"],
    ["--slurpfile", "v", "/d/bad.json"],
])
async def test_a_binding_of_a_taken_name_is_never_read(words):
    bag, texts = _parsed_line("-n", "--arg", "v", "1", *words, "$v")
    opts = await read_options(FlagView(bag, spec=SPECS["jq"]), texts, False,
                              _unread)
    assert opts.named_args == {"v": '"1"'}


@pytest.mark.asyncio
@pytest.mark.parametrize("words, refusal", [
    (["--indent", "x", "--argjson", "a", "nope"], "jq: --indent takes"),
    (["--argjson", "a", "nope", "--indent", "x"], "jq: invalid JSON text"),
    (["--argjson", "a", "nope", "--slurpfile", "b", "/d/missing.json"
      ], "jq: invalid JSON text"),
    (["--slurpfile", "b", "/d/missing.json", "--argjson", "a", "nope"
      ], "jq: Bad JSON in --slurpfile b /d/missing.json"),
])
async def test_the_first_option_jq_refuses_is_the_one_reported(words, refusal):
    with pytest.raises(UsageError) as caught:
        await _options("-n", *words, "1")
    assert str(caught.value).startswith(refusal)


@pytest.mark.asyncio
async def test_the_generic_entry_reads_the_flags_in_the_order_typed():
    bag, _ = _parsed_line("-n", "--tab", "-c", "--argjson", "b", "1", "--arg",
                          "a", "2", "--arg", "b", "3", "$ARGS.named")
    source, io = await jq_generic([], ["$ARGS.named"], CommandOpts(flags=bag),
                                  _read_bytes, _read_stream)
    assert source is not None
    assert await materialize(source) == b'{"b":1,"a":"2"}\n'
    assert io.exit_code == 0


def test_exit_status_reads_the_last_output_only():
    opts = JqOptions(exit_status=True)
    assert exit_code([_printed("1", "false")], opts) == 1
    assert exit_code([_printed("false", "1")], opts) == 0
    assert exit_code([_printed("null")], opts) == 1
    assert exit_code([_printed('"false"'), _printed("0.0")], opts) == 0
    assert exit_code([], opts) == 4


def test_exit_status_is_zero_without_the_flag():
    assert exit_code([], JqOptions()) == 0
    assert exit_code([_printed("null")], JqOptions()) == 0


def test_a_failed_run_counts_only_when_it_is_the_last_one():
    failed = run_status(JqRun(["1"], JqError("x", True)))
    assert exit_code([failed, _printed("1")], JqOptions()) == 0
    assert exit_code([_printed("1"), failed], JqOptions()) == 5
    assert exit_code([failed, _printed("false")],
                     JqOptions(exit_status=True)) == 1


def test_exit_status_looks_back_past_runs_that_printed_nothing():
    opts = JqOptions(exit_status=True)
    assert exit_code([_printed("false"), _printed()], opts) == 1
    assert exit_code([_printed("1"), _printed()], opts) == 0


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


def test_args_reads_an_operand_as_a_string():
    assert positional_value("args", "1") == '"1"'


def test_jsonargs_keeps_each_operand_as_the_text_jq_reads():
    assert positional_value("jsonargs", "1.0") == "1.0"
    assert positional_value("jsonargs", '{"b":1,"1":2}') == '{"b":1,"1":2}'


def test_jsonargs_rejects_invalid_json_in_jqs_words():
    with pytest.raises(UsageError) as caught:
        positional_value("jsonargs", "nope")
    assert str(caught.value) == (
        f"jq: invalid JSON text passed to --jsonargs\n{HINT}")
    assert caught.value.exit_code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("words, positional", [
    (["--args", "a", "--jsonargs", "1", "--args", "b"], ('"a"', "1", '"b"')),
    (["--jsonargs", "1", "--args", "a"], ("1", '"a"')),
    (["--args", "--jsonargs", "1"], ("1", )),
    (["--args", "{", "--jsonargs", "1"], ('"{"', "1")),
    (["/d/a.json", "--args", "x", "/d/b.json"], ('"x"', '"/d/b.json"')),
    (["--jsonargs", "1", "--arg", "x", "y", "2"], ("1", "2")),
    (["--args", "--", "-x", "--jsonargs"], ('"-x"', '"--jsonargs"')),
    (["/d/a.json"], ()),
])
async def test_each_operand_takes_the_mode_typed_last_before_it(
        words, positional):
    opts = await _options("-n", ".", *words)
    assert opts.positional_args == positional


@pytest.mark.asyncio
async def test_the_program_comes_first_whatever_the_mode():
    opts = await _options("-n", "--jsonargs", ".", "1", "--args", "2",
                          "--jsonargs", "3")
    assert opts.positional_args == ("1", '"2"', "3")


@pytest.mark.asyncio
async def test_a_from_file_program_leaves_every_operand_to_the_modes():
    opts = await _options("-n", "-f", "/d/prog.jq", "/d/a.json", "--args", "b",
                          "--jsonargs", "2")
    assert opts.positional_args == ('"b"', "2")


@pytest.mark.asyncio
@pytest.mark.parametrize("words, refusal", [
    (["--jsonargs", "nope", "--indent", "x"
      ], "jq: invalid JSON text passed to --jsonargs"),
    (["--indent", "x", "--jsonargs", "nope"], "jq: --indent takes"),
    (["--jsonargs", "nope", "--argjson", "a", "nope"
      ], "jq: invalid JSON text passed to --jsonargs"),
    (["--argjson", "a", "nope", "--jsonargs", "nope"
      ], "jq: invalid JSON text passed to --argjson"),
    (["--jsonargs", "nope", "--slurpfile", "b", "/d/missing.json"
      ], "jq: invalid JSON text passed to --jsonargs"),
    (["--slurpfile", "b", "/d/missing.json", "--jsonargs", "nope"
      ], "jq: Bad JSON in --slurpfile b /d/missing.json"),
])
async def test_a_jsonargs_operand_is_refused_where_it_was_typed(
        words, refusal):
    with pytest.raises(UsageError) as caught:
        await _options("-n", ".", *words)
    assert str(caught.value).startswith(refusal)


@pytest.mark.asyncio
@pytest.mark.parametrize("flags, has_program_file, texts, positional", [
    ({
        "args": True
    }, False, [".", "a", "1"], ('"a"', '"1"')),
    ({
        "args": True
    }, True, ["a", "b"], ('"a"', '"b"')),
    ({
        "args": True,
        "jsonargs": True
    }, False, [".", "1"], ("1", )),
    ({
        "jsonargs": True,
        "args": True
    }, False, [".", "1"], ('"1"', )),
    ({}, False, [".", "a"], ()),
])
async def test_keyword_operands_come_after_every_option(
        flags, has_program_file, texts, positional):
    opts = await read_options(_spec_flags(**flags), texts, has_program_file,
                              _unread)
    assert opts.positional_args == positional


@pytest.mark.asyncio
async def test_an_input_file_typed_before_args_is_still_read():
    parsed = parse_command(SPECS["jq"], [
        "-c", "[., $ARGS.positional]", "/d/one.json", "--args", "/d/two.json"
    ], "/", "jq")
    source, io = await jq_generic([_path(p) for p in parsed.paths()],
                                  parsed.texts(),
                                  CommandOpts(flags=parse_to_kwargs(parsed)),
                                  _read_bytes, _read_stream)
    assert source is not None
    assert await materialize(source) == b'[1,["/d/two.json"]]\n'
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_dash_words_reach_jq_as_the_program_and_its_values():
    parsed = parse_command(SPECS["jq"], [
        "-n", "-c", "-$ARGS.positional[0], $ARGS.positional", "--jsonargs",
        "-1", "--args", "-."
    ], "/", "jq")
    source, io = await jq_generic([], parsed.texts(),
                                  CommandOpts(flags=parse_to_kwargs(parsed)),
                                  _read_bytes, _read_stream)
    assert source is not None
    assert await materialize(source) == b'1\n[-1,"-."]\n'
    assert io.exit_code == 0


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
                   **flags: FlagValue) -> tuple[bytes, bytes, int]:
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
async def test_a_parse_error_closes_the_input_it_stopped_in():
    opened = []

    def tracked(path: PathSpec):
        stream = _read_stream(path)
        opened.append(stream)
        return stream

    source, io = await jq(
        [_path("/d/mid.json"), _path("/d/a.json")],
        ".",
        read_bytes=_read_bytes,
        read_stream=tracked)
    assert await materialize(source) == b"1\n"
    assert io.exit_code == 5
    assert opened[0].ag_frame is None


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
async def test_a_run_is_placed_where_its_reads_leave_the_reader():
    # A run reports where the reader stands once it has read its own
    # document and whatever `input` or `inputs` took past it.
    assert await _flagged(["/d/four.json"], "[., input] | error(tojson)") == (
        b"", b"jq: error (at /d/four.json:2): [1,2]\n"
        b"jq: error (at /d/four.json:4): [3,4]\n", 5)
    assert await _flagged(["/d/four.json"], "[., inputs] | error(tojson)") == (
        b"", b"jq: error (at /d/four.json:4): [1,2,3,4]\n", 5)


def _live(data: bytes):
    # An input that holds `data` and never ends, like a producer that
    # stays open.

    async def read_stream(path: PathSpec):
        yield data
        await asyncio.Event().wait()

    return read_stream


@pytest.mark.asyncio
async def test_a_run_reads_no_further_than_its_input_takes():
    source, io = await jq([_path("/d/live.json")],
                          "input",
                          read_bytes=_read_bytes,
                          read_stream=_live(b"[1 2]\n"),
                          null_input=True)
    assert await asyncio.wait_for(materialize(source), 5) == b""
    assert (await materialize(io.stderr), io.exit_code) == (
        b"jq: error (at /d/live.json:1): Expected separator between values "
        b"at line 1, column 5\n", 5)
    source, io = await jq([_path("/d/live.json")],
                          "[., input]",
                          read_bytes=_read_bytes,
                          read_stream=_live(b"1\n2\n"),
                          compact_output=True)
    assert await asyncio.wait_for(anext(source), 5) == b"[1,2]\n"
    await source.aclose()


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


MISSING = (b"jq: error: Could not open file /d/nope.json: No such file or "
           b"directory\n")


@pytest.mark.asyncio
async def test_an_input_that_cannot_be_opened_is_reported_and_read_past():
    # jq reports the file, reads on, and its main loop stops after the
    # document the reader went on to (pinned: `jq . missing.json a.json`
    # prints a.json's first document only).
    assert await _flagged(["/d/nope.json", "/d/four.json"],
                          ".") == (b"1\n", MISSING, 2)
    assert await _flagged(["/d/four.json", "/d/nope.json", "/d/multi.json"],
                          ".",
                          compact_output=True) == (b'1\n2\n3\n4\n{"a":1}\n',
                                                   MISSING, 2)


@pytest.mark.asyncio
async def test_a_failed_input_exits_two_whatever_the_runs_answered():
    assert await _flagged(["/d/nope.json", "/d/four.json"],
                          ". == 0",
                          exit_status=True) == (b"false\n", MISSING, 2)
    assert await _flagged(["/d/nope.json", "/d/four.json"],
                          "halt_error") == (b"", MISSING + b"1\n", 2)


@pytest.mark.asyncio
async def test_a_directory_input_is_reported_in_jqs_bare_words():
    assert await _flagged(["/d/dir", "/d/four.json"],
                          ".") == (b"1\n", b"jq: error: Is a directory\n", 2)


@pytest.mark.asyncio
async def test_input_reads_past_a_failed_input_to_the_next():
    # One that finds nothing more fails where the reader stopped, on the
    # failed file at line 0 (pinned).
    assert await _flagged(["/d/nope.json", "/d/four.json"],
                          "input",
                          null_input=True) == (b"1\n", MISSING, 2)
    assert await _flagged(
        ["/d/nope.json"], "input",
        null_input=True) == (b"", MISSING +
                             b"jq: error (at /d/nope.json:0): break\n", 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["rawfile", "slurpfile"])
@pytest.mark.parametrize("path, reason",
                         [("/d/nope.json", "No such file or directory"),
                          ("/d/dir", "It's a directory")])
async def test_a_flag_file_that_cannot_be_read_is_refused_in_jqs_words(
        option, path, reason):
    with pytest.raises(UsageError) as caught:
        await _run([], "$x", null_input=True, **{option: ["x", _path(path)]})
    assert str(caught.value) == (f"jq: Bad JSON in --{option} x {path}: "
                                 f"Could not open {path}: {reason}")
    assert caught.value.exit_code == 2


@pytest.mark.asyncio
async def test_a_usage_error_ends_with_jq_1_8s_hint():
    with pytest.raises(UsageError) as caught:
        await _bound(argjson=["v", "1 2"])
    assert str(
        caught.value) == (f"jq: invalid JSON text passed to --argjson\n{HINT}")


@pytest.mark.parametrize("word, line", [
    ("-x", "Unknown option -x"),
    ("--indent=3", "Unknown option --indent=3"),
    ("--arg", "--arg takes two parameters (e.g. --arg varname value)"),
    ("--slurpfile",
     "--slurpfile takes two parameters (e.g. --slurpfile varname filename)"),
    ("--indent", "--indent takes one parameter"),
])
def test_a_refused_option_is_worded_as_jq_words_it(word, line):
    assert str(option_refusal(word)) == f"jq: {line}\n{HINT}"


def test_an_f_the_line_ends_at_prints_jqs_short_usage():
    refusal = option_refusal("-f")
    assert str(refusal).startswith(
        "jq - commandline JSON processor [version 1.8.2]\n")
    assert str(refusal).endswith(
        "For listing the command options, use jq --help.")
    assert refusal.exit_code == 2


# jq 1.8.2's loop stops at the first word it cannot take, so an option the
# parser refused waits its turn behind a bad value typed before it.
@pytest.mark.asyncio
@pytest.mark.parametrize("words, first", [
    ((".", "--jsonargs", "{", "--bogus"),
     "invalid JSON text passed to --jsonargs"),
    ((".", "--bogus", "--jsonargs", "{"), "Unknown option --bogus"),
    ((".", "--indent", "9", "--bogus"),
     "--indent takes a number between -1 and 7"),
    ((".", "--bogus", "--indent", "9"), "Unknown option --bogus"),
    ((".", "--argjson", "x", "{", "-Z"),
     "invalid JSON text passed to --argjson"),
])
async def test_the_first_refusal_typed_is_the_one_reported(words, first):
    with pytest.raises(UsageError) as caught:
        await _walk("-n", *words)
    assert str(caught.value) == f"jq: {first}\n{HINT}"


@pytest.mark.asyncio
async def test_help_and_version_answer_where_the_loop_reaches_them():
    assert await _walk("--help", "--bogus") == help_page("jq", SPECS["jq"])
    assert await _walk("-hx") == help_page("jq", SPECS["jq"])
    assert await _walk("-n", ".", "-V", "--jsonargs",
                       "{") == version_line("jq")
    for words in (("--bogus", "--help"), ("-n", ".", "--jsonargs", "{", "-V")):
        with pytest.raises(UsageError):
            await _walk(*words)


@pytest.mark.asyncio
@pytest.mark.parametrize("option, expected", [
    ("from_file", b"42\n"),
    ("rawfile", b'"42\\n"\n'),
    ("slurpfile", b"[42]\n"),
])
async def test_dash_flag_file_reads_the_backend_without_a_dispatcher(
        option, expected):
    path = PathSpec("/d/-", "/d", "-", raw_path="-")
    value = path if option == "from_file" else ["x", path]
    source, io = await jq([],
                          "$x",
                          read_bytes=_read_bytes,
                          read_stream=_read_stream,
                          stdin=b"99\n",
                          null_input=True,
                          compact_output=True,
                          **{option: value})
    assert await materialize(source) == expected
    assert io.exit_code == 0
    assert await materialize(io.stderr) == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["from_file", "rawfile", "slurpfile"])
@pytest.mark.parametrize("operand", [None, "-", "/dev/stdin"])
@pytest.mark.parametrize("streamed", [False, True])
async def test_stdin_consumed_by_a_flag_file_is_not_replayed_as_input(
        option, operand, streamed):
    path = _path("/dev/stdin")
    value = path if option == "from_file" else ["x", path]
    paths = [] if operand is None else [
        PathSpec("/dev/stdin", "/dev", "stdin", raw_path=operand)
    ]
    source, io = await jq(paths,
                          ".",
                          read_bytes=_read_bytes,
                          read_stream=_read_stream,
                          stdin=yield_bytes(b"99\n") if streamed else b"99\n",
                          **{option: value})
    assert await materialize(source) == b""
    assert io.exit_code == 0
    assert await materialize(io.stderr) == b""


async def _run_program_file(*words: str) -> tuple[bytes, IOResult]:
    parsed = parse_command(SPECS["jq"], list(words), "/", "jq")
    bag = parse_to_kwargs(parsed)
    bag["from_file"] = _path(str(bag["from_file"]))
    source, io = await jq_generic([], parsed.texts(), CommandOpts(flags=bag),
                                  _read_bytes, _read_stream)
    return (await materialize(source) if source is not None else b""), io


@pytest.mark.asyncio
async def test_the_program_file_is_read_after_the_option_loop():
    with pytest.raises(UsageError, match="Unknown option --bogus"):
        await _run_program_file("-n", "-f", "/d/missing.jq", "--bogus")
    _, io = await _run_program_file("-n", "-f", "/d/missing.jq")
    assert io.exit_code == 2
    assert b"Could not open" in await materialize(io.stderr)


@pytest.mark.asyncio
async def test_a_program_file_holding_nul_is_refused():
    out, io = await _run_program_file("-n", "-f", "/d/nul.jq")
    assert out == b""
    assert io.exit_code == 2
    assert await materialize(io.stderr
                             ) == b"jq: program file contains NUL bytes\n"


@pytest.mark.asyncio
async def test_argjson_reads_its_value_as_jqs_parser_does():
    assert await _bound(argjson=["v", "{\"a\":1}"]) == {"v": '{"a":1}'}
    assert await _bound(argjson=["v", "nan"]) == {"v": "nan"}
    with pytest.raises(UsageError):
        await _bound(argjson=["v", "1 2"])

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

import pytest

from mirage.core.jq.errors import JqCompileError
from mirage.core.jq.eval import (halts, jq_check, jq_eval, jq_run,
                                 references_args, stream_reads)
from mirage.core.jq.types import JqError, JqHalt, JqRun, StreamReads


def test_single_output_is_a_one_element_list():
    assert jq_eval({"a": 1}, ".a") == [1]


def test_collector_program_evaluates_to_a_single_value():
    # `[.a[] | .t]` emits ONE array, so the caller prints one line.
    assert jq_eval({"a": [{
        "t": "x"
    }, {
        "t": "y"
    }]}, "[.a[] | .t]") == [["x", "y"]]


def test_spread_program_evaluates_to_one_output_per_element():
    assert jq_eval({"a": [1, 2, 3]}, ".a[]") == [1, 2, 3]


def test_comma_is_two_outputs_not_one_array():
    assert jq_eval({"a": 1, "b": 2}, ".a, .b") == [1, 2]


def test_comma_over_arrays_keeps_each_array_whole():
    assert jq_eval({"a": 1, "b": 2}, "[.a], [.b]") == [[1], [2]]


def test_multi_output_without_a_bracket_pair():
    # `range` and `..` spread with no `[]` anywhere in the program.
    assert jq_eval(None, "range(3)") == [0, 1, 2]
    assert jq_eval({"a": 1}, "..") == [{"a": 1}, 1]


def test_bracket_pair_inside_a_string_literal_is_one_output():
    assert jq_eval({"a": "x[]y"}, '.a | contains("[]")') == [True]


def test_zero_outputs_is_an_empty_list():
    assert jq_eval({"x": 1}, "select(.x > 100)") == []
    assert jq_eval({}, "empty") == []


def test_optional_spread_over_a_missing_field_is_empty():
    """Reproducer for the 'jq: DropItem' regression: an `[]?` over a
    missing field used to leak the internal sentinel exception."""
    msg = {"id": "x", "subject": "hi", "body_text": "..."}
    assert jq_eval(msg, ".attachments[]?") == []


def test_named_args_bind_to_dollar_names():
    assert jq_eval({"a": 1}, "[.a, $v]", {"v": "hi"}) == [[1, "hi"]]


def test_named_args_carry_json_values():
    assert jq_eval(None, "$v", {"v": {"k": [1, 2]}}) == [{"k": [1, 2]}]


def test_inputs_yields_the_bound_documents():
    assert jq_eval(None, "[inputs]", None, [1, 2, 3]) == [[1, 2, 3]]


def test_inputs_binding_is_absent_without_documents():
    assert jq_eval({"a": 1}, ".a") == [1]


def test_a_program_defining_inputs_shadows_the_binding():
    assert jq_eval(None, "def inputs: 9; [inputs]", None, [1, 2]) == [[9]]


def test_input_takes_the_first_unread_document():
    assert jq_eval(None, "input", None, [{"n": 1}, {"n": 2}]) == [{"n": 1}]


def test_inputs_starts_after_the_document_input_took():
    assert jq_eval(None, "input as $h | [$h, [inputs]]", None,
                   [1, 2, 3]) == [[1, [2, 3]]]
    assert jq_eval(None, "[input, inputs]", None, [1, 2, 3]) == [[1, 2, 3]]


def test_input_fails_with_break_once_nothing_is_left():
    with pytest.raises(ValueError, match="break"):
        jq_eval(None, "input", None, [])
    assert jq_eval(None, "try input catch .", None, []) == ["break"]


def test_bindings_carry_values_of_any_size():
    big = "x" * 2_000_000
    assert jq_eval(None, "$x | length", {"x": big}) == [2_000_000]
    docs = [{"k": "x" * 90}] * 20_480
    assert jq_eval(None, "[inputs] | length", None, docs) == [20_480]


def test_a_compile_error_names_the_line_the_program_wrote_it_on():
    with pytest.raises(ValueError, match="at <top-level>, line 1,"):
        jq_eval(None, "1 +", None, [])
    with pytest.raises(ValueError, match="at <top-level>, line 2,"):
        jq_eval(None, ".\n| 1 +", None, [], {"named": {}})


def test_a_trailing_comment_leaves_the_program_whole():
    assert jq_eval(None, "[inputs] # every document", None, [1]) == [[1]]


def test_an_empty_program_keeps_jqs_own_refusal():
    with pytest.raises(ValueError, match="Top-level program not given"):
        jq_eval(None, "# nothing", None, [1])


def test_stream_reads_finds_whole_words_only():
    assert stream_reads("[inputs]") == StreamReads(input=False, inputs=True)
    assert stream_reads("reduce inputs as $x (0; . + $x)").inputs
    assert stream_reads("input") == StreamReads(input=True, inputs=False)
    assert stream_reads("input as $h | [inputs]") == StreamReads(input=True,
                                                                 inputs=True)
    assert not stream_reads(".myinputs").inputs
    assert not stream_reads(".inputs_total").inputs
    assert not stream_reads("input_filename").input
    assert not stream_reads("input_line_number").input


@pytest.mark.parametrize("expr", [
    ".inputs", ".a.inputs", "$inputs", "{inputs: .a}", "{inputs}",
    "{a, inputs}", "m::inputs"
])
def test_stream_reads_ignores_inputs_spelling_data(expr: str):
    assert not stream_reads(expr).inputs


@pytest.mark.parametrize(
    "expr", [".input", "$input", "{input: 1}", "{input}", "m::input"])
def test_stream_reads_ignores_input_spelling_data(expr: str):
    assert not stream_reads(expr).input


def test_stream_reads_ignores_strings_and_comments():
    assert not stream_reads('"no inputs found"').inputs
    assert not stream_reads(". # drains inputs").inputs
    assert not stream_reads('"a\\("b" + "inputs")c"').inputs
    assert not stream_reads('"read the input"').input


def test_stream_reads_ignores_a_function_the_program_defines():
    assert not stream_reads("def input: 1; input").input
    assert not stream_reads("def inputs: 9; [inputs]").inputs
    assert stream_reads("def f(x): x; f(input)").input


def test_stream_reads_finds_calls_in_every_value_position():
    assert stream_reads("{a: inputs}").inputs
    assert stream_reads("{(inputs): 1}").inputs
    assert stream_reads("[1, inputs, 2]").inputs
    assert stream_reads('"\\(inputs)"').inputs
    assert stream_reads("{a: input}").input


def test_references_args_ignores_strings_and_comments():
    assert references_args("$ARGS.positional")
    assert references_args("{$ARGS}")
    assert not references_args('"$ARGS"')
    assert not references_args(". # $ARGS")
    assert not references_args("$ARGSX")


@pytest.mark.parametrize("expr, run", [
    ('.a, error("boom"), .a', JqRun([1], JqError("boom", True))),
    ('error({"b": 2})', JqRun([], JqError('{"b":2}', False))),
    ("error(null)", JqRun([], JqError("null", False))),
    ('error("null")', JqRun([], JqError("null", True))),
    (".a | .b",
     JqRun([], JqError('Cannot index number with string ("b")', True))),
    ('"bye\\n" | halt_error', JqRun([], JqHalt("bye\n", True, 5))),
    ("[1] | halt_error(2)", JqRun([], JqHalt("[1]", False, 2))),
    ("null | halt_error", JqRun([], JqHalt(None, False, 5))),
    ('"a", halt', JqRun(["a"], JqHalt(None, False, None))),
    ("1, [halt_error(2)], 3", JqRun([1], JqHalt('{"a":1}', False, 2))),
    ("[.a] | map(halt_error(4))", JqRun([], JqHalt("1", False, 4))),
    ('{"__mirage_jq_error": [true, "x"]}',
     JqRun([{
         "__mirage_jq_error": [True, "x"]
     }])),
    ('try error("x") catch .', JqRun(["x"])),
])
def test_a_run_hands_back_what_stopped_it(expr, run):
    assert jq_run({"a": 1}, expr) == run


def test_halt_error_refuses_a_code_that_is_not_a_number_as_jq_does():
    assert jq_run(1, 'halt_error("x")') == JqRun(
        [], JqError("number (1) halt_error/1: number required", True))


def test_a_run_keeps_the_programs_own_line_numbers():
    assert jq_run(None, "$__loc__ | .line") == JqRun([1])
    assert jq_run(None, "$__loc__ | .line", inputs=[]) == JqRun([1])


def test_code_that_closes_the_prelude_early_is_refused_as_jq_refuses_it():
    with pytest.raises(JqCompileError, match="syntax error"):
        jq_run(1, "1) catch 2 | try (3")


def test_a_compile_error_reads_as_the_program_numbers_its_lines():
    with pytest.raises(JqCompileError, match="line 2, column"):
        jq_run(1, ".a |\n  nosuch(1)", args_value={"positional": []})


def test_a_program_is_checked_without_being_run():
    jq_check("repeat(1)")
    with pytest.raises(JqCompileError, match="1 compile error"):
        jq_check("1 +")


@pytest.mark.parametrize("expr, expected", [
    ("halt", True),
    ('"x" | halt_error(1)', True),
    (".halt", False),
    ('"halt"', False),
    ("$halt", False),
    ("def halting: 1; halting", False),
])
def test_halts_finds_a_call_to_either_halt(expr, expected):
    assert halts(expr) is expected

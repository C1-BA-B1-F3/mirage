from collections.abc import AsyncIterator

import pytest

from mirage.commands.builtin.generic.awk import awk
from mirage.commands.errors import UsageError
from mirage.types import PathSpec


def _spec(path: str) -> PathSpec:
    return PathSpec(
        vfs_path=(path).strip("/"), virtual=path, directory=path, resolved=True
    )


def _make_backend(files: dict[str, bytes]):

    async def read_bytes(path):
        key = path.virtual if isinstance(path, PathSpec) else path
        if key not in files:
            raise FileNotFoundError(key)
        return files[key]

    async def read_stream(path):
        assert isinstance(path, PathSpec)
        key = path.virtual
        if key not in files:
            raise FileNotFoundError(key)
        yield files[key]

    return read_bytes, read_stream


async def _drain(stdout) -> bytes:
    if stdout is None:
        return b""
    if isinstance(stdout, bytes):
        return stdout
    return b"".join([c async for c in stdout])


@pytest.mark.parametrize(
    "f, files, data, expected",
    [
        (
            _spec("/prog.awk"),
            {"/prog.awk": b"{print $1}\n", "/data.txt": b"alpha beta\n"},
            ["/data.txt"],
            "alpha\n",
        ),
        (
            _spec("/prog.awk"),
            {
                "/prog.awk": b"{print NR, $1}\n",
                "/a.txt": b"one\n",
                "/b.txt": b"two\n",
            },
            ["/a.txt", "/b.txt"],
            "1 one\n2 two\n",
        ),
        (
            [_spec("/p1.awk"), _spec("/p2.awk")],
            {
                "/p1.awk": b"{sum += $1}\n",
                "/p2.awk": b"END {print sum}\n",
                "/nums.txt": b"1\n2\n3\n",
            },
            ["/nums.txt"],
            "6\n",
        ),
    ],
)
@pytest.mark.asyncio
async def test_awk_runs_the_program_files(f, files, data, expected):
    rb, rs = _make_backend(files)
    output, io = await awk(
        [_spec(path) for path in data],
        (),
        {"f": f},
        read_bytes=rb,
        read_stream=rs,
    )
    assert (await _drain(output)).decode() == expected
    assert io.cache == data


@pytest.mark.asyncio
async def test_awk_default_fs_collapses_whitespace():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ("{print $2}",),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"a   b\n\tx\t \ty\n",
    )
    assert (await _drain(output)).decode() == "b\ny\n"


@pytest.mark.asyncio
async def test_awk_explicit_single_space_fs_collapses_whitespace():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ("{print $2}",),
        {"F": " "},
        read_bytes=rb,
        read_stream=rs,
        stdin=b"a   b\n",
    )
    assert (await _drain(output)).decode() == "b\n"


@pytest.mark.asyncio
async def test_awk_empty_fs_splits_characters():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ("{print $2}",),
        {"F": ""},
        read_bytes=rb,
        read_stream=rs,
        stdin=b"abc\n",
    )
    assert (await _drain(output)).decode() == "b\n"


@pytest.mark.asyncio
async def test_awk_processes_all_files_with_continuous_nr():
    rb, rs = _make_backend(
        {
            "/a.txt": b"one\ntwo\n",
            "/b.txt": b"three\n",
        }
    )
    output, io = await awk(
        [_spec("/a.txt"), _spec("/b.txt")],
        ("{print NR, $1}",),
        None,
        read_bytes=rb,
        read_stream=rs,
    )
    assert (await _drain(output)).decode() == "1 one\n2 two\n3 three\n"
    assert io.cache == ["/a.txt", "/b.txt"]


@pytest.mark.asyncio
async def test_awk_multifile_no_trailing_newline_keeps_lines_separate():
    rb, rs = _make_backend(
        {
            "/a.txt": b"one",
            "/b.txt": b"two\n",
        }
    )
    output, _ = await awk(
        [_spec("/a.txt"), _spec("/b.txt")],
        ("{print NR, $1}",),
        None,
        read_bytes=rb,
        read_stream=rs,
    )
    assert (await _drain(output)).decode() == "1 one\n2 two\n"


@pytest.mark.asyncio
async def test_awk_print_empty_string_emits_blank_line():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ('{print ""}',),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"one\ntwo\n",
    )
    assert (await _drain(output)).decode() == "\n\n"


@pytest.mark.asyncio
async def test_awk_brace_literal_in_print():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ('{print "}"}',),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"line\n",
    )
    assert (await _drain(output)).decode() == "}\n"


@pytest.mark.asyncio
async def test_awk_program_file_missing_raises_usage_error():
    rb, rs = _make_backend({"/data.txt": b"x\n"})
    with pytest.raises(UsageError, match="No such file"):
        await awk(
            [_spec("/data.txt")],
            (),
            {"f": _spec("/missing.awk")},
            read_bytes=rb,
            read_stream=rs,
        )


@pytest.mark.asyncio
async def test_awk_duplicate_v_last_wins():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ("{print x}",),
        {"v": ["x=first", "x=second"]},
        read_bytes=rb,
        read_stream=rs,
        stdin=b"line\n",
    )
    assert (await _drain(output)).decode() == "second\n"


@pytest.mark.asyncio
async def test_awk_begin_bare_print_emits_blank_line():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ("BEGIN {print} {print $1}",),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"a\n",
    )
    assert (await _drain(output)).decode() == "\na\n"


@pytest.mark.asyncio
async def test_awk_brace_literal_with_condition():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ('/x/ {print "}"}',),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"x\ny\n",
    )
    assert (await _drain(output)).decode() == "}\n"


@pytest.mark.asyncio
async def test_awk_assignment_from_field():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ("{x = $2; print x}",),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"a b\n",
    )
    assert (await _drain(output)).decode() == "b\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "program, expected",
    [
        ("{{print $1}}", "Welcome\nInstall\n"),
        ("{{{print $1}}}", "Welcome\nInstall\n"),
        ("{{print $1}; print $2}", "Welcome\nto\nInstall\nit\n"),
        ("{print $1;{print $2}}", "Welcome\nto\nInstall\nit\n"),
    ],
)
async def test_awk_compound_statement_runs_its_body(program, expected):
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        (program,),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"Welcome to x\nInstall it\n",
    )
    assert (await _drain(output)).decode() == expected


@pytest.mark.asyncio
async def test_awk_semicolon_inside_string_is_not_a_separator():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ('{print "a;b", $1}',),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"x\n",
    )
    assert (await _drain(output)).decode() == "a;b x\n"


async def _run_stdin(program: str, stdin: bytes, flags=None) -> str:
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        (program,),
        flags,
        read_bytes=rb,
        read_stream=rs,
        stdin=stdin,
    )
    return (await _drain(output)).decode()


@pytest.mark.asyncio
async def test_awk_bare_regex_pattern_holding_an_operator_matches():
    out = await _run_stdin("/A&&B/", b"xA&&By\nAB\n")
    assert out == "xA&&By\n"


@pytest.mark.asyncio
async def test_awk_tilde_numeric_rhs_matches_as_text():
    out = await _run_stdin("$1 ~ 1", b"12\n3\n")
    assert out == "12\n"


@pytest.mark.asyncio
async def test_awk_tilde_lhs_may_be_nf_field_or_builtin():
    assert (
        await _run_stdin("$NF ~ /^App/", b"x y Application\nx y Other\n")
        == "x y Application\n"
    )
    assert await _run_stdin("NR ~ /[13]/", b"a\nb\nc\n") == "a\nc\n"


@pytest.mark.asyncio
async def test_awk_tilde_regex_may_contain_a_comparison_operator():
    assert await _run_stdin("$0 ~ /a<b/", b"a<b\nab\n") == "a<b\n"
    assert await _run_stdin("$0 ~ /a==b/", b"a==b\nab\n") == "a==b\n"


@pytest.mark.asyncio
async def test_awk_bare_regex_may_contain_a_comparison_operator():
    assert await _run_stdin("/a<b/", b"a<b\nab\n") == "a<b\n"


@pytest.mark.asyncio
async def test_awk_tilde_regex_with_escaped_slash():
    assert await _run_stdin(r"$1 ~ /a\/b/", b"a/b\nab\n") == "a/b\n"


@pytest.mark.asyncio
async def test_awk_regex_brace_is_not_the_action_brace():
    assert await _run_stdin("$1 ~ /a{2}/ {print $2}", b"aa 1\na 2\n") == "1\n"


@pytest.mark.asyncio
async def test_awk_tilde_without_surrounding_spaces():
    assert await _run_stdin("$1~/a/", b"a b\nc d\n") == "a b\n"


@pytest.mark.asyncio
async def test_awk_negated_operand_tests_falsiness():
    assert await _run_stdin("!$1", b"0\n1\nfoo\n\n") == "0\n\n"
    assert await _run_stdin("!x", b"a\nb\n", {"v": "x=0"}) == "a\nb\n"


@pytest.mark.parametrize(
    "texts, match",
    [
        ((), "usage"),
        (
            ("$1 ~ /(a/ {print}",),
            r"awk: syntax error in regular expression \(a at source line 1",
        ),
        (("/(a/",), "syntax error in regular expression"),
        (("{print $(}",), "syntax error"),
    ],
)
@pytest.mark.asyncio
async def test_awk_usage_errors_raise(texts, match):
    rb, rs = _make_backend({})
    with pytest.raises(UsageError, match=match):
        await awk([], texts, None, read_bytes=rb, read_stream=rs, stdin=b"a\n")


@pytest.mark.asyncio
async def test_awk_out_of_range_field_prints_empty():
    rb, rs = _make_backend({})
    output, _ = await awk(
        [],
        ("{print $5}",),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=b"one two\n",
    )
    assert (await _drain(output)).decode() == "\n"


async def _run_io(program: str, stdin: bytes) -> tuple[str, int, bytes]:
    rb, rs = _make_backend({})
    output, io = await awk(
        [],
        (program,),
        None,
        read_bytes=rb,
        read_stream=rs,
        stdin=stdin,
    )
    out = (await _drain(output)).decode()
    err = io.stderr if isinstance(io.stderr, bytes) else b""
    return out, io.exit_code, err


@pytest.mark.parametrize(
    "program,stdin,expected",
    [
        ("{x = y + 1; print x}", b"line\n", "1\n"),
        ("{print toupper($1)}", b"line\n", "LINE\n"),
        ('{printf "%s\\n", $1}', b"line\n", "line\n"),
        ("{if ($1) print $1}", b"line\n", "line\n"),
        ("length($1) ~ /1/", b"a\n", "a\n"),
        ("NR % 2 == 0 {print}", b"a\nb\n", "b\n"),
        ('{gsub(/a/, "b"); print}', b"banana\n", "bbnbnb\n"),
        ("{while (i++ < 2) print i, $1}", b"x\n", "1 x\n2 x\n"),
        ('{c[$1]++} END{print c["a"], length(c)}', b"a\nb\na\n", "2 2\n"),
        ("function twice(n){return n*2} {print twice($1)}", b"21\n", "42\n"),
    ],
)
@pytest.mark.asyncio
async def test_awk_runs_what_the_scraper_refused(program, stdin, expected):
    assert await _run_stdin(program, stdin) == expected


@pytest.mark.parametrize(
    "program,message",
    [
        ('{print > "out.txt"}', "awk: file output requires a workspace\n"),
        ('{system("ls")}', "awk: running a command requires a workspace\n"),
        ('{"ls" | getline}', "awk: running a command requires a workspace\n"),
        ('{print | "cat"}', "awk: running a command requires a workspace\n"),
    ],
)
@pytest.mark.asyncio
async def test_awk_refuses_what_it_cannot_reach(program, message):
    out, code, err = await _run_io(program, b"a\n")
    assert (out, code, err) == ("", 2, message.encode())


async def _chunked(parts: tuple[bytes, ...]) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


@pytest.mark.parametrize(
    "parts,rs,expected",
    [
        ((b"a\n", b"\nb\n"), "", "a|b|"),
        ((b"a1", b"2b"), "[0-9]+", "a|b|"),
        ((b"a:", b"b"), ":", "a|b|"),
        ((b"h\xc3", b"\xa9:x"), ":", "h\u00e9|x|"),
    ],
)
@pytest.mark.asyncio
async def test_awk_rs_holds_a_record_across_chunks(parts, rs, expected):
    rb, read_stream = _make_backend({})
    output, _ = await awk(
        [],
        ('{printf "%s|", $0}',),
        {"v": [f"RS={rs}"]},
        read_bytes=rb,
        read_stream=read_stream,
        stdin=_chunked(parts),
    )
    assert (await _drain(output)).decode() == expected


@pytest.mark.asyncio
async def test_awk_rs_record_never_spans_two_files():
    rb, rs = _make_backend({"/a.txt": b"a:b", "/b.txt": b"c:d:"})
    output, _ = await awk(
        [_spec("/a.txt"), _spec("/b.txt")],
        ("{print FNR, NR, $0}",),
        {"v": ["RS=:"]},
        read_bytes=rb,
        read_stream=rs,
    )
    assert (await _drain(output)).decode() == "1 1 a\n2 2 b\n1 3 c\n2 4 d\n"


@pytest.mark.asyncio
async def test_awk_rs_paragraph_separator_is_the_whole_newline_run():
    rb, read_stream = _make_backend({})
    output, _ = await awk(
        [],
        ('{printf "%s|", $0; RS="\\n"}',),
        {"v": ["RS="]},
        read_bytes=rb,
        read_stream=read_stream,
        stdin=_chunked((b"a\n\n", b"\nb\n")),
    )
    assert (await _drain(output)).decode() == "a|b|"

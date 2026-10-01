from mirage.commands.builtin.grep_pattern import compile_pattern
from mirage.commands.builtin.grep_scan import grep_lines
from mirage.io.types import IOResult


class TestGrepLines:
    def test_basic(self):
        compiled = compile_pattern("hello")
        result = grep_lines(
            "/f.txt",
            ["hello world", "foo"],
            compiled,
            False,
            False,
            False,
            False,
            False,
            None,
        )
        assert result == ["hello world"]


def _only(lines, pattern, **kwargs):
    return grep_lines(
        "/f.txt",
        lines,
        compile_pattern(pattern),
        kwargs.get("invert", False),
        kwargs.get("line_numbers", False),
        kwargs.get("count_only", False),
        kwargs.get("files_only", False),
        True,
        kwargs.get("max_count"),
        kwargs.get("io"),
    )


class TestGrepLinesReportsSelection:
    """`grep_lines` answers selection on an IOResult.

    The returned list cannot stand in for it: under -o an empty match
    prints nothing and still selects the line, so a caller deriving the
    status from an empty list answers 1 where GNU answers 0.
    """

    def test_empty_match_selects_the_line_although_nothing_prints(self):
        io = IOResult(exit_code=1)
        assert _only(["ab"], "[0-9]*", io=io) == []
        assert io.exit_code == 0

    def test_no_match_at_all_leaves_the_seeded_status(self):
        io = IOResult(exit_code=1)
        assert _only(["ab"], "[0-9]", io=io) == []
        assert io.exit_code == 1

    def test_a_printed_match_also_selects(self):
        io = IOResult(exit_code=1)
        assert _only(["a1b"], "[0-9]", io=io) == ["1"]
        assert io.exit_code == 0

    def test_selection_is_reported_under_count_only(self):
        io = IOResult(exit_code=1)
        assert _only(["ab"], "[0-9]*", count_only=True, io=io) == ["1"]
        assert io.exit_code == 0

    def test_omitting_the_channel_is_still_supported(self):
        assert _only(["a1b"], "[0-9]") == ["1"]


class TestOnlyMatchingEmptyMatches:
    """GNU's two-part -o rule, which is easy to half-implement.

    An empty match prints nothing, but the line is still selected: `-c`
    counts it, the exit status is 0, and grep's binary-file notice still
    fires. And every non-empty match on the line prints, one per line,
    not just the first.
    """

    def test_lines_path_drops_the_empty_match(self):
        assert _only(["ab"], "[0-9]*") == []

    def test_lines_path_still_selects_the_line_for_count(self):
        assert _only(["ab"], "[0-9]*", count_only=True) == ["1"]

    def test_lines_path_still_selects_the_line_for_files_only(self):
        assert _only(["ab"], "[0-9]*", files_only=True) == ["/f.txt"]

    def test_lines_path_keeps_only_the_real_match(self):
        assert _only(["a1b"], "[0-9]*") == ["1"]

    def test_lines_path_prints_every_match_on_the_line(self):
        assert _only(["a1b2c"], "[0-9]") == ["1", "2"]

    def test_lines_path_keeps_nonempty_runs_in_order(self):
        assert _only(["1a22b"], "[0-9]*") == ["1", "22"]

    def test_lines_path_numbers_every_printed_match(self):
        assert _only(["a1b2c"], "[0-9]", line_numbers=True) == ["1:1", "1:2"]


class TestByteOffsetsInTheSelectPath:
    """-b through grep_lines (GNU grep 3.11, section Q)."""

    def test_lines_print_the_line_start_offset(self):
        hits = grep_lines(
            "/f.txt",
            ["abc", "defabc", "abc abc"],
            compile_pattern("abc"),
            False,
            False,
            False,
            False,
            False,
            None,
            None,
            True,
        )
        assert hits == ["0:abc", "4:defabc", "11:abc abc"]

    def test_lines_print_the_match_offset_under_only_matching(self):
        hits = grep_lines(
            "/f.txt",
            ["abc", "defabc", "abc abc"],
            compile_pattern("abc"),
            False,
            False,
            False,
            False,
            True,
            None,
            None,
            True,
        )
        assert hits == ["0:abc", "7:abc", "11:abc", "15:abc"]

    def test_lines_keep_gnu_field_order_whatever_the_flags(self):
        hits = grep_lines(
            "/f.txt",
            ["abc", "defabc"],
            compile_pattern("abc"),
            False,
            True,
            False,
            False,
            False,
            None,
            None,
            True,
        )
        assert hits == ["1:0:abc", "2:4:defabc"]

    def test_lines_count_bytes_not_characters(self):
        # `caf` + U+00E9 (two bytes) + a space is six bytes.
        hits = grep_lines(
            "/f.txt",
            ["café abc", "xéy abc"],
            compile_pattern("abc"),
            False,
            False,
            False,
            False,
            True,
            None,
            None,
            True,
        )
        assert hits == ["6:abc", "15:abc"]

    def test_lines_leave_a_count_and_a_file_list_alone(self):
        counted = grep_lines(
            "/f.txt",
            ["abc", "defabc"],
            compile_pattern("abc"),
            False,
            False,
            True,
            False,
            False,
            None,
            None,
            True,
        )
        listed = grep_lines(
            "/f.txt",
            ["abc"],
            compile_pattern("abc"),
            False,
            False,
            False,
            True,
            False,
            None,
            None,
            True,
        )
        assert (counted, listed) == (["2"], ["/f.txt"])

    def test_lines_print_the_offsets_of_the_lines_v_selected(self):
        hits = grep_lines(
            "/f.txt",
            ["one", "two abc", "three", "four abc", "five"],
            compile_pattern("abc"),
            True,
            False,
            False,
            False,
            False,
            None,
            None,
            True,
        )
        assert hits == ["0:one", "12:three", "27:five"]


class TestMaxCountZeroSelectsNothing:
    """`-m 0` selects no line at all, which is what GNU does.

    Measured on GNU grep 3.11: `grep -m0 a f`, `grep -m0 -c a f`,
    `grep -m0 -v a f` and `grep -m0 -l a f` all print zero bytes and exit
    1. Reading the limit only after a line was printed let the first
    selected line out first, because `count >= 0` is already true.
    """

    def test_lines_print_nothing(self):
        assert _only(["a", "ab", "b"], "a", max_count=0) == []

    def test_lines_count_prints_nothing(self):
        # Not `["0"]`: a caller renders `<file>:<count>` from whatever
        # comes back, and GNU prints no per-file zeros under -m0.
        assert _only(["a", "ab", "b"], "a", max_count=0, count_only=True) == []

    def test_lines_name_no_file(self):
        assert _only(["a", "ab", "b"], "a", max_count=0, files_only=True) == []

    def test_lines_report_no_selection(self):
        io = IOResult(exit_code=1)
        _only(["a", "ab", "b"], "a", max_count=0, io=io)
        assert io.exit_code == 1


class TestOnlyMatchingWithInvertPrintsNothing:
    """`-o -v` prints nothing, because an unselected pattern has no match.

    Measured on GNU grep 3.11 over `abc\\ndef\\n`: `grep -ov abc` is zero
    bytes and exit 0, `grep -ovc abc` is `1`, and `grep -ovl abc` names the
    file. ripgrep prints the whole line instead; GNU is the reference the
    rest of this family already follows for -o.
    """

    def test_lines_print_nothing(self):
        assert _only(["abc", "def"], "abc", invert=True) == []

    def test_lines_still_count_the_selected_line(self):
        assert _only(["abc", "def"], "abc", invert=True, count_only=True) == [
            "1"
        ]

    def test_lines_still_name_the_file(self):
        assert _only(["abc", "def"], "abc", invert=True, files_only=True) == [
            "/f.txt"
        ]

    def test_lines_still_report_selection(self):
        io = IOResult(exit_code=1)
        _only(["abc", "def"], "abc", invert=True, io=io)
        assert io.exit_code == 0


class TestOffsetsOverSmuggledBytes:
    """A byte offset counts bytes, and an invalid byte is one byte.

    `grep -bo a` over `\\xffa\\n` is `1:a` on GNU grep 3.11, and
    `grep -b a` over `\\xff\\na\\n` is `2:a`. A replacing decode read the
    invalid byte as U+FFFD, three bytes wide, so both answers ran ahead.
    """

    def test_lines_count_a_smuggled_byte_as_one(self):
        rows = grep_lines(
            "/f.txt",
            ["\udcffa"],
            compile_pattern("a"),
            False,
            False,
            False,
            False,
            True,
            None,
            None,
            True,
        )
        assert rows == ["1:a"]

    def test_lines_replace_a_smuggled_byte_on_the_way_out(self):
        # A list-returning scan hands its lines to `format_records`, which
        # puts a surrogate escape back as the byte it stands for, so the
        # line keeps it: GNU grep and ripgrep both print the byte raw.
        rows = grep_lines(
            "/f.txt",
            ["\udcffa"],
            compile_pattern("a"),
            False,
            False,
            False,
            False,
            False,
            None,
            None,
            True,
        )
        assert rows == ["0:\udcffa"]

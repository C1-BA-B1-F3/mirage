from mirage.commands.builtin.grep_select import (
    FileGlob,
    WalkFilters,
    file_admitted,
    parse_file_globs,
)
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView


def _rules(*pairs: tuple[str, bool]) -> WalkFilters:
    return WalkFilters(
        file_globs=tuple(
            FileGlob(glob=glob, admit=admit) for glob, admit in pairs
        )
    )


def test_file_admitted_resolves_rules_in_line_order():
    # Pinned against GNU grep 3.11: the last matching rule decides.
    inc_then_exc = _rules(("*.txt", True), ("*.txt", False))
    assert not file_admitted("/d/a.txt", inc_then_exc)
    exc_then_inc = _rules(("*.txt", False), ("*.txt", True))
    assert file_admitted("/d/a.txt", exc_then_inc)


def test_file_admitted_no_match_default_follows_the_first_rule():
    # GNU 3.11: a file matching no rule is admitted only when the
    # first rule is an exclude.
    exc_first = _rules(("*.log", False), ("*.zzz", True))
    assert file_admitted("/d/a.txt", exc_first)
    inc_first = _rules(("*.zzz", True), ("*.log", False))
    assert not file_admitted("/d/a.txt", inc_first)


def test_file_admitted_empty_rules_admit_everything():
    assert file_admitted("/d/a.bin", WalkFilters())


def test_parse_file_globs_reads_dests_in_typed_order():
    exc_first = FlagView(
        {"exclude": ["notes.*"], "include": ["*.tex"]}, spec=SPECS["grep"]
    )
    assert parse_file_globs(exc_first) == (
        FileGlob(glob="notes.*", admit=False),
        FileGlob(glob="*.tex", admit=True),
    )
    inc_first = FlagView(
        {"include": ["*.tex"], "exclude": ["notes.*"]}, spec=SPECS["grep"]
    )
    assert parse_file_globs(inc_first) == (
        FileGlob(glob="*.tex", admit=True),
        FileGlob(glob="notes.*", admit=False),
    )

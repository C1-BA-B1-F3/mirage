import pytest

from mirage.commands.spec.compile import expand_table_long
from mirage.commands.spec.long_options import GNU_LONG_OPTIONS


@pytest.mark.parametrize(
    "command, spelling, expected",
    [
        ("grep", "--co", ["--context", "--color", "--colour", "--count"]),
        ("date", "--u", ["--uct"]),
        ("date", "--rfc", ["--rfc-email", "--rfc-3339"]),
        ("gzip", "--s", ["--stdout", "--silent", "--synchronous", "--suffix"]),
        ("cmp", "--print", ["--print-bytes", "--print-chars"]),
        ("cat", "--number", ["--number"]),
        ("date", "--universal", ["--uct"]),
    ],
)
def test_gnu_option_identity_and_ambiguity(command, spelling, expected):
    assert (
        list(expand_table_long(GNU_LONG_OPTIONS[command], spelling))
        == expected
    )

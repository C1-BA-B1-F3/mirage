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

from datetime import timedelta, timezone

import pytest

from mirage.commands.cli.builtin.git.dates import (date_clock, parse_date_mode,
                                                   relative_date, show_date)
from mirage.commands.cli.builtin.git.errors import (DateFormatColonError,
                                                    UnknownDateFormatError)
from mirage.commands.cli.builtin.git.types import DateKind, DateMode

CLOCK = DateMode(now=1768561800, zone=timezone.utc)


def _mode(value: str) -> DateMode:
    """Parse a ``--date`` value against the fixed test clock.

    Args:
        value (str): the value as typed.
    """
    return parse_date_mode(value, CLOCK)


def test_date_matches_gits_default_format():
    # Pinned against git 2.47.3: the day of the month is not padded,
    # which rules out strftime's %d.
    assert show_date(1768561800, 0,
                     DateMode()) == "Fri Jan 16 11:10:00 2026 +0000"


def test_single_digit_day_is_not_padded():
    # git 2.47.3 prints "Mon Jan 5", not "Mon Jan 05" and not "Jan  5".
    assert show_date(1767603900, 0,
                     DateMode()) == "Mon Jan 5 09:05:00 2026 +0000"


def test_date_renders_in_the_authors_own_offset():
    assert show_date(1768561800, 8 * 3600,
                     DateMode()) == "Fri Jan 16 19:10:00 2026 +0800"


def test_negative_offset_renders_with_a_minus():
    assert show_date(1768561800, -7 * 3600,
                     DateMode()) == "Fri Jan 16 04:10:00 2026 -0700"


@pytest.mark.parametrize("value,expected", [
    ("iso", "2026-01-16 16:40:00 +0530"),
    ("iso8601", "2026-01-16 16:40:00 +0530"),
    ("iso-strict", "2026-01-16T16:40:00+05:30"),
    ("iso8601-strict", "2026-01-16T16:40:00+05:30"),
    ("rfc", "Fri, 16 Jan 2026 16:40:00 +0530"),
    ("rfc2822", "Fri, 16 Jan 2026 16:40:00 +0530"),
    ("short", "2026-01-16"),
    ("raw", "1768561800 +0530"),
    ("unix", "1768561800"),
    ("default", "Fri Jan 16 16:40:00 2026 +0530"),
    ("auto:iso", "Fri Jan 16 16:40:00 2026 +0530"),
    ("local", "Fri Jan 16 11:10:00 2026"),
    ("iso-local", "2026-01-16 11:10:00 +0000"),
    ("format:%Y/%m/%d %z [%Z]", "2026/01/16 +0530 []"),
    ("format-local:%H:%M %Z", "11:10 UTC"),
    ("format:", ""),
])
def test_every_style_git_names(value, expected):
    assert show_date(1768561800, 19800, _mode(value)) == expected


@pytest.mark.parametrize("offset,wall", [(19800, "16:40 +0530"),
                                         (-25200, "04:10 -0700")])
def test_formatted_epoch_keeps_the_instant_and_percent_escapes(offset, wall):
    mode = _mode("format:%s %%s %%%s %H:%M %z")
    assert show_date(1768561800, offset,
                     mode) == (f"1768561800 %s %1768561800 {wall}")


def test_formatted_local_epoch_keeps_the_instant():
    clock = date_clock({"TZ": "Asia/Kolkata"})
    mode = parse_date_mode("format-local:%s %H:%M %z", clock)
    assert show_date(1768561800, -25200, mode) == "1768561800 16:40 +0530"


def test_strict_iso_names_utc_as_z():
    assert show_date(1768561800, 0,
                     _mode("iso-strict")) == "2026-01-16T11:10:00Z"


@pytest.mark.parametrize("value", ["bogus", "iso8601x", "local-bogus"])
def test_a_style_git_lacks_is_refused_whole(value):
    with pytest.raises(UnknownDateFormatError) as info:
        _mode(value)
    assert str(info.value) == f"unknown date format {value}"


def test_format_needs_its_colon():
    with pytest.raises(DateFormatColonError) as info:
        _mode("format")
    assert str(info.value) == "date format missing colon separator: format"


@pytest.mark.parametrize("seconds,expected", [
    (-5, "in the future"),
    (0, "0 seconds ago"),
    (1, "1 second ago"),
    (89, "89 seconds ago"),
    (90, "2 minutes ago"),
    (5369, "89 minutes ago"),
    (5399, "2 hours ago"),
    (5400, "2 hours ago"),
    (36 * 3600, "2 days ago"),
    (14 * 86400, "2 weeks ago"),
    (70 * 86400, "2 months ago"),
    (365 * 86400, "1 year ago"),
    (400 * 86400, "1 year, 1 month ago"),
    (800 * 86400, "2 years, 2 months ago"),
    (1825 * 86400, "5 years ago"),
])
def test_relative_dates_round_as_git_does(seconds, expected):
    assert relative_date(1768561800 - seconds, 1768561800) == expected


@pytest.mark.parametrize("now,expected", [
    (1768561800 + 3600, "60 minutes ago"),
    (1768561800 + 3 * 86400, "Fri 16:40 +0530"),
    (1768561800 + 20 * 86400, "Fri Jan 16 16:40"),
    (1768561800 + 400 * 86400, "Jan 16 2026"),
])
def test_human_dates_hide_what_the_reader_already_knows(now, expected):
    mode = DateMode(kind=DateKind.HUMAN, now=now, zone=timezone.utc)
    assert show_date(1768561800, 19800, mode) == expected


def test_human_dates_hide_the_readers_own_offset():
    mode = DateMode(kind=DateKind.HUMAN,
                    now=1768561800 + 3 * 86400,
                    zone=timezone(timedelta(hours=5, minutes=30)))
    assert show_date(1768561800, 19800, mode) == "Fri 16:40"


def test_the_clock_reads_gits_test_variable_and_tz():
    clock = date_clock({"GIT_TEST_DATE_NOW": "1234 rest", "TZ": "UTC"})
    assert clock.now == 1234
    assert clock.zone is not None
    assert date_clock({"GIT_TEST_DATE_NOW": "x"}).now == 0

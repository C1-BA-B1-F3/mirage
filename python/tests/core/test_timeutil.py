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

from datetime import datetime, timedelta, timezone

import pytest

from mirage.core.timeutil import (epoch_to_iso, iso_to_epoch, now_iso,
                                  ns_to_iso, to_iso_z)


def test_to_iso_z_converts_utc_offset_to_z():
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert to_iso_z(dt) == "2026-01-02T03:04:05Z"


def test_to_iso_z_normalizes_non_utc_to_z():
    tz = timezone(timedelta(hours=5))
    dt = datetime(2026, 1, 2, 8, 4, 5, tzinfo=tz)
    assert to_iso_z(dt) == "2026-01-02T03:04:05Z"


def test_now_iso_uses_z_suffix():
    s = now_iso()
    assert s.endswith("Z")
    assert "+00:00" not in s


def test_epoch_to_iso_whole_second():
    assert epoch_to_iso(1609459200) == "2021-01-01T00:00:00Z"


def test_epoch_to_iso_truncates_sub_second():
    assert epoch_to_iso(1609459200.987) == "2021-01-01T00:00:00Z"


def test_iso_to_epoch_inverts_epoch_to_iso():
    assert iso_to_epoch("2021-01-01T00:00:00Z") == 1609459200
    assert iso_to_epoch("2026-01-02T15:30:45Z") == 1767367845


def test_iso_to_epoch_reads_naive_stamp_as_utc():
    assert iso_to_epoch("2026-01-02T15:30:45") == 1767367845


def test_iso_to_epoch_honors_offset_and_truncates_sub_second():
    assert iso_to_epoch("2021-01-01T01:00:00+01:00") == 1609459200
    assert iso_to_epoch("2026-07-22T06:57:48.064802Z") == 1784703468


def test_epoch_floors_negative_fractional_like_typescript():
    # A pre-1970 fractional second floors to -1 (matching Math.floor in TS),
    # not 0 as int() truncation would give.
    assert iso_to_epoch("1969-12-31T23:59:59.500Z") == -1
    assert epoch_to_iso(-0.5) == "1969-12-31T23:59:59Z"


@pytest.mark.parametrize("input,expected", [
    ("2026-09-05T10:55:39.000Z", "2026-09-05T10:55:39Z"),
    ("2026-09-05T10:55:39.001Z", "2026-09-05T10:55:39.001000Z"),
    ("2026-09-05T10:55:39.120Z", "2026-09-05T10:55:39.120000Z"),
    ("2026-09-05T12:55:39.123+02:00", "2026-09-05T10:55:39.123000Z"),
    ("1969-12-31T23:59:59.500Z", "1969-12-31T23:59:59.500000Z"),
])
def test_to_iso_z_fraction_policy(input, expected):
    assert to_iso_z(datetime.fromisoformat(input)) == expected


@pytest.mark.parametrize("ns,want", [
    (1_609_459_200_000_000_000, "2021-01-01T00:00:00.000Z"),
    (1_704_067_200_500_000_000, "2024-01-01T00:00:00.500Z"),
    (1_759_216_160_567_499_999, "2025-09-30T07:09:20.568Z"),
    (1_759_216_160_999_999_999, "2025-09-30T07:09:21.000Z"),
    (-1_500_000, "1969-12-31T23:59:59.999Z"),
])
def test_ns_to_iso_rounds_as_node_stat_dates(ns, want):
    # Pinned against node 24: `fs.statSync(p).mtime.toISOString()` for a
    # file whose mtime was set to `ns`, and `new Date(-1)` for the last.
    assert ns_to_iso(ns) == want

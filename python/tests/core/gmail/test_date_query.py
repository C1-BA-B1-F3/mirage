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

from datetime import date, datetime, timezone

import pytest

from mirage.core.gmail.date_query import (
    date_dir_to_gmail_query,
    span_to_gmail_query,
)


# Epoch seconds for midnight UTC, one second early on the lower bound.
@pytest.mark.parametrize(
    "name,expected",
    [
        ("2026-05-03", "after:1777766399 before:1777852800"),
        ("2026-12-31", "after:1798675199 before:1798761600"),
        ("2026-01-01", "after:1767225599 before:1767312000"),
    ],
)
def test_date_dir_to_gmail_query_translates(name, expected):
    assert date_dir_to_gmail_query(name) == expected


def test_span_bounds_are_utc_seconds():
    query = span_to_gmail_query(date(2026, 1, 1), date(2026, 2, 1))
    after, before = (int(term.split(":")[1]) for term in query.split())
    assert datetime.fromtimestamp(before, tz=timezone.utc) == datetime(
        2026, 2, 1, tzinfo=timezone.utc
    )
    assert before - after == 31 * 86400 + 1


@pytest.mark.parametrize(
    "name",
    [
        "",
        "2026-13-01",
        "2026-02-30",
        "2026-5-3",
        "2026",
        "not-a-date",
        "2026-05",
        "2026-05-03-extra",
    ],
)
def test_date_dir_to_gmail_query_rejects(name):
    assert date_dir_to_gmail_query(name) is None

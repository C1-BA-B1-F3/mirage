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

from mirage.utils.sanitize import NAME_MAX_BYTES
from mirage.vfs.gcal.event_entry import (
    PRIMARY_DIR,
    event_title,
    make_calendar_dirname,
    make_event_filename,
    parse_event_filename,
)

EVENT_ID = "la9i1t995acovthi3f761chla0"


@pytest.mark.parametrize(
    "title, day, name",
    [
        ("PhD_Defense", None, f"{EVENT_ID}__0900-1030_PhD_Defense.gcal.json"),
        ("A__B_C", None, f"{EVENT_ID}__0900-1030_A__B_C.gcal.json"),
        (
            "PhD_Defense",
            "2026-08-11",
            f"{EVENT_ID}__2026-08-11_0900-1030_PhD_Defense.gcal.json",
        ),
    ],
)
def test_a_filename_leads_with_the_id_and_round_trips(title, day, name):
    assert make_event_filename(EVENT_ID, "0900-1030", title, day) == name
    assert parse_event_filename(name) == (EVENT_ID, day)


@pytest.mark.parametrize(
    "name",
    [
        "notes.txt",
        "noseparator.gcal.json",
        f"{EVENT_ID}__090.gcal.json",
        f"{EVENT_ID}__0900-1030x.gcal.json",
        f"{EVENT_ID}__2026-08-11_090.gcal.json",
    ],
)
def test_a_name_without_a_time_label_is_not_an_event(name):
    with pytest.raises(FileNotFoundError):
        parse_event_filename(name)


@pytest.mark.parametrize(
    "title", ["a" * 400, "会" * 200], ids=["ascii", "cjk"]
)
@pytest.mark.parametrize("day", [None, "2026-08-11"])
def test_a_long_title_is_trimmed_by_bytes_to_name_max(title, day):
    # 3 bytes per CJK character: a character-counted budget would overflow
    # NAME_MAX, the bug gdocs/gsheets/gslides had until sanitize_label grew
    # a byte budget.
    name = make_event_filename(EVENT_ID, "0900-1030", title, day)
    assert len(name.encode()) <= NAME_MAX_BYTES
    assert parse_event_filename(name) == (EVENT_ID, day)


def test_the_title_is_dropped_when_a_long_id_leaves_no_room():
    # 234 is the widest id that still names an event: the title is squeezed
    # out and id + separators + suffix lands exactly on NAME_MAX.
    long_id = "v" * 234
    name = make_event_filename(long_id, "0900-1030", "Some_Title")
    assert name == f"{long_id}__0900-1030.gcal.json"
    assert len(name.encode()) == NAME_MAX_BYTES


def test_an_id_too_long_to_name_is_kept_rather_than_truncated():
    # The title is what gives, never the id: a trimmed id would stop
    # addressing the event. Google's own ids are 26 chars, so this only
    # arises for a caller-supplied events.import id.
    long_id = "v" * (NAME_MAX_BYTES - 20)
    name = make_event_filename(long_id, "0900-1030", "Some Title")
    assert len(name.encode()) > NAME_MAX_BYTES
    assert parse_event_filename(name) == (long_id, None)


@pytest.mark.parametrize(
    "summary, free_busy, title",
    [
        ("Standup", False, "Standup"),
        (None, False, "untitled"),
        ("   ", False, "untitled"),
        (None, True, "busy"),
    ],
)
def test_event_title_falls_back_by_access_role(summary, free_busy, title):
    assert event_title(summary, free_busy=free_busy) == title


@pytest.mark.parametrize(
    "summary, cal_id, primary, name",
    [
        ("integ@example.com", "integ@example.com", True, PRIMARY_DIR),
        (
            "US Holidays",
            "en.usa#holiday@group.v.calendar.google.com",
            False,
            "US_Holidays__en.usa#holiday@group.v.calendar.google.com",
        ),
    ],
)
def test_calendar_dirname_is_the_alias_or_embeds_the_id(
    summary, cal_id, primary, name
):
    assert make_calendar_dirname(summary, cal_id, primary=primary) == name

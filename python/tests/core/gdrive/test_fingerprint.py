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

import json
from pathlib import Path

import pytest

from mirage.cache.index import IndexEntry
from mirage.core.gdrive.fingerprint import drive_fingerprint, entry_fingerprint

# Shared with the TypeScript suite, so the two hosts answer one table.
_FIXTURE = (Path(__file__).parents[4] / "integ" / "fixtures" / "gdrive" /
            "fingerprint.json")

_CASES = json.loads(_FIXTURE.read_text())


def test_the_shared_table_is_not_empty():
    assert len(_CASES) >= 8


@pytest.mark.parametrize("name", sorted(_CASES))
def test_drive_fingerprint_matches_the_shared_table(name):
    case = _CASES[name]
    assert drive_fingerprint(case["resource_type"], case["md5"],
                             case["head_revision"],
                             case["modified"]) == case["expected"]


def test_an_entry_of_a_file_with_content_answers_its_md5():
    entry = IndexEntry(id="f",
                       name="a.pdf",
                       resource_type="gdrive/file",
                       remote_time="2026-01-01T00:00:00Z",
                       extra={
                           "md5_checksum": "abc",
                           "head_revision_id": "r3"
                       })
    assert entry_fingerprint(entry) == "abc"


def test_an_entry_of_a_doc_answers_its_stamp():
    entry = IndexEntry(id="d",
                       name="notes",
                       resource_type="gdrive/gdoc",
                       remote_time="2026-01-01T00:00:00Z")
    assert entry_fingerprint(entry) == "2026-01-01T00:00:00Z"

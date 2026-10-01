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

from mirage.cache.index.config import IndexEntry


def test_index_entry_extra_defaults_to_empty_dict():
    entry = IndexEntry(id="x", name="x", resource_type="t")
    assert entry.extra == {}


def test_index_entry_extra_round_trip():
    entry = IndexEntry(
        id="F1",
        name="report",
        resource_type="slack/file",
        extra={
            "url": "https://files.slack.com/x",
            "mimetype": "application/pdf",
        },
    )
    assert entry.extra == {
        "url": "https://files.slack.com/x",
        "mimetype": "application/pdf",
    }


def test_index_entry_extra_survives_json_round_trip():
    entry = IndexEntry(
        id="F1",
        name="report",
        resource_type="slack/file",
        extra={"url": "u"},
    )
    restored = IndexEntry.model_validate_json(entry.model_dump_json())
    assert restored.extra == {"url": "u"}

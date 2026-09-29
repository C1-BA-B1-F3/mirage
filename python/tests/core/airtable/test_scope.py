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

from mirage.core.airtable.scope import detect_scope

BASE = "bases/Roadmap__appRoadmapBase001"
TABLE = f"{BASE}/Features__tblFeatures000001"


@pytest.mark.parametrize("path, kind, slots", [
    ("/", "root", {}),
    ("/bases", "bases", {}),
    (f"/{BASE}", "base", {
        "base_id": "appRoadmapBase001"
    }),
    (f"/{BASE}/base.json", "base_json", {
        "base_id": "appRoadmapBase001"
    }),
    (f"/{TABLE}", "table", {
        "table_id": "tblFeatures000001"
    }),
    (f"/{TABLE}/table.json", "table_json", {
        "table_id": "tblFeatures000001"
    }),
    (f"/{TABLE}/records.jsonl", "records", {
        "table_id": "tblFeatures000001"
    }),
    (f"/{TABLE}/views", "views", {}),
    (f"/{TABLE}/views/Done__viwDone0000000001.jsonl", "view", {
        "view_id": "viwDone0000000001"
    }),
    (f"/{TABLE}/views/Done__viwDone0000000001.json", "invalid", {}),
    (f"/{BASE}/no_separator", "invalid", {}),
    (f"/{TABLE}/.hidden", "invalid", {}),
])
def test_every_level_classifies(path, kind, slots):
    match = detect_scope(path)
    assert match.kind == kind
    for key, value in slots.items():
        assert match.slots[key] == value

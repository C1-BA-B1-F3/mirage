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

from mirage.core.airtable.pathing import (base_dirname, table_dirname,
                                          view_filename)
from mirage.utils.naming import parse_id_name


def test_names_are_sanitized_labels_joined_to_exact_ids():
    assert base_dirname({
        "id": "appOpsFinance0001",
        "name": "Ops / Finance ✓"
    }) == "Ops_Finance__appOpsFinance0001"
    assert table_dirname({
        "id": "tblBudget00000001",
        "name": "Q3 / Budget"
    }) == "Q3_Budget__tblBudget00000001"
    assert view_filename({
        "id": "viwDone0000000001",
        "name": "Done / shipped"
    }) == "Done_shipped__viwDone0000000001.jsonl"


def test_a_nameless_entity_falls_back_to_its_id():
    assert table_dirname({"id": "tblX", "name": ""}) == "tblX__tblX"


def test_the_id_survives_a_label_past_name_max():
    name = view_filename({"id": "viwDone0000000001", "name": "界" * 200})
    assert len(name.encode()) <= 255
    assert parse_id_name(name, suffix=".jsonl")[1] == "viwDone0000000001"

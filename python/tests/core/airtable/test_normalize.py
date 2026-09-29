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

from mirage.core.airtable import normalize
from mirage.core.airtable.normalize import (deletions_jsonl, normalize_base,
                                            normalize_base_summary,
                                            normalize_comment,
                                            normalize_record, normalize_table,
                                            records_jsonl)


def test_base_json_lists_its_tables():
    base = {"id": "appA", "name": "A", "permissionLevel": "read"}
    tables = [{"id": "tblT", "name": "T", "primaryFieldId": "fldP"}]
    assert normalize_base(base, tables) == {
        "base_id":
        "appA",
        "base_name":
        "A",
        "permission_level":
        "read",
        "tables": [{
            "table_id": "tblT",
            "table_name": "T",
            "primary_field_id": "fldP"
        }],
    }


def test_table_json_keeps_field_types_and_options():
    table = {
        "id":
        "tblT",
        "name":
        "T",
        "primaryFieldId":
        "fldP",
        "fields": [{
            "id": "fldP",
            "name": "Name",
            "type": "singleLineText"
        }, {
            "id": "fldS",
            "name": "Status",
            "type": "singleSelect",
            "options": {
                "choices": []
            }
        }],
        "views": [{
            "id": "viwG",
            "name": "Grid view",
            "type": "grid"
        }],
    }
    out = normalize_table(table, "appA")
    assert out["base_id"] == "appA"
    assert out["fields"][1] == {
        "field_id": "fldS",
        "field_name": "Status",
        "type": "singleSelect",
        "description": None,
        "options": {
            "choices": []
        },
    }
    assert out["views"] == [{
        "view_id": "viwG",
        "view_name": "Grid view",
        "type": "grid"
    }]


def test_a_record_passes_its_cells_through():
    record = {
        "id": "recA",
        "createdTime": "2026-01-01T00:00:00.000Z",
        "fields": {
            "Name": "é",
            "Link": ["recB"]
        }
    }
    assert normalize_record(record) == {
        "record_id": "recA",
        "created_time": "2026-01-01T00:00:00.000Z",
        "fields": {
            "Name": "é",
            "Link": ["recB"]
        },
    }
    assert normalize_record({"id": "recC"})["fields"] == {}


def test_records_render_one_line_each_in_listing_order():
    rows = records_jsonl([{
        "id": "rec2",
        "fields": {
            "Notes": "a\nb"
        }
    }, {
        "id": "rec1",
        "fields": {}
    }])
    lines = rows.decode().splitlines()
    assert [json.loads(line)["record_id"]
            for line in lines] == ["rec2", "rec1"]
    assert records_jsonl([]) == b""


def test_a_base_summary_is_base_json_without_its_tables():
    base = {"id": "appA", "name": "A", "permissionLevel": "edit"}
    assert normalize_base_summary(base) == {
        "base_id": "appA",
        "base_name": "A",
        "permission_level": "edit",
    }
    full = normalize_base(base, [])
    assert {k: v for k, v in full.items() if k != "tables"} == \
        normalize_base_summary(base)


def test_a_comment_flattens_its_author():
    comment = {
        "id": "comA",
        "author": {
            "id": "usrA",
            "email": "a@example.com",
            "name": "A"
        },
        "text": "hi",
        "createdTime": "2026-01-01T00:00:00.000Z",
        "lastUpdatedTime": None,
        "mentioned": {},
    }
    assert normalize_comment(comment) == {
        "comment_id": "comA",
        "author_id": "usrA",
        "author_email": "a@example.com",
        "author_name": "A",
        "text": "hi",
        "created_time": "2026-01-01T00:00:00.000Z",
        "last_updated_time": None,
    }
    assert normalize_comment({"id": "comB"})["author_id"] is None


def test_deletions_render_one_line_each():
    rows = deletions_jsonl([{"id": "rec1", "deleted": True}])
    assert rows == b'{"record_id":"rec1","deleted":true}\n'
    assert deletions_jsonl([]) == b""


def test_only_json_objects_count_as_rows():
    assert normalize.as_row({"a": 1}) == {"a": 1}
    assert normalize.as_row([{"a": 1}]) == {}
    assert normalize.as_row(None) == {}
    assert normalize.as_rows([{
        "a": 1
    }, "x", None, [2], {
        "b": 2
    }]) == [{
        "a": 1
    }, {
        "b": 2
    }]
    assert normalize.as_rows({"a": 1}) == []
    assert normalize.as_rows(None) == []

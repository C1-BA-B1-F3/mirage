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

from mirage.core.airtable.errors import AirtableAPIError, error_parts


def test_error_parts_reads_every_body_shape():
    assert error_parts('{"error": {"type": "X", "message": "m"}}') == ("X",
                                                                       "m")
    assert error_parts(
        '{"error": {"type": "LIST_RECORDS_ITERATOR_NOT_'
        'AVAILABLE"}}') == ("LIST_RECORDS_ITERATOR_NOT_AVAILABLE", None)
    assert error_parts('{"error": "NOT_FOUND"}') == ("NOT_FOUND", None)
    assert error_parts("not json") == (None, None)
    assert error_parts("[1]") == (None, None)


def test_not_found_covers_airtables_403_answer():
    assert AirtableAPIError("m", status=404).not_found
    assert AirtableAPIError(
        "m", status=403,
        error_type="INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND").not_found
    assert not AirtableAPIError("m", status=422,
                                error_type="INVALID_REQUEST").not_found


def test_a_missing_view_is_not_found_by_id_or_by_name():
    for kind in ("VIEW_ID_NOT_FOUND", "VIEW_NAME_NOT_FOUND"):
        assert AirtableAPIError("m", status=422, error_type=kind).not_found

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

from mirage.core.slack.formatters import file_blob_name
from mirage.utils.sanitize import NAME_MAX_BYTES, byte_len

BLOB_ID = "F0123456789"


@pytest.mark.parametrize(
    "meta,expected",
    [
        ({"id": "F1", "name": "report.pdf"}, "report__F1.pdf"),
        ({"id": "F2", "title": "design doc.docx"}, "design doc__F2.docx"),
        ({"id": "F3", "name": "readme"}, "readme__F3"),
        ({"id": "F4"}, "file__F4"),
    ],
)
def test_file_blob_name(meta, expected):
    assert file_blob_name(meta) == expected


@pytest.mark.parametrize(
    "raw_name,expected_tail",
    [
        ("会議" * 100 + ".txt", ".txt"),
        ("会議" * 100, ""),
    ],
)
def test_a_long_filename_fits_name_max_and_keeps_id_and_extension(
    raw_name, expected_tail
):
    """The stem is the only part that gives.

    A trimmed id stops addressing the file and a trimmed extension changes
    its type, so both are spent before the stem gets its budget.
    """
    name = file_blob_name({"name": raw_name, "id": BLOB_ID})

    assert byte_len(name) <= NAME_MAX_BYTES
    assert name.endswith(f"{BLOB_ID}{expected_tail}")
    assert "�" not in name

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


@pytest.mark.parametrize(
    "meta,expected",
    [
        ({"id": "F1", "name": "report.pdf", "title": "Q4"}, "report__F1.pdf"),
        (
            {"id": "F2", "name": "", "title": "design doc.docx"},
            "design doc__F2.docx",
        ),
        ({"id": "F3"}, "file__F3"),
    ],
)
def test_file_blob_name(meta, expected):
    assert file_blob_name(meta) == expected

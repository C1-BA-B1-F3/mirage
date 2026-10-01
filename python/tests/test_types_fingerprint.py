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

from mirage.types import ContentType, FileStat, FileType


def test_file_stat_has_fingerprint_field():
    st = FileStat(
        name="x",
        type=FileType.FILE,
        content=ContentType.TEXT,
        fingerprint="abc123",
    )
    assert st.fingerprint == "abc123"


def test_file_stat_fingerprint_defaults_none():
    st = FileStat(name="x", type=FileType.FILE, content=ContentType.TEXT)
    assert st.fingerprint is None

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

from mirage.core.nextcloud.stream import read_stream
from mirage.observe.context import RecordingScope
from mirage.types import PathSpec


@pytest.mark.asyncio
async def test_stream_records_the_virtual_path(make_acc):
    # A key named like its mount: neither m/k.txt nor /m/k.txt is virtual.
    acc = make_acc({"m/k.txt": b"hello"})
    spec = PathSpec(virtual="/m/m/k.txt",
                    directory="/m/m/",
                    vfs_path="m/k.txt")
    scope = RecordingScope()
    try:
        chunks = [c async for c in read_stream(acc, spec)]
    finally:
        scope.close()
    assert b"".join(chunks) == b"hello"
    assert [r.path for r in scope.records] == ["/m/m/k.txt"]

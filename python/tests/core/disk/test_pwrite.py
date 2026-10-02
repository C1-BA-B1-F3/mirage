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

from mirage.accessor.disk import DiskAccessor
from mirage.core.disk.pwrite import pwrite
from mirage.types import PathSpec

PATH = PathSpec(vfs_path="f.txt", virtual="/f.txt", directory="/")


@pytest.mark.asyncio
async def test_pwrite_keeps_the_bytes_outside_the_window(tmp_path):
    (tmp_path / "f.txt").write_bytes(b"hello")
    await pwrite(DiskAccessor(tmp_path), PATH, b"XY", 1)
    assert (tmp_path / "f.txt").read_bytes() == b"hXYlo"


@pytest.mark.asyncio
async def test_pwrite_past_the_end_fills_zeros_and_creates(tmp_path):
    await pwrite(DiskAccessor(tmp_path), PATH, b"z", 3)
    assert (tmp_path / "f.txt").read_bytes() == b"\0\0\0z"


@pytest.mark.asyncio
async def test_pwrite_reads_nothing_back(tmp_path):
    target = tmp_path / "f.txt"
    target.write_bytes(b"abcdef")
    target.chmod(0o200)
    try:
        await pwrite(DiskAccessor(tmp_path), PATH, b"Z", 5)
    finally:
        target.chmod(0o600)
    assert target.read_bytes() == b"abcdeZ"

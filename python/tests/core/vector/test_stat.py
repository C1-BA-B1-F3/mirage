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

from mirage.cache.index import IndexEntry
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.core.vector.read import make_read
from mirage.core.vector.readdir import make_readdir
from mirage.core.vector.stat import make_stat
from mirage.types import ContentType, FileType, PathSpec


def _ps(path: str) -> PathSpec:
    return PathSpec(virtual=path, directory=path, vfs_path=path.strip("/"))


def _stat(tree):
    readdir = make_readdir(tree)
    return make_stat(tree, readdir, make_read(tree)), readdir


@pytest.mark.asyncio
async def test_a_group_is_a_directory_of_an_existing_table(tree, accessor):
    stat, _ = _stat(tree)
    s = await stat(accessor, _ps("/animals/cat"))
    assert (s.type, s.name) == (FileType.DIRECTORY, "cat")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/zoo/cat", "/zoo/cat/1.txt", "/animals/cat/1.weird/x"])
async def test_a_missing_table_or_shape_is_absent(tree, accessor, path):
    stat, _ = _stat(tree)
    with pytest.raises(FileNotFoundError):
        await stat(accessor, _ps(path))


@pytest.mark.asyncio
async def test_a_seeded_size_answers_without_a_read(tree, accessor):
    stat, _ = _stat(tree)
    index = RAMIndexCacheStore()
    await index.put(
        "/animals/cat/1.txt",
        IndexEntry(id="1",
                   name="1.txt",
                   resource_type="stub/row_text",
                   vfs_name="1.txt",
                   size=999))
    s = await stat(accessor, _ps("/animals/cat/1.txt"), index)
    assert (s.size, s.content, accessor.reads) == (999, ContentType.TEXT, 0)


@pytest.mark.asyncio
async def test_an_unsized_entry_is_sized_by_its_read(tree, accessor):
    stat, readdir = _stat(tree)
    index = RAMIndexCacheStore()
    await readdir(accessor, _ps("/animals/cat"), index)
    s = await stat(accessor, _ps("/animals/cat/1.txt"), index)
    assert (s.size, accessor.reads) == (len(b"row 1\n"), 1)


@pytest.mark.asyncio
async def test_a_leaf_takes_its_scope_content_type(tree, accessor):
    stat, _ = _stat(tree)
    s = await stat(accessor, _ps("/animals/cat/1.png"))
    assert (s.type, s.content, s.size) == (FileType.FILE,
                                           ContentType.IMAGE_PNG, 3)

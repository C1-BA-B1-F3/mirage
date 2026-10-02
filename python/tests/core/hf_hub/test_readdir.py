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

from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.core.hf_hub.readdir import readdir
from mirage.core.hf_hub.tree import seed_index
from tests.core.hf_hub.conftest import file_row, ps, seed


@pytest.mark.asyncio
async def test_readdir_lists_the_root(loaded):
    assert await readdir(loaded, ps("")) == ["/a.txt", "/d"]


@pytest.mark.asyncio
async def test_readdir_lists_a_subdirectory(loaded):
    assert await readdir(loaded, ps("d")) == ["/d/b.txt"]


@pytest.mark.asyncio
async def test_readdir_answers_the_same_through_an_index(loaded):
    index = RAMIndexCacheStore()
    seed_index(loaded.tree, index, "")
    assert await readdir(loaded, ps(""), index) == ["/a.txt", "/d"]


@pytest.mark.asyncio
async def test_readdir_of_a_file_is_enotdir(loaded):
    with pytest.raises(NotADirectoryError):
        await readdir(loaded, ps("a.txt"))


@pytest.mark.asyncio
async def test_readdir_under_a_file_is_enotdir(loaded):
    """GNU `ls /f.txt/x` reports Not a directory, not absence."""
    with pytest.raises(NotADirectoryError):
        await readdir(loaded, ps("a.txt/x"))


@pytest.mark.asyncio
async def test_readdir_of_a_missing_path_is_enoent(loaded):
    with pytest.raises(FileNotFoundError):
        await readdir(loaded, ps("nope"))


@pytest.mark.asyncio
async def test_readdir_below_a_missing_path_is_enoent(loaded):
    """A component that does not exist is ENOENT however deep it is."""
    with pytest.raises(FileNotFoundError):
        await readdir(loaded, ps("nope/deeper"))


@pytest.mark.asyncio
async def test_readdir_of_an_empty_repo_lists_nothing(accessor):
    seed(accessor)
    assert await readdir(accessor, ps("")) == []


@pytest.mark.asyncio
async def test_readdir_under_a_mount_prefix(accessor):
    seed(accessor, file_row("a.txt"))
    assert await readdir(accessor, ps("", "/m")) == ["/m/a.txt"]

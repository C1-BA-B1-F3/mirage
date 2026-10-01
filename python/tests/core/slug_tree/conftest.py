from unittest.mock import AsyncMock

import pytest

from mirage.cache.index import IndexEntry, RAMIndexCacheStore
from mirage.core.slug_tree.rows import dir_rows
from mirage.core.slug_tree.tree import SlugTree
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key
from mirage.utils.path import gnu_basename

FILES = {"/guides/quickstart": 5, "/api/reference": 3}


def spec(virtual: str) -> PathSpec:
    return PathSpec.from_str_path(virtual, mount_key(virtual, "/knowledge"))


def file_entry(path: str, size: int) -> IndexEntry:
    return IndexEntry(id=path.strip("/"),
                      name=gnu_basename(path),
                      resource_type="file",
                      size=size)


async def load_rows(accessor, prefix):
    return dir_rows(FILES, prefix, file_entry)


@pytest.fixture
def load() -> AsyncMock:
    return AsyncMock(wraps=load_rows)


@pytest.fixture
def tree(load) -> SlugTree:
    return SlugTree(load)


@pytest.fixture
def index() -> RAMIndexCacheStore:
    return RAMIndexCacheStore()

from datetime import datetime, timedelta, timezone

import pytest

from mirage.cache.file.ram import RAMFileCacheStore
from mirage.cache.index.view import IndexView
from mirage.core.slug_tree.tree import virtual_key_for
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key

from .conftest import spec

ROOT_CHILDREN = ["/knowledge/api", "/knowledge/guides"]
GUIDES_CHILDREN = ["/knowledge/guides/quickstart"]


@pytest.mark.asyncio
async def test_resolve_classifies_files_and_folders(tree, index):
    file = await tree.resolve(
        None, spec("/knowledge/guides/quickstart"), index
    )
    folder = await tree.resolve(None, spec("/knowledge/guides"), index)
    root = await tree.resolve(None, spec("/knowledge"), index)

    assert not file.is_dir
    assert file.entry.id == "guides/quickstart"
    assert folder.is_dir
    assert folder.virtual_key == "/knowledge/guides"
    assert root.is_dir
    with pytest.raises(FileNotFoundError):
        await tree.resolve(None, spec("/knowledge/missing"), index)


def test_virtual_key_for_honors_prefix_and_patterns():
    assert (
        virtual_key_for(spec("/knowledge/guides/quickstart"))
        == "/knowledge/guides/quickstart"
    )
    assert virtual_key_for(spec("/knowledge")) == "/knowledge"
    assert (
        virtual_key_for(
            PathSpec(
                vfs_path="guides/quickstart",
                virtual="/guides/quickstart",
                directory="/guides",
            )
        )
        == "/guides/quickstart"
    )
    assert (
        virtual_key_for(
            PathSpec(
                vfs_path=mount_key("/knowledge/guides/*.md", "/knowledge"),
                virtual="/knowledge/guides/*.md",
                directory="/knowledge/guides",
                pattern="*.md",
            )
        )
        == "/knowledge/guides"
    )


@pytest.mark.asyncio
async def test_ensure_fetches_only_while_the_root_is_unlisted(
    tree, load, index
):
    assert await tree.ensure(None, index, "/knowledge/") is not None
    assert await tree.ensure(None, index, "/knowledge/") is None
    assert load.await_count == 1


@pytest.mark.asyncio
async def test_readdir_lists_folders_and_refuses_the_rest(tree, index):
    assert await tree.readdir(None, spec("/knowledge"), index) == ROOT_CHILDREN
    assert (
        await tree.readdir(None, spec("/knowledge/guides"), index)
        == GUIDES_CHILDREN
    )
    with pytest.raises(NotADirectoryError):
        await tree.readdir(None, spec("/knowledge/guides/quickstart"), index)
    with pytest.raises(FileNotFoundError):
        await tree.readdir(None, spec("/knowledge/nope"), index)


@pytest.mark.asyncio
async def test_an_expired_folder_under_a_live_root_refills(tree, index):
    # The tree is written whole, so an expired folder listing means the
    # tree aged out, not that the folder is gone: refill and answer.
    await tree.readdir(None, spec("/knowledge/guides"), index)
    await index.set_dir(
        "/knowledge/guides",
        [],
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert (
        await tree.readdir(None, spec("/knowledge/guides"), index)
        == GUIDES_CHILDREN
    )


async def _refuse_listing(_folder: str, _version: str | None) -> bool:
    return False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "folder, children",
    [("/knowledge", ROOT_CHILDREN), ("/knowledge/guides", GUIDES_CHILDREN)],
)
async def test_a_refused_listing_refills_once_and_answers(
    tree, load, index, folder, children
):
    # A read outside any command under fresh has every cached listing
    # refused; answering ENOENT would fail every such ls of a subfolder.
    view = IndexView(
        index,
        RAMFileCacheStore(),
        "/knowledge",
        lambda _key: True,
        may_serve_listing=_refuse_listing,
    )
    for _ in range(2):
        load.reset_mock()
        assert await tree.readdir(None, spec(folder), view) == children
        assert load.await_count == 1


@pytest.mark.asyncio
async def test_refilled_rows_respect_index_ownership(tree, index):
    view = IndexView(
        index,
        RAMFileCacheStore(),
        "/knowledge",
        lambda key: not key.startswith("/knowledge/guides"),
    )
    for _ in range(2):
        assert await tree.readdir(None, spec("/knowledge"), view) == [
            "/knowledge/api"
        ]


@pytest.mark.asyncio
async def test_walk_honors_root_prefix_and_depth(tree, index):
    assert await tree.walk(
        None, spec("/knowledge"), index, include_root=True, strip_prefix=True
    ) == ["/", "/api", "/api/reference", "/guides", "/guides/quickstart"]
    assert (
        await tree.walk(None, spec("/knowledge"), index, maxdepth=1)
        == ROOT_CHILDREN
    )


@pytest.mark.asyncio
async def test_walk_of_a_missing_path_raises_unless_ignored(tree, index):
    with pytest.raises(FileNotFoundError):
        await tree.walk(None, spec("/knowledge/missing"), index)
    assert (
        await tree.walk(
            None, spec("/knowledge/missing"), index, ignore_missing=True
        )
        == []
    )

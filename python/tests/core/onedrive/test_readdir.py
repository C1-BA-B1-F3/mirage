import pytest
from aioresponses import aioresponses

from mirage.accessor.onedrive import OneDriveAccessor, OneDriveConfig
from mirage.cache.index import RAMIndexCacheStore
from mirage.core.onedrive.readdir import readdir
from mirage.types import PathSpec


def _accessor(**kw) -> OneDriveAccessor:
    return OneDriveAccessor(OneDriveConfig(access_token="tok", **kw))


_BASE = "https://graph.microsoft.com/v1.0/me/drive"


@pytest.mark.asyncio
async def test_readdir_root_lists_children():
    index = RAMIndexCacheStore()
    with aioresponses() as m:
        m.get(
            _BASE + "/root/children",
            payload={
                "value": [
                    {"id": "1", "name": "a.txt", "size": 10, "file": {}},
                    {"id": "2", "name": "Docs", "folder": {"childCount": 0}},
                ]
            },
        )
        names = await readdir(_accessor(), PathSpec.from_str_path("/"), index)
    assert names == ["/Docs", "/a.txt"]


@pytest.mark.asyncio
async def test_readdir_folder_records_file_and_folder_entries():
    index = RAMIndexCacheStore()
    with aioresponses() as m:
        m.get(
            _BASE + "/root:/Docs:/children",
            payload={
                "value": [
                    {"id": "9", "name": "report.docx", "size": 55, "file": {}}
                ]
            },
        )
        names = await readdir(
            _accessor(), PathSpec.from_str_path("/Docs"), index
        )
    assert names == ["/Docs/report.docx"]
    lookup = await index.get("/Docs/report.docx")
    assert lookup.entry.resource_type == "file"
    assert lookup.entry.size == 55


@pytest.mark.asyncio
async def test_readdir_of_file_raises_not_a_directory():
    index = RAMIndexCacheStore()
    with aioresponses() as m:
        m.get(
            _BASE + "/root:/a.txt:/children",
            status=404,
            payload={"error": {"code": "itemNotFound", "message": "x"}},
        )
        m.get(
            _BASE + "/root:/a.txt",
            payload={"id": "1", "name": "a.txt", "size": 3, "file": {}},
        )
        with pytest.raises(NotADirectoryError):
            await readdir(_accessor(), PathSpec.from_str_path("/a.txt"), index)


@pytest.mark.asyncio
async def test_readdir_under_a_file_is_not_a_directory():
    # Graph 404s the children of `/a.txt/x` exactly as it does those of a
    # name that is simply absent, so only the ancestor walk can tell GNU's
    # "Not a directory" from "No such file or directory".
    index = RAMIndexCacheStore()
    missing = {"error": {"code": "itemNotFound", "message": "x"}}
    with aioresponses() as m:
        m.get(_BASE + "/root:/a.txt/x:/children", status=404, payload=missing)
        # The walk asks each component as a directory and then as a file, so
        # every probe URL answers more than once.
        m.get(
            _BASE + "/root:/a.txt/x", status=404, payload=missing, repeat=True
        )
        m.get(
            _BASE + "/root:/a.txt",
            payload={"id": "1", "name": "a.txt", "size": 3, "file": {}},
            repeat=True,
        )
        with pytest.raises(NotADirectoryError):
            await readdir(
                _accessor(), PathSpec.from_str_path("/a.txt/x"), index
            )


@pytest.mark.asyncio
async def test_readdir_of_a_missing_path_is_not_found():
    index = RAMIndexCacheStore()
    missing = {"error": {"code": "itemNotFound", "message": "x"}}
    with aioresponses() as m:
        m.get(
            _BASE + "/root:/nope/deeper:/children", status=404, payload=missing
        )
        m.get(
            _BASE + "/root:/nope/deeper",
            status=404,
            payload=missing,
            repeat=True,
        )
        m.get(_BASE + "/root:/nope", status=404, payload=missing, repeat=True)
        with pytest.raises(FileNotFoundError):
            await readdir(
                _accessor(), PathSpec.from_str_path("/nope/deeper"), index
            )


@pytest.mark.asyncio
async def test_readdir_paginates_nextlink():
    index = RAMIndexCacheStore()
    page2 = _BASE + "/root/children?$skiptoken=x"
    with aioresponses() as m:
        m.get(
            _BASE + "/root/children",
            payload={
                "value": [{"id": "1", "name": "a.txt", "file": {}}],
                "@odata.nextLink": page2,
            },
        )
        m.get(
            page2,
            payload={"value": [{"id": "2", "name": "b.txt", "file": {}}]},
        )
        names = await readdir(_accessor(), PathSpec.from_str_path("/"), index)
    assert names == ["/a.txt", "/b.txt"]


@pytest.mark.asyncio
async def test_readdir_stores_remote_time_for_files():
    index = RAMIndexCacheStore()
    with aioresponses() as m:
        m.get(
            _BASE + "/root/children",
            payload={
                "value": [
                    {
                        "id": "1",
                        "name": "a.txt",
                        "size": 10,
                        "file": {},
                        "lastModifiedDateTime": "2026-06-19T09:28:00Z",
                    }
                ]
            },
        )
        await readdir(_accessor(), PathSpec.from_str_path("/"), index)
    lookup = await index.get("/a.txt")
    assert lookup.entry.remote_time == "2026-06-19T09:28:00Z"


@pytest.mark.asyncio
async def test_readdir_stores_remote_time_for_folders():
    index = RAMIndexCacheStore()
    with aioresponses() as m:
        m.get(
            _BASE + "/root/children",
            payload={
                "value": [
                    {
                        "id": "2",
                        "name": "Docs",
                        "folder": {"childCount": 3},
                        "size": 5000,
                        "lastModifiedDateTime": "2026-05-28T02:10:00Z",
                    }
                ]
            },
        )
        await readdir(_accessor(), PathSpec.from_str_path("/"), index)
    lookup = await index.get("/Docs")
    assert lookup.entry.remote_time == "2026-05-28T02:10:00Z"
    # Graph folder size is aggregate storage metadata, never a rendered
    # content length: it lives in extra, not in the entry size.
    assert lookup.entry.size is None
    assert lookup.entry.extra["size_bytes"] == 5000
    assert lookup.entry.extra["child_count"] == 3

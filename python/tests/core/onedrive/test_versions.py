import pytest
from aioresponses import aioresponses

from mirage.accessor.onedrive import OneDriveAccessor, OneDriveConfig
from mirage.core.onedrive.versions import list_versions
from mirage.types import PathSpec


@pytest.mark.asyncio
async def test_list_versions_lists_the_item_under_the_key_prefix():
    versions = [{"id": "2.0"}, {"id": "1.0"}]
    accessor = OneDriveAccessor(
        OneDriveConfig(access_token="tok", key_prefix="team")
    )
    with aioresponses() as m:
        m.get(
            "https://graph.microsoft.com/v1.0/me/drive"
            "/root:/team/a.txt:/versions",
            payload={"value": versions},
        )
        found = await list_versions(
            accessor, PathSpec.from_str_path("/od/a.txt", "a.txt")
        )
    assert found == versions

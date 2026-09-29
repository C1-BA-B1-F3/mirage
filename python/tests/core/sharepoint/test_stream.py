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

import re

import pytest
from aioresponses import aioresponses

from mirage.accessor.sharepoint import SharePointAccessor, SharePointConfig
from mirage.core.sharepoint.stream import read_stream
from mirage.observe.context import RecordingScope
from mirage.types import PathSpec

_BASE = "https://graph.microsoft.com/v1.0"
_SITE_ID = "tenant.sharepoint.com,site-guid,web-guid"
_DRIVE_ID = "b!driveXYZ"
# The site is named like the mount, so vfs_path "m/Documents/k.txt" sits
# under the virtual "/m/m/Documents/k.txt".
_SPEC = PathSpec(virtual="/m/m/Documents/k.txt",
                 directory="/m/m/Documents/",
                 vfs_path="m/Documents/k.txt")


def _accessor() -> SharePointAccessor:
    accessor = SharePointAccessor(SharePointConfig(access_token="tok"))
    accessor.site_cache["m"] = _SITE_ID
    accessor.drive_cache[(_SITE_ID, "Documents")] = _DRIVE_ID
    return accessor


@pytest.mark.asyncio
async def test_recorded_stream_names_the_virtual_path():
    scope = RecordingScope()
    try:
        with aioresponses() as m:
            m.get(re.compile(r".*/root:/k\.txt(\?.*)?$"),
                  payload={
                      "id": "01",
                      "cTag": "c1",
                      "versions": []
                  })
            m.get(f"{_BASE}/drives/{_DRIVE_ID}/root:/k.txt:/content",
                  body=b"bytes")
            chunks = [c async for c in read_stream(_accessor(), _SPEC)]
    finally:
        scope.close()
    assert b"".join(chunks) == b"bytes"
    assert [r.path for r in scope.records] == ["/m/m/Documents/k.txt"]

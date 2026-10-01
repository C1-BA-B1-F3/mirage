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
from aioresponses import aioresponses
from yarl import URL

from mirage.core.discord.files import download_file, file_blob_name
from mirage.utils.sanitize import NAME_MAX_BYTES, byte_len

BODY = b"0123456789"
CDN_URL = "https://cdn.example/a.csv"
BLOB_ID = "1234567890123456789"
KEY = "filename"


async def _download(
    status: int, body: bytes, offset: int, size: int | None
) -> tuple[bytes, dict]:
    with aioresponses() as m:
        m.get(CDN_URL, status=status, body=body)
        data = await download_file(CDN_URL, offset, size)
        sent = m.requests[("GET", URL(CDN_URL))][0].kwargs
    return data, sent


@pytest.mark.asyncio
async def test_the_window_is_sent_as_a_range_header():
    _, sent = await _download(206, b"234", 2, 3)

    assert sent["headers"]["Range"] == "bytes=2-4"


@pytest.mark.asyncio
async def test_a_206_body_is_trusted_as_the_window():
    data, _ = await _download(206, b"234", 2, 3)

    assert data == b"234"


@pytest.mark.asyncio
async def test_a_200_is_sliced_because_the_cdn_ignored_the_range():
    """A CDN may legally answer 200 with the whole file to a Range
    request. Before this was handled the caller got every byte for what
    it asked to be a window."""
    data, _ = await _download(200, BODY, 2, 3)

    assert data == b"234"


@pytest.mark.asyncio
async def test_no_window_sends_no_header_and_reads_whole():
    data, sent = await _download(200, BODY, 0, None)

    assert data == BODY
    assert "Range" not in (sent["headers"] or {})


@pytest.mark.parametrize(
    "raw_name,expected_tail",
    [
        ("会議" * 100 + ".txt", ".txt"),
        ("会議" * 100, ""),
    ],
)
def test_a_long_filename_fits_name_max_and_keeps_id_and_extension(
    raw_name, expected_tail
):
    """The stem is the only part that gives.

    A trimmed id stops addressing the file and a trimmed extension changes
    its type, so both are spent before the stem gets its budget.
    """
    name = file_blob_name({KEY: raw_name, "id": BLOB_ID})

    assert byte_len(name) <= NAME_MAX_BYTES
    assert name.endswith(f"{BLOB_ID}{expected_tail}")
    assert "�" not in name

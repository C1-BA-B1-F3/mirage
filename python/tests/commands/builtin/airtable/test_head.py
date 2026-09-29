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

from mirage import Workspace
from mirage.core.airtable.config import AirtableConfig
from mirage.vfs.airtable import AirtableVFS
from tests.fixtures.airtable_api import TOKEN

RECORDS = ("/at/bases/Product_Roadmap__appRoadmapBase001/"
           "Features__tblFeatures000001/records.jsonl")


def _ws() -> Workspace:
    return Workspace({
        "/at/":
        AirtableVFS(
            AirtableConfig(token=TOKEN,
                           requests_per_second=10_000.0,
                           max_read_records=5))
    })


@pytest.mark.asyncio
async def test_head_pushes_its_line_count_into_max_records(airtable_api):
    ws = _ws()
    try:
        result = await ws.shell(f"head -n 2 {RECORDS}")
        assert result.exit_code == 0
        assert len((await result.stdout_str()).splitlines()) == 2
    finally:
        await ws.close()
    calls = airtable_api.record_calls()
    assert [c["maxRecords"] for c in calls] == ["2"]


@pytest.mark.asyncio
async def test_head_default_is_ten_and_respects_the_cap(airtable_api):
    ws = _ws()
    try:
        result = await ws.shell(f"head {RECORDS}")
    finally:
        await ws.close()
    # 10 lines asked of a 7-record table under a cap of 5: the full answer
    # would exceed the cap, so it is refused rather than truncated
    assert result.exit_code == 1
    assert await result.stderr_str(
    ) == f"head: error reading '{RECORDS}': File too large\n"


@pytest.mark.asyncio
async def test_head_by_bytes_reads_the_file(airtable_api):
    ws = _ws()
    try:
        result = await ws.shell(f"head -c 12 {RECORDS}")
    finally:
        await ws.close()
    # no line count to push down: a byte window needs the whole file,
    # which the cap refuses
    assert result.exit_code == 1

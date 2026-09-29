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

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from aioresponses import aioresponses

from mirage.core.airtable.client import (RETRY, WRITE_RETRY, create_comment,
                                         create_records, delete_records,
                                         get_record, list_bases, list_comments,
                                         list_records, list_tables,
                                         update_records)
from mirage.core.airtable.errors import AirtableAPIError
from tests.fixtures.airtable_api import (DONE_FORMULA, FEATURES,
                                         MODEL_NOT_FOUND, OPS, ROADMAP,
                                         FakeAirtable, make_accessor)

FIRST = "rec00000000000001"


async def _drain(batches: AsyncIterator[list[dict[str, Any]]]) -> list[int]:
    return [len(batch) async for batch in batches]


def _names(n: int) -> list[dict[str, Any]]:
    return [{"Name": f"New {i}"} for i in range(1, n + 1)]


def test_the_retry_policy_vetoes_only_the_billing_cap():
    assert RETRY.retryable is not None
    assert RETRY.retryable(429, '{"error": {"type": "RATE_LIMIT_REACHED"}}')
    assert not RETRY.retryable(
        429, '{"error": {"type": "PUBLIC_API_BILLING_LIMIT_EXCEEDED"}}')
    assert RETRY.min_delays[429] == 30.0


@pytest.mark.asyncio
async def test_list_bases_honors_the_configured_scope(airtable_api):
    everything = await list_bases(make_accessor())
    assert [b["id"] for b in everything] == [ROADMAP, OPS]
    scoped = await list_bases(make_accessor(base_ids=[OPS]))
    assert [b["id"] for b in scoped] == [OPS]


@pytest.mark.asyncio
async def test_a_bad_token_names_the_call_and_the_type(airtable_api):
    with pytest.raises(AirtableAPIError) as exc:
        await list_bases(make_accessor(token="wrong"))
    assert exc.value.status == 401
    assert exc.value.error_type == "AUTHENTICATION_REQUIRED"
    assert str(
        exc.value) == ("Airtable API error (GET /meta/bases): HTTP 401: "
                       "AUTHENTICATION_REQUIRED: Authentication required")


@pytest.mark.asyncio
async def test_list_tables_returns_the_schema(airtable_api):
    tables = await list_tables(make_accessor(), ROADMAP)
    assert [t["id"] for t in tables] == [FEATURES]


@pytest.mark.asyncio
async def test_list_records_pages_through_every_offset(airtable_api):
    records = await list_records(make_accessor(), ROADMAP, FEATURES)
    assert len(records) == 7
    calls = airtable_api.record_calls()
    assert len(calls) == 3
    assert "offset" not in calls[0]
    assert calls[1]["offset"] == "itrFakeIterator01/3"
    assert all(c["pageSize"] == "100" for c in calls)


@pytest.mark.asyncio
async def test_max_records_rides_the_wire_and_the_collector(airtable_api):
    records = await list_records(make_accessor(),
                                 ROADMAP,
                                 FEATURES,
                                 max_records=2)
    assert [r["id"]
            for r in records] == ["rec00000000000001", "rec00000000000002"]
    assert airtable_api.record_calls()[0]["maxRecords"] == "2"


@pytest.mark.asyncio
async def test_a_view_filters_through_the_api(airtable_api):
    records = await list_records(make_accessor(),
                                 ROADMAP,
                                 FEATURES,
                                 view="viwDone0000000001")
    assert [r["fields"]["Priority"] for r in records] == [1, 3, 5, 7]


@pytest.mark.asyncio
async def test_a_formula_rides_the_wire(airtable_api):
    records = await list_records(make_accessor(),
                                 ROADMAP,
                                 FEATURES,
                                 formula=DONE_FORMULA)
    assert [r["fields"]["Priority"] for r in records] == [1, 3, 5, 7]
    assert airtable_api.record_calls()[0]["filterByFormula"] == DONE_FORMULA


@pytest.mark.asyncio
async def test_a_table_name_is_as_good_as_its_id(airtable_api):
    records = await list_records(make_accessor(), ROADMAP, "Features")
    assert len(records) == 7


@pytest.mark.asyncio
async def test_get_record_reads_one_by_id(airtable_api):
    record = await get_record(make_accessor(), ROADMAP, FEATURES, FIRST)
    assert record["fields"]["Name"] == "Feature 1"
    with pytest.raises(AirtableAPIError) as exc:
        await get_record(make_accessor(), ROADMAP, FEATURES,
                         "recZZZZZZZZZZZZZZ")
    assert exc.value.status == 403
    assert exc.value.not_found
    assert str(exc.value) == (
        f"Airtable API error (GET /{ROADMAP}/{FEATURES}/recZZZZZZZZZZZZZZ): "
        f"HTTP 403: INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND: {MODEL_NOT_FOUND}")


@pytest.mark.asyncio
async def test_creates_go_ten_to_a_request(airtable_api):
    sizes = await _drain(
        create_records(make_accessor(), ROADMAP, FEATURES, _names(23)))
    assert sizes == [10, 10, 3]
    bodies = [params["body"] for _, params in airtable_api.write_calls()]
    assert [len(b["records"]) for b in bodies] == [10, 10, 3]
    assert bodies[0]["records"][0] == {"fields": {"Name": "New 1"}}
    assert all("typecast" not in b for b in bodies)
    assert len(airtable_api.records[FEATURES]) == 30


@pytest.mark.asyncio
async def test_typecast_is_a_body_key(airtable_api):
    await _drain(
        create_records(make_accessor(),
                       ROADMAP,
                       FEATURES,
                       _names(1),
                       typecast=True))
    await _drain(
        update_records(make_accessor(),
                       ROADMAP,
                       FEATURES, [(FIRST, {
                           "Priority": 9
                       })],
                       typecast=True))
    assert [p["body"]["typecast"]
            for _, p in airtable_api.write_calls()] == [True, True]


@pytest.mark.asyncio
async def test_updates_patch_ten_to_a_request(airtable_api):
    ids = [r["id"] for r in airtable_api.records[FEATURES]]
    updates = [(record_id, {"Priority": 0}) for record_id in ids * 2][:12]
    sizes = await _drain(
        update_records(make_accessor(), ROADMAP, FEATURES, updates))
    assert sizes == [10, 2]
    calls = airtable_api.write_calls()
    assert [kind for kind, _ in calls] == ["update", "update"]
    assert calls[0][1]["body"]["records"][0] == {
        "id": FIRST,
        "fields": {
            "Priority": 0
        }
    }
    assert airtable_api.records[FEATURES][0]["fields"]["Name"] == "Feature 1"


@pytest.mark.asyncio
async def test_deletes_ride_records_brackets_ten_to_a_request(airtable_api):
    await _drain(create_records(make_accessor(), ROADMAP, FEATURES, _names(5)))
    ids = [r["id"] for r in airtable_api.records[FEATURES]]
    sizes = await _drain(
        delete_records(make_accessor(), ROADMAP, FEATURES, ids))
    assert sizes == [10, 2]
    deletes = [p for kind, p in airtable_api.write_calls() if kind == "delete"]
    assert [d["records"] for d in deletes] == [ids[:10], ids[10:]]
    assert airtable_api.records[FEATURES] == []


@pytest.mark.asyncio
async def test_a_failed_batch_stops_after_what_landed(airtable_api):
    rows = _names(10) + [{"Nope": 1}] + _names(2)
    landed: list[int] = []
    with pytest.raises(AirtableAPIError) as exc:
        async for batch in create_records(make_accessor(), ROADMAP, FEATURES,
                                          rows):
            landed.append(len(batch))
    assert landed == [10]
    assert exc.value.error_type == "UNKNOWN_FIELD_NAME"
    assert len(airtable_api.write_calls()) == 2
    assert len(airtable_api.records[FEATURES]) == 17


@pytest.mark.asyncio
async def test_a_write_never_retries_a_503():
    fake = FakeAirtable(faults={1: (503, "SERVICE_UNAVAILABLE")})
    with aioresponses() as m:
        fake.install(m)
        with pytest.raises(AirtableAPIError) as exc:
            await _drain(
                create_records(make_accessor(), ROADMAP, FEATURES, _names(1)))
    assert exc.value.status == 503
    assert len(fake.write_calls()) == 1


@pytest.mark.asyncio
async def test_a_write_waits_out_a_429_and_retries_it(monkeypatch):
    waits: list[float] = []

    async def _no_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    fake = FakeAirtable(faults={1: (429, "RATE_LIMIT_REACHED")})
    with aioresponses() as m:
        fake.install(m)
        sizes = await _drain(
            create_records(make_accessor(), ROADMAP, FEATURES, _names(1)))
    assert sizes == [1]
    assert len(fake.write_calls()) == 2
    assert waits == [30.0]


def test_the_write_policy_retries_only_the_429():
    assert WRITE_RETRY.statuses == frozenset({429})
    assert WRITE_RETRY.min_delays[429] == 30.0
    assert WRITE_RETRY.retryable is not None
    assert not WRITE_RETRY.retryable(
        429, '{"error": {"type": "PUBLIC_API_BILLING_LIMIT_EXCEEDED"}}')
    assert {502, 503} <= RETRY.statuses


@pytest.mark.asyncio
async def test_comments_page_newest_first(airtable_api):
    accessor = make_accessor()
    for n in range(3):
        await create_comment(accessor, ROADMAP, FEATURES, FIRST, f"note {n}")
    comments = await list_comments(accessor, ROADMAP, FEATURES, FIRST)
    assert [c["text"] for c in comments
            ] == ["note 2", "note 1", "note 0", "Shipped it.", "Looks good."]
    pages = [p for kind, p in airtable_api.calls if kind == "comments"]
    assert len(pages) == 2
    assert pages[1]["offset"] == "itrFakeIterator01/3"


@pytest.mark.asyncio
async def test_create_comment_posts_only_the_text(airtable_api):
    made = await create_comment(make_accessor(), ROADMAP, FEATURES, FIRST,
                                "hello")
    assert made["text"] == "hello"
    assert made["author"]["email"] == "ada@example.com"
    assert airtable_api.write_calls()[0][1]["body"] == {"text": "hello"}


@pytest.mark.asyncio
async def test_every_request_paces_under_its_base(airtable_api, monkeypatch):
    accessor = make_accessor()
    keys: list[str] = []
    acquire = accessor.limiter.acquire

    async def _spy(key: str) -> None:
        keys.append(key)
        await acquire(key)

    monkeypatch.setattr(accessor.limiter, "acquire", _spy)
    await _drain(create_records(accessor, ROADMAP, FEATURES, _names(11)))
    await _drain(
        update_records(accessor, ROADMAP, FEATURES, [(FIRST, {
            "Priority": 2
        })]))
    await _drain(delete_records(accessor, ROADMAP, FEATURES, [FIRST]))
    await get_record(accessor, ROADMAP, FEATURES, "rec00000000000002")
    await create_comment(accessor, ROADMAP, FEATURES, "rec00000000000002", "x")
    await list_comments(accessor, ROADMAP, FEATURES, "rec00000000000002")
    assert keys == [ROADMAP] * 7

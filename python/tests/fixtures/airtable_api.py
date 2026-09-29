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

import inspect
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, unquote

import pytest
from aiohttp import ClientResponse
from aioresponses import CallbackResult, aioresponses
from aioresponses import core as aioresponses_core

from mirage.accessor.airtable import AirtableAccessor
from mirage.core.airtable.config import AirtableConfig


class _PatchedClientResponse(ClientResponse):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stream_writer", SimpleNamespace(output_size=0))
        super().__init__(*args, **kwargs)


if "stream_writer" in inspect.signature(ClientResponse.__init__).parameters:
    aioresponses_core.ClientResponse = _PatchedClientResponse

API = "https://api.airtable.com/v0"
TOKEN = "patTest0000000001.secret"
ROADMAP = "appRoadmapBase001"
OPS = "appOpsFinance0001"
FEATURES = "tblFeatures000001"
BUDGET = "tblBudget00000001"
GRID = "viwGrid0000000001"
DONE = "viwDone0000000001"
DONE_FORMULA = "{Status}='Done'"
MAX_BATCH = 10

MODEL_NOT_FOUND = ("Invalid permissions, or the requested model was not "
                   "found. Check that both your user and your token have the "
                   "required permissions, and that the model names and/or "
                   "ids are correct.")

VIEW_ID = re.compile(r"viw[A-Za-z0-9]{14}")
ADA = {"id": "usrAda0000000001", "email": "ada@example.com", "name": "Ada"}
BEN = {"id": "usrBen0000000002", "email": "ben@example.com", "name": "Ben"}
WRITER = ADA
WRITE_KINDS = frozenset({"create", "update", "delete", "comment"})
BATCH_MESSAGES = {
    "create": ("You must provide an array of up to 10 record objects, each "
               'with a "fields" object for cell values.'),
    "update": ("You must provide an array of up to 10 record objects, each "
               'with an "id" ID field and a "fields" object for cell '
               "values."),
    "delete":
    "You must provide an array of up to 10 record IDs.",
}


def _record(n: int, **fields: Any) -> dict[str, Any]:
    return {
        "id": f"rec{n:014d}",
        "createdTime": f"2026-01-{n:02d}T09:00:00.000Z",
        "fields": fields,
    }


def _features() -> list[dict[str, Any]]:
    rows = []
    for n in range(1, 8):
        cells: dict[str, Any] = {"Name": f"Feature {n}", "Priority": n}
        if n % 2:
            cells["Status"] = "Done"
        rows.append(_record(n, **cells))
    return rows


def _is_done(record: dict[str, Any]) -> bool:
    return record["fields"].get("Status") == "Done"


def _comment(n: int, text: str, author: dict[str, str]) -> dict[str, Any]:
    return {
        "id": f"com{n:014d}",
        "author": author,
        "text": text,
        "createdTime": f"2026-01-{n:02d}T10:00:00.000Z",
        "lastUpdatedTime": None,
    }


def _segments(url: Any) -> list[str]:
    tail = str(url).split(API + "/")[1].split("?")[0]
    return [unquote(part) for part in tail.split("/")]


def _error(status: int, kind: str, message: str | None = None) -> Any:
    body: dict[str, Any] = {"type": kind}
    if message is not None:
        body["message"] = message
    return CallbackResult(status=status, payload={"error": body})


def _model_not_found() -> Any:
    return _error(403, "INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND",
                  MODEL_NOT_FOUND)


@dataclass
class FakeAirtable:
    """An in-process Airtable API for aioresponses, paged like the real one.

    ``page_cap`` keeps pages short so a handful of records still spans
    several ``offset`` round trips.
    """

    bases: list[dict[str, Any]] = field(default_factory=lambda: [
        {
            "id": ROADMAP,
            "name": "Product Roadmap",
            "permissionLevel": "create"
        },
        {
            "id": OPS,
            "name": "Ops / Finance ✓",
            "permissionLevel": "read"
        },
    ])
    tables: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            ROADMAP: [{
                "id":
                FEATURES,
                "name":
                "Features",
                "primaryFieldId":
                "fldName000000001",
                "fields": [
                    {
                        "id": "fldName000000001",
                        "name": "Name",
                        "type": "singleLineText"
                    },
                    {
                        "id": "fldStatus0000001",
                        "name": "Status",
                        "type": "singleSelect",
                        "options": {
                            "choices": [{
                                "id": "selDone000000001",
                                "name": "Done"
                            }]
                        },
                    },
                    {
                        "id": "fldPriority00001",
                        "name": "Priority",
                        "type": "number",
                        "options": {
                            "precision": 0
                        }
                    },
                ],
                "views": [
                    {
                        "id": GRID,
                        "name": "Grid view",
                        "type": "grid"
                    },
                    {
                        "id": DONE,
                        "name": "Done / shipped",
                        "type": "grid"
                    },
                ],
            }],
            OPS: [{
                "id":
                BUDGET,
                "name":
                "Q3 / Budget",
                "primaryFieldId":
                "fldLine000000001",
                "fields": [{
                    "id": "fldLine000000001",
                    "name": "Line",
                    "type": "singleLineText"
                }],
                "views": [],
            }],
        })
    records: dict[str,
                  list[dict[str,
                            Any]]] = field(default_factory=lambda: {
                                FEATURES: _features(),
                                BUDGET: [_record(1, Line="Rent")],
                            })
    views: dict[str, Callable[[dict[str, Any]],
                              bool]] = field(default_factory=lambda: {
                                  GRID: lambda record: True,
                                  DONE: _is_done
                              })
    formulas: dict[str, Callable[[dict[str, Any]], bool]] = field(
        default_factory=lambda: {DONE_FORMULA: _is_done})
    comments: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "rec00000000000001": [
                _comment(2, "Shipped it.", ADA),
                _comment(1, "Looks good.", BEN),
            ]
        })
    faults: dict[int, tuple[int, str]] = field(default_factory=dict)
    page_cap: int = 3
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    writes: int = 0
    minted: int = 0

    def _authorized(self, kwargs: dict[str, Any]) -> bool:
        headers = kwargs.get("headers") or {}
        return headers.get("Authorization") == f"Bearer {TOKEN}"

    def _table(self, base_id: str, ref: str) -> dict[str, Any] | None:
        tables = self.tables.get(base_id, [])
        return (next((t for t in tables if t["id"] == ref), None) or next(
            (t for t in tables if t["name"] == ref), None))

    def _fault(self) -> Any:
        self.writes += 1
        fault = self.faults.get(self.writes)
        return None if fault is None else _error(fault[0], fault[1])

    def _bases(self, url: Any, **kwargs: Any) -> Any:
        self.calls.append(("bases", dict(kwargs.get("params") or {})))
        if not self._authorized(kwargs):
            return _error(401, "AUTHENTICATION_REQUIRED",
                          "Authentication required")
        return CallbackResult(payload={"bases": self.bases})

    def _tables(self, url: Any, **kwargs: Any) -> Any:
        base_id = str(url).split("/meta/bases/")[1].split("/")[0]
        self.calls.append(("tables", {"base": base_id}))
        if base_id not in self.tables:
            return _model_not_found()
        return CallbackResult(payload={"tables": self.tables[base_id]})

    def _records(self, url: Any, **kwargs: Any) -> Any:
        params = {k: str(v) for k, v in (kwargs.get("params") or {}).items()}
        base_id, ref = _segments(url)[:2]
        table = self._table(base_id, ref)
        self.calls.append(("records", {**params, "table": ref}))
        if table is None:
            return _model_not_found()
        pool = self.records[table["id"]]
        view = params.get("view")
        if view is not None:
            keep = self.views.get(view)
            if keep is None:
                kind = ("VIEW_ID_NOT_FOUND"
                        if VIEW_ID.fullmatch(view) else "VIEW_NAME_NOT_FOUND")
                return _error(422, kind, f"View {view} not found")
            pool = [r for r in pool if keep(r)]
        formula = params.get("filterByFormula")
        if formula is not None:
            test = self.formulas.get(formula)
            if test is None:
                return _error(422, "INVALID_FILTER_BY_FORMULA",
                              "The formula for filtering records is invalid")
            pool = [r for r in pool if test(r)]
        if "maxRecords" in params:
            pool = pool[:int(params["maxRecords"])]
        return self._paged(pool, "records", params, trailing=False)

    def _paged(self, pool: list[dict[str, Any]], key: str,
               params: dict[str, str], *, trailing: bool) -> Any:
        size = min(int(params.get("pageSize", 100)), self.page_cap)
        start = int(
            params["offset"].split("/")[1]) if "offset" in params else 0
        body: dict[str, Any] = {key: pool[start:start + size]}
        if start + size < len(pool):
            body["offset"] = f"itrFakeIterator01/{start + size}"
        elif trailing:
            body["offset"] = None
        return CallbackResult(payload=body)

    def _record(self, url: Any, **kwargs: Any) -> Any:
        base_id, ref, record_id = _segments(url)[:3]
        self.calls.append(("record", {"table": ref, "record": record_id}))
        found = self._find(base_id, ref, record_id)
        if isinstance(found, CallbackResult):
            return found
        return CallbackResult(payload=found)

    def _find(self, base_id: str, ref: str, record_id: str) -> Any:
        table = self._table(base_id, ref)
        if table is None:
            return _model_not_found()
        for record in self.records[table["id"]]:
            if record["id"] == record_id:
                return record
        return _model_not_found()

    def _cells(self, table: dict[str, Any], before: dict[str, Any],
               cells: Any) -> Any:
        if not isinstance(cells, dict):
            return None
        names = {f["name"] for f in table["fields"]}
        out = dict(before)
        for name, value in cells.items():
            if name not in names:
                return _error(422, "UNKNOWN_FIELD_NAME",
                              f'Unknown field name: "{name}"')
            if value is None:
                out.pop(name, None)
            else:
                out[name] = value
        return out

    def _batch(self, url: Any, kind: str, keys: frozenset[str],
               **kwargs: Any) -> Any:
        base_id, ref = _segments(url)[:2]
        body = kwargs.get("json")
        self.calls.append((kind, {"table": ref, "body": body}))
        fault = self._fault()
        if fault is not None:
            return fault
        table = self._table(base_id, ref)
        if table is None:
            return _model_not_found()
        if (not isinstance(body, dict) or set(body) - {"records", "typecast"}
                or not isinstance(body.get("typecast", False), bool)):
            return _error(422, "INVALID_REQUEST_UNKNOWN",
                          "Invalid request: parameter validation failed.")
        rows = body.get("records")
        if (not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BATCH
                or any(not isinstance(r, dict) or set(r) != keys
                       for r in rows)):
            return _error(422, "INVALID_RECORDS", BATCH_MESSAGES[kind])
        return table, rows

    def _create(self, url: Any, **kwargs: Any) -> Any:
        batch = self._batch(url, "create", frozenset({"fields"}), **kwargs)
        if isinstance(batch, CallbackResult):
            return batch
        table, rows = batch
        made = []
        for row in rows:
            cells = self._cells(table, {}, row["fields"])
            if not isinstance(cells, dict):
                return cells or _error(422, "INVALID_RECORDS",
                                       BATCH_MESSAGES["create"])
            self.minted += 1
            made.append({
                "id": f"recNew{self.minted:011d}",
                "createdTime": f"2026-02-01T00:00:{self.minted:02d}.000Z",
                "fields": cells,
            })
        self.records[table["id"]].extend(made)
        return CallbackResult(payload={"records": made})

    def _update(self, url: Any, **kwargs: Any) -> Any:
        batch = self._batch(url, "update", frozenset({"id", "fields"}),
                            **kwargs)
        if isinstance(batch, CallbackResult):
            return batch
        table, rows = batch
        pool = {r["id"]: r for r in self.records[table["id"]]}
        planned = []
        for row in rows:
            record = pool.get(row["id"])
            if record is None:
                return _error(
                    422, "ROW_DOES_NOT_EXIST",
                    f"Record ID {row['id']} does not exist in this table")
            cells = self._cells(table, record["fields"], row["fields"])
            if not isinstance(cells, dict):
                return cells or _error(422, "INVALID_RECORDS",
                                       BATCH_MESSAGES["update"])
            planned.append((record, cells))
        for record, cells in planned:
            record["fields"] = cells
        return CallbackResult(
            payload={"records": [record for record, _ in planned]})

    def _delete(self, url: Any, **kwargs: Any) -> Any:
        base_id, ref = _segments(url)[:2]
        ids = [v for k, v in parse_qsl(url.query_string) if k == "records[]"]
        self.calls.append(("delete", {"table": ref, "records": ids}))
        fault = self._fault()
        if fault is not None:
            return fault
        table = self._table(base_id, ref)
        if table is None:
            return _model_not_found()
        if not 1 <= len(ids) <= MAX_BATCH:
            return _error(422, "INVALID_RECORDS", BATCH_MESSAGES["delete"])
        pool = self.records[table["id"]]
        known = {r["id"] for r in pool}
        missing = next((i for i in ids if i not in known), None)
        if missing is not None:
            return _error(404, "NOT_FOUND",
                          f'Could not find a record with ID "{missing}".')
        self.records[table["id"]] = [r for r in pool if r["id"] not in ids]
        return CallbackResult(
            payload={"records": [{
                "id": i,
                "deleted": True
            } for i in ids]})

    def _comments(self, url: Any, **kwargs: Any) -> Any:
        params = {k: str(v) for k, v in (kwargs.get("params") or {}).items()}
        base_id, ref, record_id = _segments(url)[:3]
        self.calls.append(("comments", {**params, "record": record_id}))
        found = self._find(base_id, ref, record_id)
        if isinstance(found, CallbackResult):
            return found
        return self._paged(self.comments.get(record_id, []),
                           "comments",
                           params,
                           trailing=True)

    def _comment(self, url: Any, **kwargs: Any) -> Any:
        base_id, ref, record_id = _segments(url)[:3]
        body = kwargs.get("json")
        self.calls.append(("comment", {"record": record_id, "body": body}))
        fault = self._fault()
        if fault is not None:
            return fault
        found = self._find(base_id, ref, record_id)
        if isinstance(found, CallbackResult):
            return found
        if (not isinstance(body, dict) or set(body) != {"text"}
                or not isinstance(body["text"], str) or not body["text"]):
            return _error(422, "INVALID_REQUEST_UNKNOWN",
                          "Invalid request: parameter validation failed.")
        self.minted += 1
        made = {
            "id": f"comNew{self.minted:011d}",
            "author": WRITER,
            "text": body["text"],
            "createdTime": f"2026-02-02T00:00:{self.minted:02d}.000Z",
            "lastUpdatedTime": None,
        }
        self.comments.setdefault(record_id, []).insert(0, made)
        return CallbackResult(payload=made)

    def install(self, m: aioresponses) -> None:
        """Route the API's record and comment endpoints to this fake.

        Args:
            m (aioresponses): the active mock.
        """
        table = rf"^{re.escape(API)}/app\w+/[^/?]+"
        record = rf"{table}/rec\w+"
        m.get(re.compile(rf"^{re.escape(API)}/meta/bases(\?.*)?$"),
              callback=self._bases,
              repeat=True)
        m.get(re.compile(rf"^{re.escape(API)}/meta/bases/[^/]+/tables$"),
              callback=self._tables,
              repeat=True)
        m.get(re.compile(rf"{table}(\?.*)?$"),
              callback=self._records,
              repeat=True)
        m.get(re.compile(rf"{record}$"), callback=self._record, repeat=True)
        m.get(re.compile(rf"{record}/comments(\?.*)?$"),
              callback=self._comments,
              repeat=True)
        m.post(re.compile(rf"{table}$"), callback=self._create, repeat=True)
        m.patch(re.compile(rf"{table}$"), callback=self._update, repeat=True)
        m.delete(re.compile(rf"{table}(\?.*)?$"),
                 callback=self._delete,
                 repeat=True)
        m.post(re.compile(rf"{record}/comments$"),
               callback=self._comment,
               repeat=True)

    def record_calls(self) -> list[dict[str, Any]]:
        """The query of every records request, in order."""
        return [params for kind, params in self.calls if kind == "records"]

    def write_calls(self) -> list[tuple[str, dict[str, Any]]]:
        """Every write request, in order, with what it carried."""
        return [(kind, params) for kind, params in self.calls
                if kind in WRITE_KINDS]


@pytest.fixture
def airtable_api() -> Iterator[FakeAirtable]:
    fake = FakeAirtable()
    with aioresponses() as m:
        fake.install(m)
        yield fake


def make_accessor(**overrides: Any) -> AirtableAccessor:
    """An accessor against the fake, pacing disabled for speed.

    Args:
        **overrides (Any): AirtableConfig fields to replace.
    """
    config = AirtableConfig(**{
        "token": TOKEN,
        "requests_per_second": 10_000.0,
        **overrides
    })
    return AirtableAccessor(config)

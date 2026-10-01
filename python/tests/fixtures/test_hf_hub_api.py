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

import json
import re
import urllib.error
import urllib.request
from typing import Any

from tests.fixtures.hf_hub_api import FakeHub, serve

HEX40 = re.compile(r"[0-9a-f]{40}")
REPO = ("models", "acme/widget")
API = "/api/models/acme/widget"


def _call(
    hub: FakeHub, path: str, body: dict[str, Any] | None = None
) -> tuple[int, Any, str]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        hub.url + path,
        data=data,
        headers={} if body is None else {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            kind = response.headers.get("Content-Type", "")
            return (
                response.status,
                json.loads(raw) if "json" in kind else raw,
                "",
            )
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, None, exc.headers.get("X-Error-Code", "")


def _head(hub: FakeHub, rev: str = "main") -> str:
    status, body, _ = _call(hub, f"{API}/revision/{rev}?expand%5B%5D=sha")
    assert status == 200, (rev, status)
    return body["sha"]


def _paths(hub: FakeHub, rev: str, prefix: str = "") -> set[str]:
    tail = f"/{prefix}" if prefix else ""
    status, body, _ = _call(hub, f"{API}/tree/{rev}{tail}")
    assert status == 200, (rev, prefix, status)
    return {row["path"] for row in body}


def _hub() -> FakeHub:
    return FakeHub(
        repos={
            REPO: {
                "README.md": b"readme",
                "data/a.csv": b"a",
            }
        }
    )


def test_the_revision_route_answers_the_full_object_by_default():
    with serve(_hub()) as hub:
        status, body, _ = _call(hub, f"{API}/revision/main")
        assert status == 200
        assert HEX40.fullmatch(body["sha"])
        assert body["id"] == "acme/widget"
        assert {s["rfilename"] for s in body["siblings"]} == {
            "README.md",
            "data/a.csv",
        }


def test_expand_sha_answers_only_the_sha_and_the_ids():
    with serve(_hub()) as hub:
        status, body, _ = _call(hub, f"{API}/revision/main?expand%5B%5D=sha")
        assert status == 200
        assert set(body) == {"_id", "id", "sha"}
        assert HEX40.fullmatch(body["sha"])


def test_the_revision_route_logs_its_rev_and_query():
    with serve(_hub()) as hub:
        _head(hub)
        assert hub.count("revision") == 1
        route, _, rev, query = hub.log[-1]
        assert (route, rev) == ("revision", "main")
        assert "expand[]=sha" in query


def test_the_head_is_derived_from_the_files_now():
    with serve(_hub()) as hub:
        first = _head(hub)
        assert _head(hub) == first
        hub.repos[REPO]["data/a.csv"] = b"a, edited"
        edited = _head(hub)
        assert edited != first
        hub.repos[REPO]["data/a.csv"] = b"a"
        assert _head(hub) == first


def test_heads_are_per_repo():
    with serve(_hub()) as hub:
        hub.repos[("models", "acme/other")] = {"README.md": b"other"}
        status, body, _ = _call(hub, "/api/models/acme/other/revision/main")
        assert status == 200
        assert body["sha"] != _head(hub)


def test_tree_paths_info_and_resolve_log_the_rev():
    with serve(_hub()) as hub:
        _paths(hub, "main")
        _call(hub, f"{API}/paths-info/dev", {"paths": ["README.md"]})
        _call(hub, "/acme/widget/resolve/v1/README.md")
        assert [(entry[0], entry[2]) for entry in hub.log] == [
            ("tree", "main"),
            ("paths_info", "dev"),
            ("resolve", "v1"),
        ]
        assert (
            hub.count("tree"),
            hub.count("paths_info"),
            hub.count("resolve"),
        ) == (1, 1, 1)


def test_a_commit_sha_serves_the_files_it_named():
    with serve(_hub()) as hub:
        old = _head(hub)
        hub.repos[REPO]["data/b.csv"] = b"b"
        del hub.repos[REPO]["README.md"]
        assert _paths(hub, old) == {"README.md", "data", "data/a.csv"}
        assert _paths(hub, "main") == {"data", "data/a.csv", "data/b.csv"}
        assert _paths(hub, old, "data") == {"data/a.csv"}
        status, rows, _ = _call(
            hub,
            f"{API}/paths-info/{old}",
            {"paths": ["README.md", "data/b.csv"]},
        )
        assert status == 200
        assert [row["path"] for row in rows] == ["README.md"]
        assert _head(hub, old) == old


def test_a_commit_sha_the_fake_never_answered_is_not_found():
    with serve(_hub()) as hub:
        _head(hub)
        unknown = "0" * 40
        assert _call(hub, f"{API}/tree/{unknown}")[::2] == (
            404,
            "RevisionNotFound",
        )
        assert _call(
            hub, f"{API}/paths-info/{unknown}", {"paths": ["README.md"]}
        )[::2] == (404, "RevisionNotFound")
        assert _call(hub, f"{API}/revision/{unknown}")[::2] == (
            404,
            "RevisionNotFound",
        )


def test_the_revision_of_a_missing_repo_is_repo_not_found():
    with serve(_hub()) as hub:
        assert _call(hub, "/api/models/acme/nope/revision/main")[::2] == (
            404,
            "RepoNotFound",
        )

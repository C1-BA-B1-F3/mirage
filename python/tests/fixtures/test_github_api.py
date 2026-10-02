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
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from tests.fixtures.github_api import FakeGitHub, serve

HEX40 = re.compile(r"[0-9a-f]{40}")


def _get(hub: FakeGitHub, segment: str) -> tuple[int, Any]:
    url = f"{hub.url}/repos/o/r/git/trees/{segment}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _sha(hub: FakeGitHub, segment: str) -> str:
    status, body = _get(hub, segment)
    assert status == 200, (segment, status, body)
    return body["sha"]


def _rows(hub: FakeGitHub, segment: str) -> dict[str, str]:
    status, body = _get(hub, segment)
    assert status == 200, (segment, status, body)
    return {row["path"]: row["sha"] for row in body["tree"]}


def _hub() -> FakeGitHub:
    return FakeGitHub(
        files={
            "docs/a.txt": b"alpha",
            "docs/sub/b.txt": b"bravo",
            "src/c.txt": b"charlie",
            "top.txt": b"top",
        }
    )


def test_a_ref_answers_its_head_commit_derived_from_the_files_now():
    with serve(_hub()) as hub:
        first = _sha(hub, "main")
        assert HEX40.fullmatch(first)
        assert _sha(hub, "main") == first
        assert _sha(hub, "main?recursive=1") == first
        hub.files["docs/a.txt"] = b"alpha, edited"
        edited = _sha(hub, "main")
        assert edited != first
        assert _sha(hub, "main?recursive=1") == edited
        hub.files["docs/a.txt"] = b"alpha"
        assert _sha(hub, "main") == first


def test_the_symlink_bit_is_part_of_the_head():
    with serve(_hub()) as hub:
        plain = _sha(hub, "main")
        hub.symlinks.add("top.txt")
        assert _sha(hub, "main") != plain


def test_a_ref_and_its_root_tree_answer_different_shas():
    with serve(_hub()) as hub:
        head = _sha(hub, "main")
        root = _sha(hub, "main:")
        assert HEX40.fullmatch(root)
        assert root != head


def test_a_folder_sha_moves_only_when_something_under_it_changes():
    with serve(_hub()) as hub:
        before = _rows(hub, "main")
        assert HEX40.fullmatch(before["docs"])
        assert _sha(hub, "main:docs") == before["docs"]
        root = _sha(hub, "main:")
        hub.files["docs/sub/b.txt"] = b"bravo, edited"
        after = _rows(hub, "main")
        assert after["docs"] != before["docs"]
        assert after["src"] == before["src"]
        assert _sha(hub, "main:") != root
        assert _sha(hub, "main:docs") == after["docs"]


def test_a_folder_sha_lists_that_folder_now_and_after_it_moved():
    with serve(_hub()) as hub:
        old = _rows(hub, "main")["docs"]
        assert set(_rows(hub, old)) == {"a.txt", "sub"}
        hub.files["docs/new.txt"] = b"new"
        new = _rows(hub, "main")["docs"]
        assert set(_rows(hub, new)) == {"a.txt", "new.txt", "sub"}
        assert set(_rows(hub, old)) == {"a.txt", "sub"}


def test_an_old_head_serves_the_files_it_named():
    with serve(_hub()) as hub:
        old = _sha(hub, "main")
        hub.files["docs/new.txt"] = b"new"
        del hub.files["top.txt"]
        assert _sha(hub, "main") != old
        assert set(_rows(hub, old)) == {"docs", "src", "top.txt"}
        status, body = _get(hub, f"{old}?recursive=1")
        assert status == 200
        assert body["sha"] == old
        assert "docs/new.txt" not in {row["path"] for row in body["tree"]}
        assert set(_rows(hub, f"{old}:docs")) == {"a.txt", "sub"}
        assert set(_rows(hub, "main:docs")) == {"a.txt", "new.txt", "sub"}


def test_a_sha_the_fake_never_answered_is_not_found():
    with serve(_hub()) as hub:
        _sha(hub, "main")
        assert _get(hub, "0" * 40)[0] == 404
        assert _get(hub, f"{'0' * 40}?recursive=1")[0] == 404
        assert _get(hub, f"{'0' * 40}:docs")[0] == 404


def test_hold_dir_gates_only_the_shallow_listing_of_the_ref():
    with serve(_hub()) as hub:
        hub.hold_dir = threading.Event()
        answered: list[str] = []
        held = threading.Thread(
            target=lambda: answered.append(_sha(hub, "main"))
        )
        held.start()
        deadline = time.monotonic() + 10
        while ("dir", "main") not in hub.log and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ("dir", "main") in hub.log
        assert _rows(hub, "main:docs")
        assert _sha(hub, "main?recursive=1")
        assert not answered
        hub.files["new.txt"] = b"new"
        hub.hold_dir.set()
        held.join(10)
        assert answered == [hub.head()]

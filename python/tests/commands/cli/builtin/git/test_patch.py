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

from dulwich.object_store import MemoryObjectStore
from dulwich.objects import Blob
from dulwich.refs import DictRefsContainer
from dulwich.repo import BaseRepo

from mirage.commands.cli.builtin.git.patch import file_patch, short_oid

MODE = 0o100644
SYMLINK = 0o120000
WIDTH = 7


def repo_with(*contents: bytes) -> tuple[BaseRepo, list[bytes]]:
    """A repository holding each blob, and their ids in the same order.

    Args:
        contents (bytes): blob contents to store.
    """
    store = MemoryObjectStore()
    ids = []
    for content in contents:
        blob = Blob.from_string(content)
        store.add_object(blob)
        ids.append(blob.id)
    return BaseRepo(store, DictRefsContainer({})), ids


def test_short_oid_pads_a_missing_side_with_zeros():
    assert short_oid(None, WIDTH) == "0000000"
    assert short_oid((MODE, b"4cb29ea" + b"0" * 33), WIDTH) == "4cb29ea"


# Every expected patch below is pinned against git 2.54.


def test_a_changed_line_is_one_hunk_with_its_context():
    repo, (old, new) = repo_with(b"one\ntwo\nthree\n", b"one\nTWO\nthree\n")
    patch = file_patch(
        repo, "f.txt", "f.txt", (MODE, old), (MODE, new), None, WIDTH
    )
    assert patch == (
        b"diff --git a/f.txt b/f.txt\n"
        b"index 4cb29ea..ddc897f 100644\n"
        b"--- a/f.txt\n"
        b"+++ b/f.txt\n"
        b"@@ -1,3 +1,3 @@\n"
        b" one\n"
        b"-two\n"
        b"+TWO\n"
        b" three\n"
    )


def test_a_missing_final_newline_is_marked_on_each_side():
    repo, (old, new) = repo_with(b"keep\nlast", b"keep\nend")
    patch = file_patch(
        repo, "g.txt", "g.txt", (MODE, old), (MODE, new), None, WIDTH
    )
    assert patch[patch.index(b"@@") :] == (
        b"@@ -1,2 +1,2 @@\n"
        b" keep\n"
        b"-last\n"
        b"\\ No newline at end of file\n"
        b"+end\n"
        b"\\ No newline at end of file\n"
    )


def test_a_pure_rename_has_no_index_line():
    repo, (blob,) = repo_with(b"keep\nend")
    patch = file_patch(
        repo, "h.txt", "g.txt", (MODE, blob), (MODE, blob), 100, WIDTH
    )
    assert patch == (
        b"diff --git a/g.txt b/h.txt\n"
        b"similarity index 100%\n"
        b"rename from g.txt\n"
        b"rename to h.txt\n"
    )


def test_a_file_turned_symlink_splits_into_a_deletion_and_a_creation():
    repo, (old, new) = repo_with(b"one\nTWO\nthree\n", b"target")
    patch = file_patch(
        repo, "f.txt", "f.txt", (MODE, old), (SYMLINK, new), None, WIDTH
    )
    assert patch == (
        b"diff --git a/f.txt b/f.txt\n"
        b"deleted file mode 100644\n"
        b"index ddc897f..0000000\n"
        b"--- a/f.txt\n"
        b"+++ /dev/null\n"
        b"@@ -1,3 +0,0 @@\n"
        b"-one\n"
        b"-TWO\n"
        b"-three\n"
        b"diff --git a/f.txt b/f.txt\n"
        b"new file mode 120000\n"
        b"index 0000000..1de5659\n"
        b"--- /dev/null\n"
        b"+++ b/f.txt\n"
        b"@@ -0,0 +1 @@\n"
        b"+target\n"
        b"\\ No newline at end of file\n"
    )

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

from mirage.utils.key_prefix import mount_key, rekey, strip_mount, under_path


def test_strip_mount_removes_prefix_at_boundary():
    assert strip_mount("/data/sub/x.txt", "/data") == "/sub/x.txt"


def test_strip_mount_respects_path_boundary():
    assert strip_mount("/database/x.txt", "/data") == "/database/x.txt"


def test_strip_mount_at_mount_root():
    assert strip_mount("/data", "/data") == "/"


def test_strip_mount_without_prefix():
    assert strip_mount("/x.txt", "") == "/x.txt"


def test_mount_key_strips_surrounding_slashes():
    assert mount_key("/data/sub/x.txt", "/data") == "sub/x.txt"


def test_mount_key_at_mount_root_is_empty():
    assert mount_key("/data", "/data") == ""


def test_mount_key_without_prefix():
    assert mount_key("/x.txt", "") == "x.txt"


def test_under_path_matches_descendant():
    assert under_path("/data/x/y", "/data/x") is True


def test_under_path_matches_root_itself():
    assert under_path("/data/x", "/data/x") is True


def test_under_path_ignores_trailing_slash_on_either_side():
    assert under_path("/data/x/", "/data/x") is True
    assert under_path("/data/x", "/data/x/") is True


def test_under_path_respects_path_boundary():
    assert under_path("/data/xy", "/data/x") is False


def test_under_path_with_empty_root_matches_everything():
    assert under_path("/anything", "") is True
    assert under_path("/anything", "/") is True


def test_rekey_child_under_named_mount():
    assert rekey("/data/sub", "sub", "/data/sub/x.txt") == "sub/x.txt"


def test_rekey_child_at_mount_root():
    assert rekey("/data", "", "/data/x.txt") == "x.txt"


def test_rekey_deep_child():
    assert rekey("/mnt/s3", "", "/mnt/s3/a/b/c.txt") == "a/b/c.txt"


def test_rekey_matches_mount_key():
    parent_original = "/data/sub"
    prefix = "/data"
    parent_key = mount_key(parent_original, prefix)
    child = "/data/sub/deep/y.txt"
    assert rekey(parent_original, parent_key, child) == mount_key(
        child, prefix
    )

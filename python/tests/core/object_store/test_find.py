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

from mirage.core.object_store.find import make_find
from tests.core.object_store.conftest import FakeStore, make_driver, spec


def test_find_synthesizes_the_implicit_parent_chain(accessor):
    store = FakeStore({"data/a/b/deep.txt": b"x"})
    find = make_find(make_driver(store))
    out = asyncio.run(find(accessor, spec("/data"), type="d"))
    assert out == ["/data", "/data/a", "/data/a/b"]


def test_find_type_f_drops_synthesized_dirs(accessor):
    store = FakeStore({"data/a/b.txt": b"x"})
    find = make_find(make_driver(store))
    assert asyncio.run(find(accessor, spec("/data"),
                            type="f")) == ["/data/a/b.txt"]


def test_find_marker_only_start_is_empty(accessor):
    store = FakeStore({"data/": b""})
    find = make_find(make_driver(store))
    assert asyncio.run(find(accessor, spec("/data"), empty=True)) == ["/data"]


def test_find_missing_start_emits_nothing(accessor):
    find = make_find(make_driver(FakeStore()))
    assert asyncio.run(find(accessor, spec("/never"))) == []


def test_find_narrowed_query_still_emits_the_start_path(accessor):
    # The pushed-down -name query matches nothing, but the prefix holds
    # keys, so the probe restores the start directory.
    store = FakeStore({"data/a.txt": b"x"})
    find = make_find(make_driver(store, find_narrowing=True))
    out = asyncio.run(find(accessor, spec("/data"), name="*.md", type="f"))
    assert out == []
    out = asyncio.run(find(accessor, spec("/data"), name="*.txt", type="f"))
    assert out == ["/data/a.txt"]


def test_find_size_gate_counts_a_directory_as_dir_size(accessor):
    store = FakeStore({"data/a/big.txt": b"123456"})
    find = make_find(make_driver(store))
    out = asyncio.run(find(accessor, spec("/data"), min_size=1))
    assert out == ["/data", "/data/a", "/data/a/big.txt"]
    out = asyncio.run(find(accessor, spec("/data"), max_size=100))
    assert out == ["/data/a/big.txt"]

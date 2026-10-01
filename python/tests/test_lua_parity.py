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

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
PY_LUA = sorted((REPO / "python" / "mirage").rglob("*.lua"))
TS_LUA = sorted(
    (REPO / "typescript" / "packages" / "node" / "src").rglob("*.lua")
)


def _by_name(paths: list[pathlib.Path]) -> dict[str, pathlib.Path]:
    return {path.name: path for path in paths}


def test_every_lua_script_exists_in_both_languages():
    """A server-side script is one wire contract with two copies.

    Neither language can import the other's file, so each ships its own;
    the pair is what keeps a Redis-side behavior from having two
    meanings. A script added to one tree and forgotten in the other
    fails here rather than at runtime on whichever host is missing it.
    """
    assert PY_LUA, "no lua scripts found under python/mirage"
    assert sorted(_by_name(PY_LUA)) == sorted(_by_name(TS_LUA))


def test_lua_basenames_are_unique_within_each_tree():
    """tsup copies each script to a flat `dist/<name>.lua`.

    Two scripts sharing a basename would silently overwrite each other
    in the bundle, so the name has to be unique even though the source
    directories differ.
    """
    for tree in (PY_LUA, TS_LUA):
        names = [path.name for path in tree]
        assert len(names) == len(set(names))


def test_each_lua_pair_is_byte_identical():
    """One wire schema, two copies: the two files must never drift."""
    ts = _by_name(TS_LUA)
    for path in PY_LUA:
        twin = ts[path.name]
        assert path.read_text(encoding="utf-8") == twin.read_text(
            encoding="utf-8"
        ), f"{path.name} differs between python and ts"

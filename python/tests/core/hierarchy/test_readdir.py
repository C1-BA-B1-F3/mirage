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

import pytest

from mirage.cache.file.ram import RAMFileCacheStore
from mirage.cache.index import Evicted, IndexEntry
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.cache.index.view import IndexView
from mirage.core.hierarchy.readdir import DirListing, make_readdir
from mirage.core.hierarchy.scope import ScopeMatch
from mirage.types import PathSpec
from tests.core.hierarchy.conftest import (FakeAccessor, detect_scope,
                                           list_notes, list_rooms, room_guard,
                                           spec)

READDIR = make_readdir(
    detect_scope,
    listers={
        "rooms": list_rooms,
        "room": list_notes,
    },
    static_root=("rooms", ),
    guards={"room": room_guard},
)


def test_static_root_lists_without_any_call(accessor):
    assert asyncio.run(READDIR(accessor, spec("/"))) == ["/h/rooms"]
    assert accessor.calls == []


def test_dynamic_level_joins_names_under_the_virtual_key(accessor):
    out = asyncio.run(READDIR(accessor, spec("/rooms")))
    assert out == ["/h/rooms/red", "/h/rooms/blue"]


def test_a_none_index_gets_a_call_local_store(accessor):
    # Bare commands built outside a workspace bind index=None; the kit
    # substitutes a call-local store exactly as it does for NULL_INDEX.
    out = asyncio.run(READDIR(accessor, spec("/rooms"), index=None))
    assert out == ["/h/rooms/red", "/h/rooms/blue"]


def test_guard_runs_before_the_index_probe(accessor):
    index = RAMIndexCacheStore()
    asyncio.run(READDIR(accessor, spec("/rooms/red"), index=index))
    asyncio.run(READDIR(accessor, spec("/rooms/red"), index=index))
    # Two guard calls, one lister call: the second hit was served from
    # the index but still had to prove the room exists.
    assert accessor.calls == ["guard:red", "notes:red", "guard:red"]


def test_guard_failure_is_enoent_even_for_a_listable_shape(accessor):
    with pytest.raises(FileNotFoundError):
        asyncio.run(READDIR(accessor, spec("/rooms/ghost")))


def test_leaf_and_invalid_paths_refuse(accessor):
    with pytest.raises(FileNotFoundError):
        asyncio.run(READDIR(accessor, spec("/rooms/red/a.json")))
    with pytest.raises(FileNotFoundError):
        asyncio.run(READDIR(accessor, spec("/halls")))


def test_dot_prefixed_names_are_dropped_from_listings(accessor):
    # The classifier refuses every dot-leading segment, so a listing
    # must not advertise one (a quoted postgres schema can be named
    # ".foo"; every other op would report it absent).
    async def hidden_rooms(a, match):
        rooms = await list_rooms(a, match)
        return [(".secret", rooms[0][1]), *rooms]

    readdir = make_readdir(detect_scope,
                           listers={"rooms": hidden_rooms},
                           static_root=("rooms", ))
    index = RAMIndexCacheStore()
    out = asyncio.run(readdir(accessor, spec("/rooms"), index=index))
    assert out == ["/h/rooms/red", "/h/rooms/blue"]
    cached = asyncio.run(index.list_dir("/h/rooms"))
    assert cached.entries == ["/h/rooms/red", "/h/rooms/blue"]


def test_leaf_error_can_be_enotdir(accessor):
    readdir = make_readdir(detect_scope,
                           listers={"rooms": list_rooms},
                           static_root=("rooms", ),
                           leaf_error="enotdir")
    with pytest.raises(NotADirectoryError):
        asyncio.run(readdir(accessor, spec("/rooms/red/a.json")))


async def _entry_notes(accessor: FakeAccessor, match: ScopeMatch,
                       entry: IndexEntry) -> list[tuple[str, IndexEntry]]:
    accessor.calls.append(f"entry-notes:{entry.id}")
    return [("note.json",
             IndexEntry(id=entry.id,
                        name="note.json",
                        resource_type="fake/note",
                        vfs_name="note.json",
                        size=entry.extra.get("json_size")))]


ENTRY_READDIR = make_readdir(
    detect_scope,
    listers={"rooms": list_rooms},
    entry_listers={"room": _entry_notes},
    static_root=("rooms", ),
)


def test_entry_lister_resolves_through_the_parent_listing(accessor):
    # The kit warms the parent listing once and hands the directory's own
    # entry to the lister; the lister never re-fetches its ancestors.
    index = RAMIndexCacheStore()
    out = asyncio.run(ENTRY_READDIR(accessor, spec("/rooms/red"), index=index))
    assert out == ["/h/rooms/red/note.json"]
    assert accessor.calls == ["rooms", "entry-notes:red"]
    asyncio.run(ENTRY_READDIR(accessor, spec("/rooms/blue"), index=index))
    # The second room resolves from the already-cached rooms listing.
    assert accessor.calls == ["rooms", "entry-notes:red", "entry-notes:blue"]


def test_entry_lister_unlisted_container_is_enoent(accessor):
    with pytest.raises(FileNotFoundError):
        asyncio.run(ENTRY_READDIR(accessor, spec("/rooms/ghost")))
    assert accessor.calls == ["rooms"]


def test_entry_lister_works_without_an_index(accessor):
    # A caller with no cache gets a call-local one, so the parent warm
    # still feeds the entry resolution.
    out = asyncio.run(ENTRY_READDIR(accessor, spec("/rooms/red")))
    assert out == ["/h/rooms/red/note.json"]


def test_a_kind_in_both_lister_tables_fails_at_build():
    with pytest.raises(ValueError):
        make_readdir(detect_scope,
                     listers={"room": list_notes},
                     entry_listers={"room": _entry_notes},
                     static_root=("rooms", ))


def _room_entry(room: str) -> IndexEntry:
    return IndexEntry(id=room,
                      name=room,
                      resource_type="fake/room",
                      vfs_name=room)


async def _seeding_notes(accessor, match, own):
    accessor.calls.append(f"seed-notes:{match.slots['room']}")
    atts = IndexEntry(id=f"{own.id}:atts",
                      name="atts",
                      resource_type="fake/atts",
                      vfs_name="atts")
    blob = IndexEntry(id="x",
                      name="x.bin",
                      resource_type="fake/blob",
                      vfs_name="x.bin",
                      size=3)
    return DirListing(entries=[("atts", atts)],
                      seeds={"atts": [("x.bin", blob)]})


async def _atts_fallback(accessor, match, own):
    accessor.calls.append(f"atts-fallback:{match.slots['room']}")
    return []


SEEDED_READDIR = make_readdir(
    detect_scope,
    listers={"rooms": list_rooms},
    entry_listers={
        "room": _seeding_notes,
        "room_atts": _atts_fallback,
    },
    static_root=("rooms", ),
)


def test_seeds_serve_the_child_listing_without_a_second_fetch(accessor):
    index = RAMIndexCacheStore()
    asyncio.run(SEEDED_READDIR(accessor, spec("/rooms/red"), index=index))
    out = asyncio.run(
        SEEDED_READDIR(accessor, spec("/rooms/red/atts"), index=index))
    assert out == ["/h/rooms/red/atts/x.bin"]
    # One fetch answered both directories; the atts lister never ran.
    assert accessor.calls == ["rooms", "seed-notes:red"]


def test_entry_branch_rechecks_the_listing_after_resolving(accessor):
    # A cold readdir of the seeded child resolves its own entry, which
    # warms the seeding parent; the re-check then serves the listing the
    # warm just wrote instead of running the fallback lister.
    out = asyncio.run(SEEDED_READDIR(accessor, spec("/rooms/red/atts")))
    assert out == ["/h/rooms/red/atts/x.bin"]
    assert accessor.calls == ["rooms", "seed-notes:red"]


async def _days_by_room(accessor, match, room_entry):
    accessor.calls.append(f"days:{room_entry.id}:{match.slots['day']}")
    day = match.slots["day"]
    return [(f"{day}.txt",
             IndexEntry(id=f"{room_entry.id}:{day}",
                        name=f"{day}.txt",
                        resource_type="fake/day_note",
                        vfs_name=f"{day}.txt"))]


PARENT_READDIR = make_readdir(
    detect_scope,
    listers={"rooms": list_rooms},
    entry_listers={"room": _entry_notes},
    parent_entry_listers={"room_day": _days_by_room},
    static_root=("rooms", ),
)


def test_parent_entry_lister_is_proven_by_the_parent(accessor):
    # The day dir has no entry of its own (the room listing never minted
    # one); the proof is the room entry, handed to the lister.
    out = asyncio.run(PARENT_READDIR(accessor, spec("/rooms/red/2024-01-15")))
    assert out == ["/h/rooms/red/2024-01-15/2024-01-15.txt"]
    assert accessor.calls == ["rooms", "days:red:2024-01-15"]


def test_parent_entry_lister_bogus_parent_is_enoent(accessor):
    with pytest.raises(FileNotFoundError):
        asyncio.run(PARENT_READDIR(accessor, spec("/rooms/ghost/2024-01-15")))
    assert accessor.calls == ["rooms"]


def test_a_kind_in_several_lister_tables_fails_at_build():
    with pytest.raises(ValueError):
        make_readdir(detect_scope,
                     listers={"rooms": list_rooms},
                     entry_listers={"room_day": _atts_fallback},
                     parent_entry_listers={"room_day": _days_by_room},
                     static_root=("rooms", ))


def _any_pattern(pattern: str) -> bool:
    return True


async def _list_windowed(accessor: FakeAccessor,
                         match: ScopeMatch) -> DirListing:
    # Stands in for a bounded listing: without a glob it reports the tail
    # of the tree, with one it reports exactly what the glob asked for.
    accessor.calls.append(f"window:{match.pattern}")
    names = ["c.json"] if match.pattern is None else [match.pattern]
    entries = [(n,
                IndexEntry(id=n, name=n, resource_type="fake/note",
                           vfs_name=n)) for n in names]
    return DirListing(entries=entries, partial=match.pattern is not None)


WINDOW_READDIR = make_readdir(
    detect_scope,
    listers={
        "rooms": list_rooms,
        "room": _list_windowed,
    },
    static_root=("rooms", ),
    pattern_kinds={"room": _any_pattern},
)


def _globbed(mount_path: str, pattern: str) -> PathSpec:
    base = spec(mount_path)
    return PathSpec(virtual=base.virtual + "/" + pattern,
                    directory=base.virtual + "/",
                    vfs_path=base.vfs_path + "/" + pattern,
                    pattern=pattern)


def test_a_pattern_kind_hands_the_glob_to_its_lister(accessor):
    out = asyncio.run(
        WINDOW_READDIR(accessor, _globbed("/rooms/red", "z.json")))
    assert out == ["/h/rooms/red/z.json"]
    assert accessor.calls == ["window:z.json"]


def test_an_undeclared_kind_never_sees_a_pattern(accessor):
    plain = make_readdir(detect_scope,
                         listers={
                             "rooms": list_rooms,
                             "room": _list_windowed
                         },
                         static_root=("rooms", ))
    out = asyncio.run(plain(accessor, _globbed("/rooms/red", "z.json")))
    assert out == ["/h/rooms/red/c.json"]
    assert accessor.calls == ["window:None"]


def test_a_partial_listing_is_not_cached_as_the_directory(accessor):
    index = RAMIndexCacheStore()
    asyncio.run(
        WINDOW_READDIR(accessor, _globbed("/rooms/red", "z.json"),
                       index=index))
    # The entries are real, so they are cached one by one; the directory
    # is not, so a bare listing still asks the backend.
    assert asyncio.run(index.get("/h/rooms/red/z.json")).entry is not None
    assert asyncio.run(index.list_dir("/h/rooms/red")).entries is None
    out = asyncio.run(WINDOW_READDIR(accessor, spec("/rooms/red"),
                                     index=index))
    assert out == ["/h/rooms/red/c.json"]
    assert accessor.calls == ["window:z.json", "window:None"]


def test_a_globbed_listing_does_not_read_a_warm_window(accessor):
    # The cached listing is the window itself, so answering the glob from
    # it would hide everything the window leaves out.
    index = RAMIndexCacheStore()
    asyncio.run(WINDOW_READDIR(accessor, spec("/rooms/red"), index=index))
    out = asyncio.run(
        WINDOW_READDIR(accessor, _globbed("/rooms/red", "z.json"),
                       index=index))
    assert out == ["/h/rooms/red/z.json"]
    assert accessor.calls == ["window:None", "window:z.json"]


def _room(name: str) -> tuple[str, IndexEntry]:
    return (name, IndexEntry(id=name, name=name, resource_type="fake/room"))


def _sliding(window: bool, partial: bool = False):
    # First the window holds red and blue, then a newer room pushes red out;
    # each listing also seeds the room it names first.
    pages = [["red", "blue"], ["blue", "green"]]

    async def lister(a, match):
        names = pages.pop(0)
        return DirListing(entries=[_room(n) for n in names],
                          seeds={names[0]: [_room(f"{names[0]}-a")]},
                          window=window,
                          partial=partial)

    return make_readdir(detect_scope,
                        listers={"rooms": lister},
                        static_root=("rooms", ))


@pytest.mark.parametrize("window, survives", [(True, True), (False, False)])
def test_a_window_slide_keeps_the_row_that_slid_out(accessor, window,
                                                    survives):
    # The same slide without the flag evicts red, which is what shows the
    # fixture can tell a window from a complete listing.
    readdir = _sliding(window)
    index = RAMIndexCacheStore()
    asyncio.run(readdir(accessor, spec("/rooms"), index=index))
    asyncio.run(index.invalidate())
    asyncio.run(readdir(accessor, spec("/rooms"), index=index))
    red = asyncio.run(index.get("/h/rooms/red")).entry
    assert (red is not None) is survives
    assert asyncio.run(index.list_dir("/h/rooms")).entries == [
        "/h/rooms/blue", "/h/rooms/green"
    ]


def test_a_windowed_listing_seeds_windows_too(accessor):
    # A day seeded from a label window names only that window's messages;
    # it must not evict what a full listing of the day found earlier.
    readdir = make_readdir(
        detect_scope,
        listers={
            "rooms":
            lambda a, match: _seed_once(["/h/rooms/red-a", "/h/rooms/red-b"],
                                        window=True)
        },
        static_root=("rooms", ))
    index = RAMIndexCacheStore()
    asyncio.run(index.set_dir("/h/rooms/red",
                              [_room("red-a"), _room("red-b")]))
    asyncio.run(readdir(accessor, spec("/rooms"), index=index))
    assert asyncio.run(index.get("/h/rooms/red/red-b")).entry is not None


def test_a_partial_window_stays_partial_and_seeds_windows(accessor):
    readdir = _sliding(window=True, partial=True)
    index = RAMIndexCacheStore()
    asyncio.run(index.set_dir("/h/rooms/red",
                              [_room("red-a"), _room("red-z")]))
    asyncio.run(readdir(accessor, spec("/rooms"), index=index))
    assert asyncio.run(index.list_dir("/h/rooms")).entries is None
    assert asyncio.run(index.get("/h/rooms/red/red-z")).entry is not None


async def _seed_once(_names: list[str], window: bool) -> DirListing:
    return DirListing(entries=[_room("red")],
                      seeds={"red": [_room("red-a")]},
                      window=window)


async def _unchanged_listing(a, match):
    return DirListing(
        entries=[(".secret", _room(".secret")[1]),
                 _room("red"),
                 _room("blue")],
        seeds={"red": [_room("red-a"), (".hidden", _room(".hidden")[1])]})


def test_relisting_an_unchanged_backend_hands_nothing_to_cleanup(accessor):
    # Every writer here must name every child it names the first time; a
    # dropped hidden name or a seeded child listing that differs between
    # two identical fetches would evict rows that still exist.
    gone: list[Evicted] = []

    async def on_gone(child: Evicted) -> None:
        gone.append(child)

    readdir = make_readdir(detect_scope,
                           listers={"rooms": _unchanged_listing},
                           static_root=("rooms", ))
    store = RAMIndexCacheStore()
    index = IndexView(store,
                      RAMFileCacheStore(),
                      "/h",
                      lambda _key: True,
                      on_gone=on_gone)
    asyncio.run(readdir(accessor, spec("/rooms"), index=index))
    asyncio.run(store.invalidate())
    asyncio.run(readdir(accessor, spec("/rooms"), index=index))
    assert gone == []
    assert asyncio.run(store.get("/h/rooms/red/red-a")).entry is not None

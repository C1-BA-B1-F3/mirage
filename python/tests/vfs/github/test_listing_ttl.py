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
from datetime import datetime, timedelta, timezone

import pytest

from mirage.cache.index.view import IndexView
from mirage.core.github.config import GitHubConfig
from mirage.core.github.tree import fetch_tree
from mirage.types import MountMode, ReadPolicy, ReadSpec
from mirage.vfs.github import GitHubVFS
from mirage.vfs.registry import build_vfs
from mirage.workspace import Workspace
from mirage.workspace.mount import Mount
from tests.fixtures.github_api import FakeGitHub, serve

OLD = b"version one\n"
NEW = b"version two, longer\n"
LISTED = b"a.txt\nb.txt\n"
GROWN = b"a.txt\nb.txt\nc.txt\n"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Clock(datetime):
    at: datetime = T0

    @classmethod
    def now(cls, tz=None):
        return cls.at

    @classmethod
    def advance(cls, seconds: float) -> None:
        cls.at += timedelta(seconds=seconds)


def _hub() -> FakeGitHub:
    return FakeGitHub(files={
        "docs/a.txt": OLD,
        "docs/b.txt": b"bravo x\n",
        "top.txt": b"top\n"
    })


def _vfs(hub: FakeGitHub):
    return build_vfs(
        "github", {
            "token": "t",
            "owner": "o",
            "repo": "r",
            "ref": "main",
            "base_url": hub.url
        })


def _mount(vfs, policy: ReadPolicy = ReadPolicy.BOUNDED, ttl: int = 1):
    return Mount(vfs=vfs,
                 mode=MountMode.READ,
                 read=ReadSpec(policy=policy, ttl=ttl))


def _ws(vfs, prefix: str = "/gh", **kwargs) -> Workspace:
    return Workspace({prefix: _mount(vfs, **kwargs)})


def _sessions(ws: Workspace, count: int) -> list[str]:
    ids = [f"s{n}" for n in range(count)]
    for session_id in ids:
        ws.create_session(session_id)
    return ids


async def _out(ws: Workspace, line: str, session_id: str | None = None):
    kwargs = {} if session_id is None else {"session_id": session_id}
    result = await asyncio.wait_for(ws.shell(line, **kwargs), 10)
    out = await result.materialize_stdout()
    err = await result.stderr_str()
    assert (result.exit_code, err) == (0, ""), line
    return out


async def _expire(ws: Workspace, path: str) -> None:
    await ws._registry.mount_for(path).index.invalidate()


def _du_paths(out: bytes) -> list[str]:
    return [line.split("\t", 1)[1] for line in out.decode().splitlines()]


@pytest.mark.asyncio
async def test_concurrent_sessions_after_an_expiry_fetch_the_tree_once():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), ttl=600)
        try:
            ids = _sessions(ws, 7)
            assert await _out(ws, "ls /gh/docs") == LISTED
            await _expire(ws, "/gh/docs")
            hub.log.clear()
            outs = await asyncio.wait_for(
                asyncio.gather(*(_out(ws, "ls /gh/docs", session_id)
                                 for session_id in ids)), 10)
            assert hub.counts() == (0, 1, 0)
            assert outs == [LISTED] * 7
        finally:
            await ws.close()


def _gate(monkeypatch) -> tuple[asyncio.Event, asyncio.Event]:
    # Pause outside the mutation fence so a competing reader can enter.
    wiped, release = asyncio.Event(), asyncio.Event()
    original = IndexView.invalidate_prefix
    fired = []

    async def gated(self, vfs_path: str) -> None:
        await original(self, vfs_path)
        if not fired:
            fired.append(vfs_path)
            wiped.set()
            await release.wait()

    monkeypatch.setattr(IndexView, "invalidate_prefix", gated)
    return wiped, release


@pytest.mark.asyncio
async def test_a_reader_arriving_mid_refill_waits_for_it(monkeypatch):
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), ttl=600)
        first = second = None
        release = asyncio.Event()
        try:
            _sessions(ws, 2)
            assert await _out(ws, "ls /gh/docs") == LISTED
            await _expire(ws, "/gh/docs")
            hub.log.clear()
            wiped, release = _gate(monkeypatch)
            first = asyncio.ensure_future(_out(ws, "ls /gh/docs", "s0"))
            await asyncio.wait_for(wiped.wait(), 5)
            second = asyncio.ensure_future(_out(ws, "ls /gh/docs", "s1"))
            await asyncio.sleep(0.02)
            waited = not second.done()
            release.set()
            outs = await asyncio.wait_for(asyncio.gather(first, second), 5)
            assert hub.counts() == (0, 1, 0)
            assert outs == [LISTED, LISTED]
            assert waited
        finally:
            release.set()
            await asyncio.gather(*(task for task in (first, second) if task),
                                 return_exceptions=True)
            await ws.close()


@pytest.mark.asyncio
async def test_a_glob_arriving_mid_refill_still_answers(monkeypatch):
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), ttl=600)
        first = None
        release = asyncio.Event()
        try:
            _sessions(ws, 2)
            assert await _out(ws, "ls /gh/docs") == LISTED
            await _expire(ws, "/gh/docs")
            hub.log.clear()
            wiped, release = _gate(monkeypatch)
            first = asyncio.ensure_future(_out(ws, "ls /gh/docs", "s0"))
            await asyncio.wait_for(wiped.wait(), 5)
            globbed = await asyncio.wait_for(_out(ws, "echo /gh/docs/*", "s1"),
                                             5)
            assert globbed == b"/gh/docs/a.txt /gh/docs/b.txt\n"
            release.set()
            assert await asyncio.wait_for(first, 5) == LISTED
            assert hub.counts() == (0, 2, 0)
        finally:
            release.set()
            await asyncio.gather(*([first] if first else []),
                                 return_exceptions=True)
            await ws.close()


MIXED = [
    "ls /gh/docs",
    "find /gh -name a.txt",
    "du -a /gh",
    "grep -rl x /gh",
    "echo /gh/docs/*",
    "cat /gh/docs/a.txt",
]


# Rotations 2 and 3 expose lock inversion if refills lock the raw store.
@pytest.mark.asyncio
@pytest.mark.parametrize("rotation", [0, 2, 3])
async def test_mixed_commands_after_an_expiry_never_deadlock(rotation):
    order = MIXED[rotation:] + MIXED[:rotation]
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), ttl=600)
        try:
            ids = _sessions(ws, 3)
            expected = {line: await _out(ws, line) for line in MIXED}
            await _expire(ws, "/gh/docs")
            outs = await asyncio.wait_for(
                asyncio.gather(*(_out(ws, line, ids[n % 3])
                                 for n, line in enumerate(order))), 5)
            assert outs == [expected[line] for line in order]
        finally:
            await ws.close()


TREE_WALKS = [
    ("/gh", "find /gh -name c.txt", "/gh/docs/c.txt"),
    ("/gh", "cd /gh && find . -name c.txt", "./docs/c.txt"),
    ("/gh", "du -a /gh", "/gh/docs/c.txt"),
    ("/gh", "cd /gh && du -a", "./docs/c.txt"),
    ("/r/gh", "find /r/gh -name c.txt", "/r/gh/docs/c.txt"),
]
TREE_WALKS_BELOW_ROOT = [
    ("/gh", "find /gh/docs -name c.txt", "/gh/docs/c.txt"),
    ("/gh", "cd /gh/docs && du -a", "./c.txt"),
]


async def _walk_after_an_add(prefix: str, line: str, path: str) -> None:
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), prefix=prefix, ttl=600)
        try:
            assert await _out(ws, f"ls {prefix}/docs") == LISTED
            hub.files["docs/c.txt"] = b"charlie\n"
            await _expire(ws, prefix + "/docs")
            hub.log.clear()
            out = await _out(ws, line)
            printed = _du_paths(out) if "du" in line else out.decode().split()
            assert path in printed
            assert hub.counts() == (0, 1, 0)
        finally:
            await ws.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,line,path", TREE_WALKS)
async def test_a_tree_walk_after_an_expiry_sees_a_remote_add(
        prefix, line, path):
    await _walk_after_an_add(prefix, line, path)


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,line,path", TREE_WALKS_BELOW_ROOT)
async def test_a_tree_walk_below_the_root_refills_once(prefix, line, path):
    await _walk_after_an_add(prefix, line, path)


@pytest.mark.asyncio
async def test_a_truncated_tree_is_not_refetched_by_every_find():
    files = {"top.txt": b"t", "docs/a.txt": OLD}
    with serve(FakeGitHub(files=files, truncated_recursive=True)) as hub:
        config = GitHubConfig(token="t", base_url=hub.url)
        tree, truncated = await fetch_tree(config, "o", "r", "main")
        vfs = GitHubVFS(config,
                        "o",
                        "r",
                        "main",
                        default_branch="main",
                        tree=tree,
                        truncated=truncated)
        ws = _ws(vfs, ttl=600)
        try:
            await _out(ws, "find /gh -name a.txt")
            walks = hub.count("recursive")
            await _out(ws, "find /gh -name a.txt")
            assert hub.count("recursive") == walks
        finally:
            await ws.close()


FIRST_READERS = [
    "ls /gh/docs",
    "echo /gh/docs/*",
    "for f in /gh/docs/*; do echo $f; done",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [ReadPolicy.BOUNDED, ReadPolicy.FRESH])
@pytest.mark.parametrize("first", FIRST_READERS)
async def test_a_listing_is_served_until_the_mount_ttl_then_refetched(
        first, policy):
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), policy=policy, ttl=1)
        try:
            await _out(ws, first)
            hub.files["docs/c.txt"] = b"charlie\n"
            assert await _out(ws, "ls /gh/docs") == LISTED
            await asyncio.sleep(1.1)
            assert await _out(ws, "ls /gh/docs") == GROWN
        finally:
            await ws.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("line,expected", [
    ("ls /gh/docs", GROWN),
    ("cat /gh/docs/a.txt", NEW),
    ("find /gh -name c.txt", b"/gh/docs/c.txt\n"),
])
async def test_the_first_reader_after_the_ttl_sees_the_remote_change(
        line, expected):
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), ttl=1)
        try:
            assert await _out(ws, "ls /gh/docs") == LISTED
            hub.files["docs/c.txt"] = b"charlie\n"
            hub.files["docs/a.txt"] = NEW
            await asyncio.sleep(1.1)
            assert await _out(ws, line) == expected
        finally:
            await ws.close()


@pytest.mark.asyncio
async def test_two_prefixes_over_one_vfs_keep_their_own_bound():
    with serve(_hub()) as hub:
        vfs = _vfs(hub)
        ws = Workspace({"/a": _mount(vfs, ttl=1), "/b": _mount(vfs, ttl=600)})
        try:
            assert await _out(ws, "ls /a/docs") == LISTED
            assert await _out(ws, "ls /b/docs") == LISTED
            hub.files["docs/c.txt"] = b"charlie\n"
            await asyncio.sleep(1.1)
            assert await _out(ws, "ls /a/docs") == GROWN
            assert await _out(ws, "ls /b/docs") == LISTED
        finally:
            await ws.close()


# Keep T0 before the real clock used by the GitHub seed.
@pytest.mark.asyncio
@pytest.mark.parametrize("after,expected", [(599, LISTED), (601, GROWN)])
async def test_a_mount_without_a_ttl_caps_listings_at_the_default(
        monkeypatch, after, expected):
    _Clock.at = T0
    for module in ("view", "ram"):
        monkeypatch.setattr(f"mirage.cache.index.{module}.datetime", _Clock)
    with serve(_hub()) as hub:
        ws = Workspace({"/gh": Mount(vfs=_vfs(hub), mode=MountMode.READ)})
        try:
            assert await _out(ws, "ls /gh/docs") == LISTED
            hub.files["docs/c.txt"] = b"charlie\n"
            _Clock.advance(after)
            assert await _out(ws, "ls /gh/docs") == expected
        finally:
            await ws.close()

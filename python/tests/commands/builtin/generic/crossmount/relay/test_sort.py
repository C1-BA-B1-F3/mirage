import pytest

from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


@pytest.mark.asyncio
@pytest.mark.parametrize("overwrite", [False, True])
async def test_relay_sort_caches_inputs_and_replacements(overwrite):
    left, right = RAMVFS(), RAMVFS()
    left.caches_reads = right.caches_reads = True
    left.load_state({"files": {"/input": b"z\na\n"}})
    right.load_state({"files": {"/input": b"m\n"}})
    ws = Workspace({"/a": left, "/b": right}, mode=MountMode.WRITE)
    command = "sort /a/input /b/input"
    try:
        result = await ws.shell(command +
                                (" -o /a/input" if overwrite else ""))
        assert result.exit_code == 0
        assert await result.materialize_stdout() == (b"" if overwrite else
                                                     b"a\nm\nz\n")
        assert await ws.cache.get("/a/input") == (b"a\nm\nz\n"
                                                  if overwrite else b"z\na\n")
        assert await ws.cache.get("/b/input") == b"m\n"
        assert result.reads["/b/input"] == b"m\n"
        left.load_state({"files": {"/input": b"changed\n"}})
        again = await ws.shell("cat /a/input" if overwrite else command)
        assert await again.materialize_stdout() == b"a\nm\nz\n"
    finally:
        await ws.close()

import pytest

from mirage.io.async_line_iterator import AsyncLineIterator
from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

COMMANDS = [
    "grep -c zzqqxx /data/tree/a.txt",
    "grep -ci zzqqxx /data/tree/a.txt",
    "grep -cE 'zzqqxx|qqzzyy' /data/tree/a.txt",
    r"grep -c 'zzqqxx\|qqzzyy' /data/tree/a.txt",
    "grep -c 'zz.qxx' /data/tree/a.txt",
    "grep -cw zzqqxx /data/tree/a.txt",
    "grep -ci -e zzqqxx -e qqzzyy /data/tree/a.txt",
    "grep -ril zzqqxx /data/tree",
    "grep -rlE 'zzqqxx|qqzzyy' /data/tree",
    "rg -c zzqqxx /data/tree/a.txt",
    "rg -ci zzqqxx /data/tree/a.txt",
    "rg -c 'zzqqxx|qqzzyy' /data/tree/a.txt",
    "rg -w zzqqxx /data/tree/a.txt",
    "rg -li 'zzqqxx|qqzzyy' /data/tree",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", COMMANDS)
async def test_shell_search_skips_nonmatching_blocks(command, monkeypatch):
    ram = RAMVFS()
    ram._store.dirs.update({"/", "/tree"})
    data = b"abcdefg\n" * 40000
    ram._store.files["/tree/a.txt"] = data
    ram._store.files["/tree/b.txt"] = data
    reads = 0
    read_until = AsyncLineIterator.read_until

    async def counted(self, delim):
        nonlocal reads
        reads += 1
        return await read_until(self, delim)

    monkeypatch.setattr(AsyncLineIterator, "read_until", counted)
    ws = Workspace({"/data": (ram, MountMode.WRITE)})
    try:
        io = await ws.shell(command)
        assert await io.stdout_str() == ("0\n" if "grep -c" in command else "")
        assert await io.stderr_str() == ""
        assert io.exit_code == 1
    finally:
        await ws.close()
    assert reads < 100

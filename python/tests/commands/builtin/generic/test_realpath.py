import json
from pathlib import Path

import pytest

from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

_ROOT = Path(__file__).parents[5]
_CASES = [
    case for case in json.loads(
        (_ROOT / "integ/unix/realpath/error.json").read_text())["cases"]
    if case["id"].startswith("realpath_review_")
] + [
    case for case in json.loads(
        (_ROOT / "integ/crossmount/nested/basic.json").read_text())["cases"]
    if case["id"].startswith("nest_realpath_")
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
async def test_gnu_realpath_cases(case):
    mounts = {"/data": RAMVFS()}
    if "ram-nested" in case["targets"]:
        mounts["/data/inner"] = RAMVFS()
    ws = Workspace(mounts, mode=MountMode.WRITE)
    try:
        io = await ws.shell(case["command"])
        assert io.exit_code == case["expect"]["exit"]
        assert await io.stdout_str() == case["expect"]["stdout"]
        assert await io.stderr_str() == case["expect"]["stderr"]
    finally:
        await ws.close()

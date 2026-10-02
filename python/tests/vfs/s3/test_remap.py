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

from mirage.commands.config import RegisteredCommand
from mirage.commands.spec import CommandSpec
from mirage.ops.registry import RegisteredOp
from mirage.types import VFSName
from mirage.vfs.s3.remap import remap_commands_vfs, remap_ops_vfs

# Mirrors typescript/packages/core/src/vfs/s3/remap.test.ts.


def _handler() -> None:
    return None


def _command(vfs: str) -> RegisteredCommand:
    return RegisteredCommand(
        name="cat", spec=CommandSpec(), vfs=vfs, filetype=None, fn=_handler
    )


def test_remap_ops_retags_only_s3_entries():
    s3 = RegisteredOp(name="read", vfs="s3", filetype=None, fn=_handler)
    ram = RegisteredOp(name="read", vfs="ram", filetype=None, fn=_handler)
    out = remap_ops_vfs([s3, ram], VFSName.R2)
    assert [ro.vfs for ro in out] == ["r2", "ram"]
    assert s3.vfs == "s3"
    assert out[1] is ram


def test_remap_commands_retags_only_s3_entries():
    s3, ram = _command("s3"), _command("ram")
    out = remap_commands_vfs([s3, ram], VFSName.R2)
    assert [rc.vfs for rc in out] == ["r2", "ram"]
    assert out[0] is not s3 and s3.vfs == "s3"
    assert out[1] is ram

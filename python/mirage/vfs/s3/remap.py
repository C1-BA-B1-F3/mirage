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

from dataclasses import replace

from mirage.commands.config import RegisteredCommand
from mirage.ops.registry import RegisteredOp
from mirage.types import VFSName


def remap_ops_vfs(ops: list[RegisteredOp], to: str) -> list[RegisteredOp]:
    """Rebind S3-registered ops to an S3-compatible alias name (gcs, r2,
    minio, wasabi, ...) so dispatch finds them under the alias VFS.

    Args:
        ops (list[RegisteredOp]): the S3 op table.
        to (str): the alias's VFS name.
    """
    return [replace(op, vfs=to) if op.vfs == VFSName.S3 else op for op in ops]


def remap_commands_vfs(
    commands: list[RegisteredCommand], to: str
) -> list[RegisteredCommand]:
    """Same as :func:`remap_ops_vfs` but for registered commands.

    Args:
        commands (list[RegisteredCommand]): the S3 command table.
        to (str): the alias's VFS name.
    """
    return [
        replace(rc, vfs=to) if rc.vfs == VFSName.S3 else rc for rc in commands
    ]

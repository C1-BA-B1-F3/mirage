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

import logging
import stat
from collections.abc import Iterator
from pathlib import Path

from mirage.core.disk.utils import resolve_inside_sync, walk_entries
from mirage.types import PathSpec

logger = logging.getLogger(__name__)


def size_sync(root: Path, spec: PathSpec) -> int:
    """Total visible file bytes, on the caller's worker thread.

    Args:
        root (Path): mount root.
        spec (PathSpec): virtual operand.
    """
    return sum(size for _, size in _file_sizes(root, spec))


def _file_sizes(root: Path, spec: PathSpec) -> Iterator[tuple[str, int]]:
    """Collect visible file sizes in one worker handoff.

    Missing operands total zero; unreadable trees fail instead of reporting
    a partial total. Symlinks are excluded by the shared enumeration policy.

    Args:
        root (Path): mount root.
        spec (PathSpec): virtual operand.
    """
    p = resolve_inside_sync(root, spec)
    try:
        info = p.stat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(info.st_mode):
        yield spec.mount_path, info.st_size
        return
    if not stat.S_ISDIR(info.st_mode):
        return
    for directory, _, filenames in walk_entries(p):
        for name in filenames:
            full = directory / name
            try:
                info = full.lstat()
            except FileNotFoundError:
                logger.debug("File vanished during disk traversal",
                             exc_info=True)
                continue
            if stat.S_ISREG(info.st_mode):
                yield "/" + full.relative_to(root).as_posix(), info.st_size


def entries_sync(root: Path,
                 spec: PathSpec) -> tuple[list[tuple[str, int]], int]:
    """Collect sorted file sizes and their total.

    Args:
        root (Path): mount root.
        spec (PathSpec): virtual operand.
    """
    found = sorted(_file_sizes(root, spec))
    return found, sum(size for _, size in found)

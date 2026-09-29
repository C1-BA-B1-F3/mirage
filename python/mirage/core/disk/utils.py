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
import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path

from mirage.core.disk.errors import disk_error
from mirage.types import PathSpec
from mirage.utils.errors import enoent

logger = logging.getLogger(__name__)


def resolve_inside_sync(root: Path,
                        spec: PathSpec,
                        path: str | None = None) -> Path:
    """Resolve an exact host operand without following links below the root.

    Missing components are left to the operation, allowing creates. The root
    itself may be an infrastructure symlink. This check is not atomic with
    subsequent I/O: protection against concurrent host replacement requires
    descriptor-relative operations with O_NOFOLLOW throughout.

    Call on a worker thread, or from a synchronous snapshot API. Async
    operations use resolve_inside, which hands the whole check to one worker.

    Args:
        root (Path): mount root on the host.
        spec (PathSpec): operand retained for virtual-path errors.
        path (str | None): alternate mount-relative key, otherwise spec's.
    """
    key = spec.mount_path if path is None else path
    base = os.path.abspath(root)
    full = os.path.normpath(os.path.join(base, key.lstrip("/")))
    prefix = base if base.endswith(os.sep) else base + os.sep
    if full != base and not full.startswith(prefix):
        raise ValueError(f"path escapes root: {spec.virtual}")
    at = base
    for part in full[len(base):].split(os.sep):
        if not part:
            continue
        at = os.path.join(at, part)
        try:
            info = os.lstat(at)
        except (FileNotFoundError, NotADirectoryError):
            return Path(full)
        except OSError as exc:
            raise disk_error(exc, spec.virtual) from exc
        if stat.S_ISLNK(info.st_mode):
            raise enoent(spec)
    return Path(full)


async def resolve_inside(root: Path,
                         spec: PathSpec,
                         path: str | None = None) -> Path:
    """Run the complete path check off the event loop.

    Args:
        root (Path): mount root on the host.
        spec (PathSpec): operand retained for virtual-path errors.
        path (str | None): alternate mount-relative key.
    """
    return await asyncio.to_thread(resolve_inside_sync, root, spec, path)


def read_entries(directory: Path) -> list[os.DirEntry[str]]:
    """List visible host entries using metadata that never follows links.

    All disk traversals use this policy. Errors propagate to the caller,
    which decides whether absence is expected or the traversal is incomplete.

    Args:
        directory (Path): checked host directory.
    """
    with os.scandir(directory) as listing:
        return [entry for entry in listing if not entry.is_symlink()]


def walk_entries(start: Path) -> Iterator[tuple[Path, list[str], list[str]]]:
    """Walk visible entries, allowing callers to prune the directory list.

    Args:
        start (Path): checked host directory.
    """
    pending = [start]
    while pending:
        directory = pending.pop()
        dirs: list[str] = []
        files: list[str] = []
        try:
            entries = read_entries(directory)
        except FileNotFoundError:
            logger.debug("Directory vanished during disk traversal",
                         exc_info=True)
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                dirs.append(entry.name)
            else:
                files.append(entry.name)
        yield directory, dirs, files
        pending.extend(directory / name for name in reversed(dirs))

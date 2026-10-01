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

import posixpath

from mirage.accessor.onedrive import OneDriveAccessor
from mirage.cache.context import invalidate_after_write, invalidate_ancestors
from mirage.core.msgraph.drive import create_child_folder
from mirage.core.onedrive.client import (GraphError, full_item_url, item_url,
                                         split_path)
from mirage.types import PathSpec


async def _create_root(accessor: OneDriveAccessor, prefix: str) -> None:
    """Create the mount's ``key_prefix`` folders, one level at a time.

    The mount root exists from the agent's side because it is mounted, but
    on the drive it is a folder chain nothing has created yet until the
    first write. A file upload creates its parents; a folder create does
    not, so mkdir has to.

    Args:
        accessor (OneDriveAccessor): the mount's accessor.
        prefix (str): the mount's key_prefix, stripped of slashes.
    """
    parent = ""
    for name in prefix.split("/"):
        await create_child_folder(accessor.config,
                                  full_item_url(accessor.config,
                                                parent,
                                                action="/children"),
                                  name,
                                  session=accessor.pool)
        parent = f"{parent}/{name}" if parent else name


async def _create_dir(accessor: OneDriveAccessor, stripped: str) -> None:
    parent = posixpath.dirname("/" + stripped).strip("/")
    url = item_url(accessor.config,
                   "/" + parent if parent else "/",
                   action="/children")
    name = posixpath.basename(stripped)
    try:
        await create_child_folder(accessor.config,
                                  url,
                                  name,
                                  session=accessor.pool)
    except GraphError as exc:
        prefix = (accessor.config.key_prefix or "").strip("/")
        if exc.status != 404 or parent or not prefix:
            raise
        await _create_root(accessor, prefix)
        await create_child_folder(accessor.config,
                                  url,
                                  name,
                                  session=accessor.pool)


async def mkdir(accessor: OneDriveAccessor,
                path: PathSpec,
                parents: bool = False) -> None:
    _, stripped = split_path(path)
    if not stripped:
        return
    if parents:
        parts = stripped.split("/")
        for i in range(len(parts)):
            await _create_dir(accessor, "/".join(parts[:i + 1]))
    else:
        await _create_dir(accessor, stripped)
    await invalidate_after_write(path)
    if parents:
        await invalidate_ancestors(path)

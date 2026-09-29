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

from stat import S_ISDIR

import aiofiles.os

from mirage.accessor.disk import DiskAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.core.disk.errors import disk_errors
from mirage.core.disk.utils import resolve_inside
from mirage.core.timeutil import epoch_to_iso
from mirage.types import FileStat, FileType, PathSpec
from mirage.utils.filetype import content_type_for_path


async def stat(accessor: DiskAccessor,
               path_spec: PathSpec,
               index: IndexCacheStore = NULL_INDEX) -> FileStat:
    virtual = path_spec.virtual
    root = accessor.root
    p = await resolve_inside(root, path_spec)
    # One stat, restamped: an existence check first would read ENOTDIR
    # (a path under a plain file) as plain absence.
    with disk_errors(virtual):
        st = await aiofiles.os.stat(p)
    modified = epoch_to_iso(st.st_mtime)
    # Fields setattr applies natively (mode, times) read from the real
    # inode, so external chmod/utime stays visible. Ownership can never
    # be applied natively (chown needs privileges), so it lives wholly
    # in the namespace overlay, merged at the stat-merge layer; host
    # uid/gid numbers would also be machine-dependent noise.
    if S_ISDIR(st.st_mode):
        return FileStat(name=p.name,
                        size=None,
                        modified=modified,
                        type=FileType.DIRECTORY,
                        mode=st.st_mode & 0o7777,
                        atime=epoch_to_iso(st.st_atime))
    return FileStat(name=p.name,
                    size=st.st_size,
                    modified=modified,
                    fingerprint=modified,
                    type=FileType.FILE,
                    content=content_type_for_path(p.name),
                    mode=st.st_mode & 0o7777,
                    atime=epoch_to_iso(st.st_atime))

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

from mirage.accessor.gslides import GSlidesAccessor
from mirage.cache.index import IndexCacheStore
from mirage.core.google.entry import resolve_app_entry
from mirage.core.gslides.constants import MIME
from mirage.core.gslides.readdir import readdir
from mirage.core.gslides.scope import detect_scope
from mirage.core.hierarchy.scope import ScopeMatch
from mirage.core.hierarchy.stat import make_stat
from mirage.types import ContentType, FileStat, FileType, PathSpec
from mirage.vfs.gslides.slide_entry import make_filename


async def _file_stat(
    accessor: GSlidesAccessor,
    match: ScopeMatch,
    path: PathSpec,
    index: IndexCacheStore,
) -> FileStat:
    entry = await resolve_app_entry(
        accessor.token_manager,
        match,
        path,
        index,
        MIME,
        "gslides/file",
        make_filename,
    )
    return FileStat(
        name=entry.vfs_name,
        type=FileType.FILE,
        content=ContentType.JSON,
        modified=entry.remote_time,
        size=entry.size,
        fingerprint=entry.remote_time or None,
        extra={
            "doc_id": entry.id,
            "doc_name": entry.name,
            **entry.extra,
        },
    )


stat = make_stat(detect_scope, readdir, overrides={"file": _file_stat})

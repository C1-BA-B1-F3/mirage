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
from mirage.core.gslides.client import TokenManager, google_get, slides_base
from mirage.core.gslides.constants import MIME
from mirage.core.gslides.scope import detect_scope
from mirage.core.hierarchy.read import make_read
from mirage.core.hierarchy.scope import ScopeMatch
from mirage.core.render.json import compact_json_bytes
from mirage.observe.context import record, start_op
from mirage.types import PathSpec
from mirage.vfs.gslides.slide_entry import make_filename


async def read_presentation(
    token_manager: TokenManager, presentation_id: str
) -> bytes:
    url = f"{slides_base(token_manager)}/presentations/{presentation_id}"
    data = await google_get(token_manager, url)
    return compact_json_bytes(data)


async def _read_file(
    accessor: GSlidesAccessor,
    match: ScopeMatch,
    path: PathSpec,
    index: IndexCacheStore,
) -> bytes:
    entry = await resolve_app_entry(
        accessor.token_manager,
        match,
        path,
        index,
        MIME,
        "gslides/file",
        make_filename,
    )
    timer = start_op()
    data = await read_presentation(accessor.token_manager, entry.id)
    record(
        "read",
        path.virtual,
        "gslides",
        len(data),
        timer,
        fingerprint=entry.remote_time or None,
    )
    return data


read = make_read(detect_scope, readers={"file": _read_file})

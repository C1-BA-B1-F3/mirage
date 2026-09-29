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

from mirage.core.hierarchy.search import make_search_op
from mirage.core.langfuse.read import read as _read
from mirage.core.langfuse.readdir import readdir as _readdir
from mirage.core.langfuse.scope import detect_scope
from mirage.core.langfuse.search import SEARCHERS
from mirage.core.langfuse.stat import stat as _stat
from mirage.vfs.adapter import VFSAdapter
from mirage.vfs.types import ReadOps, SearchOps

# Langfuse traces/observations/sessions/prompts are read through the generic
# factory (find walks readdir, classifying via stat); grep and rg keep
# wrappers that use the adapter's core searchers, which filter the list
# endpoints client-side (trace summaries, session ids, prompt and dataset
# names); there is no server-side search. Langfuse is read-only, so the
# generic byte-mutation commands are intentionally absent (no write op wired).
IO = VFSAdapter(search=SearchOps(search=make_search_op(detect_scope,
                                                       SEARCHERS),
                                 meta={"grep": {
                                     "mode": "regex"
                                 }}),
                read=ReadOps(readdir=_readdir, read_bytes=_read, stat=_stat),
                is_mounted=lambda a: True,
                local=False).to_command_io()

resolve_glob = IO.resolve_glob

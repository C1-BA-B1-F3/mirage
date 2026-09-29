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

from mirage.core.qdrant.read import read as _read
from mirage.core.qdrant.readdir import readdir as _readdir
from mirage.core.qdrant.search import search_many, search_resource
from mirage.core.qdrant.stat import stat as _stat
from mirage.vfs.adapter import VFSAdapter
from mirage.vfs.types import ReadOps, SearchOps

# Qdrant points are read through the generic factory (find walks readdir,
# classifying via stat); search pushes down to the Qdrant query API.
# Qdrant is read-only, so the generic
# byte-mutation commands are intentionally absent (no write op wired). There is
# no native streaming read, so the stream op is synthesized from the whole-row
# read.
IO = VFSAdapter(search=SearchOps(search=search_resource,
                                 search_many=search_many),
                read=ReadOps(readdir=_readdir, read_bytes=_read, stat=_stat),
                is_mounted=lambda a: True,
                local=False).to_command_io()

resolve_glob = IO.resolve_glob

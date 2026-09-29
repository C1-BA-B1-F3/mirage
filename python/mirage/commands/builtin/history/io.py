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

from mirage.core.history.find import find
from mirage.core.history.read import read as _read
from mirage.core.history.readdir import readdir as _readdir
from mirage.core.history.stat import stat as _stat
from mirage.vfs.adapter import VFSAdapter
from mirage.vfs.types import NativeReadOps, ReadOps

# The history view is read-only (the recorder owns mutation), so only the
# read trio is wired; the history commands themselves stay bespoke. There is
# no native streaming read, so the stream op is synthesized from the whole
# rendered histfile.
IO = VFSAdapter(read=ReadOps(readdir=_readdir, read_bytes=_read, stat=_stat),
                native=NativeReadOps(find=find),
                is_mounted=lambda a: True,
                local=False).to_command_io()

resolve_glob = IO.resolve_glob

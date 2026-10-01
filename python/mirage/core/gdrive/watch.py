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

from functools import partial

from mirage.accessor.gdrive import GDriveAccessor
from mirage.core.gdrive.readdir import readdir
from mirage.core.gdrive.stat import stat
from mirage.watch.base import DeltaHook
from mirage.watch.delta import ListingDeltaHook
from mirage.watch.walk import ReaddirWalk


def build_delta_hook(accessor: GDriveAccessor) -> DeltaHook:
    """Build the Google Drive delta hook.

    Drive addresses files by id and returns ``parents`` rather than
    paths, so a whole-corpus ``files.list`` would still have to rebuild
    the tree before it could name anything; the walk descends per folder
    instead, which is the same shape ``find`` already uses here.

    Fingerprints on ``modifiedTime``, which is what Drive stat reports.
    Drive also has ``changes.list`` with a page token, an account-wide
    feed that is cheaper than any walk and would have to be filtered
    back down to the watch root; that belongs behind ``pull`` as a fast
    path, with this walk as its reset.

    Args:
        accessor (GDriveAccessor): Backend handle.
    """
    return ListingDeltaHook(
        ReaddirWalk(partial(readdir, accessor), partial(stat, accessor))
    )

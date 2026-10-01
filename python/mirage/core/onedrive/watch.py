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

from mirage.accessor.onedrive import OneDriveAccessor
from mirage.core.onedrive.readdir import readdir
from mirage.core.onedrive.stat import stat
from mirage.watch.base import DeltaHook
from mirage.watch.delta import ListingDeltaHook
from mirage.watch.walk import ReaddirWalk


def build_delta_hook(accessor: OneDriveAccessor) -> DeltaHook:
    """Build the OneDrive delta hook.

    Fingerprints on the item's ``cTag``, which Graph moves only when the
    content changes (``eTag`` also moves on a metadata edit), so a
    rename does not read as a content change.

    Graph has a native ``/delta`` feed with a resumable token, which is
    cheaper than this walk and reports deletes directly. It is a fast
    path rather than a replacement: Graph can answer ``resyncRequired``
    at any time, and the only response to that is a full listing. When
    it is added it belongs behind ``pull``, with this walk as its reset.

    Args:
        accessor (OneDriveAccessor): Backend handle.
    """
    return ListingDeltaHook(
        ReaddirWalk(partial(readdir, accessor), partial(stat, accessor))
    )

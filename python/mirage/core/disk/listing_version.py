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

import os
from pathlib import Path
from time import time_ns

from mirage.core.disk.constants import RACY_WINDOW_NS


def wall_ns() -> int:
    """The wall clock a folder version is judged against, in nanoseconds."""
    return time_ns()


def stamp(st: os.stat_result, now_ns: int) -> str | None:
    """The listing version of a folder, from its stat.

    A disk listing holds only names and types, and every add, rename or
    remove inside a folder moves that folder's change time, so the folder's
    own stat covers its listing. The inode and device catch a folder made
    again or a filesystem mounted over it; the mtime covers a platform
    whose ``st_ctime`` is a creation time. A folder changed less than
    ``RACY_WINDOW_NS`` before ``now_ns`` gets no version, since a second
    change within one timestamp tick would leave it unmoved.

    Args:
        st (os.stat_result): the folder's stat, links followed.
        now_ns (int): the wall clock, read before the stat.

    Returns:
        str | None: ``dev:ino:ctime_ns:mtime_ns``, or None while the
            folder is still settling.
    """
    if now_ns - max(st.st_ctime_ns, st.st_mtime_ns) < RACY_WINDOW_NS:
        return None
    return f"{st.st_dev}:{st.st_ino}:{st.st_ctime_ns}:{st.st_mtime_ns}"


def folder_version(path: Path, now_ns: int) -> str | None:
    """Stat a host folder and return its listing version.

    Args:
        path (Path): the host folder, already checked by ``resolve_inside``.
        now_ns (int): the wall clock, read before this call.

    Returns:
        str | None: see :func:`stamp`.
    """
    return stamp(os.stat(path), now_ns)

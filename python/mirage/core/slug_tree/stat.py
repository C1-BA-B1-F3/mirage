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

from mirage.core.slug_tree.rows import mount_root
from mirage.core.slug_tree.types import ResolvedDirectory
from mirage.types import FileStat, FileType


def directory_stat(resolved: ResolvedDirectory) -> FileStat:
    """Stat a folder of the tree, which exists only as its listing.

    Args:
        resolved (ResolvedDirectory): the resolved folder.
    """
    key = resolved.virtual_key
    name = ("/" if key == mount_root(resolved.mount_prefix) else
            key.rstrip("/").rsplit("/", 1)[-1])
    return FileStat(name=name,
                    type=FileType.DIRECTORY,
                    extra={"children_count": 0})

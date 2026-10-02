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

from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_prefix_of


def raw_path_of(path: PathSpec) -> str:
    """The path below the mount prefix, spelled as the virtual path is.

    Args:
        path (PathSpec): a path on a nextcloud mount.

    Returns:
        str: ``/`` for the mount root, else the slash-led remainder with
        any trailing slash kept.
    """
    prefix = mount_prefix_of(path.virtual, path.vfs_path)
    if prefix and path.virtual.startswith(prefix):
        return path.virtual[len(prefix) :] or "/"
    return path.virtual


def nextcloud_key(path: PathSpec) -> str:
    """The WebDAV key opendal addresses a path by.

    Args:
        path (PathSpec): a path on a nextcloud mount.

    Returns:
        str: ``raw_path_of(path)`` without its leading slash.
    """
    return raw_path_of(path).lstrip("/")

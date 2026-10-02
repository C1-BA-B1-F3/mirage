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

import struct


def pack_dirent(index: int, name: bytes, filetype: int) -> bytes:
    """Encode one fd_readdir entry; d_next/d_ino are the entry index + 1.

    Args:
        index (int): zero-based position of the entry in the listing.
        name (bytes): entry name, already encoded.
        filetype (int): preview1 filetype, FT_UNKNOWN when not known.
    """
    return (
        struct.pack("<QQIBxxx", index + 1, index + 1, len(name), filetype)
        + name
    )

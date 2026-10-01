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

from mirage.runtime.wasm.constants import FT_DIR, FT_REG
from mirage.runtime.wasm.list import pack_dirent


def test_dirent_record_is_the_preview1_layout_plus_the_name():
    assert len(pack_dirent(0, b"abc", FT_DIR)) == 24 + 3


def test_dirent_carries_cookie_name_and_type():
    d_next, d_ino, namelen, ftype = struct.unpack_from(
        "<QQIB", pack_dirent(4, b"f.txt", FT_REG)
    )
    assert (d_next, d_ino, namelen, ftype) == (5, 5, 5, FT_REG)
    assert pack_dirent(4, b"f.txt", FT_REG)[24:] == b"f.txt"

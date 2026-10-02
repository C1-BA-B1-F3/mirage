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
from hashlib import blake2b

from mirage.runtime.python.host.constants import BLKSIZE


def ident(text: str) -> int:
    """A stable, distinct id for one name.

    ``os.path.samefile`` compares (st_dev, st_ino) pairs and
    ``os.path.ismount`` compares a path's pair with its parent's, so
    reporting zero for both would make every mounted file the same file
    and every mount root invisible. Derived from the name rather than
    counted, so two processes reading the same workspace agree and a
    repeated stat of one path does not move.

    Args:
        text (str): the virtual path or mount prefix to identify.
    """
    return int.from_bytes(
        blake2b(text.encode(), digest_size=7).digest(), "big"
    )


def stat_result(
    virtual: str,
    prefix: str,
    mode: int,
    size: int,
    nlink: int,
    uid: int,
    gid: int,
    access: float,
    stamp: float,
) -> os.stat_result:
    """One `os.stat_result`, every field resolved.

    Every optional field is filled explicitly, because built from a
    plain 10-tuple they come back None while still answering
    ``hasattr``: ``shutil.copystat`` reads ``st_flags`` that way and
    handed the host's chflags a None, and ``pathlib`` reads the
    ``_ns`` pair. A key the platform has no such field for
    (``st_flags`` off BSD) is dropped by the constructor, so the
    result carries exactly what a real stat there would.

    Args:
        virtual (str): the path being statted (the inode's name).
        prefix (str): the mount owning it (the device's name).
        mode (int): st_mode, type bits included.
        size (int): st_size.
        nlink (int): st_nlink.
        uid (int): st_uid.
        gid (int): st_gid.
        access (float): access time.
        stamp (float): modification and change time.
    """
    return os.stat_result(
        (
            mode,
            ident(virtual),
            ident(prefix),
            nlink,
            uid,
            gid,
            size,
            int(access),
            int(stamp),
            int(stamp),
        ),
        {
            "st_atime": access,
            "st_mtime": stamp,
            "st_ctime": stamp,
            "st_atime_ns": int(access * 1_000_000_000),
            "st_mtime_ns": int(stamp * 1_000_000_000),
            "st_ctime_ns": int(stamp * 1_000_000_000),
            "st_birthtime": stamp,
            "st_blksize": BLKSIZE,
            "st_blocks": -(-size // 512),
            "st_rdev": 0,
            "st_flags": 0,
            "st_gen": 0,
        },
    )

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

import errno

import asyncssh
import pytest

from mirage.accessor.ssh import SSHAccessor
from mirage.core.ssh.config import SSHConfig
from mirage.core.ssh.rmdir import rmdir
from mirage.types import PathSpec


class _FakeSFTP:
    """Just enough of asyncssh's SFTPClient for rmdir.

    Args:
        refusal (Exception | None): what rmdir raises; None removes.
        names (list[str] | None): what listdir reports beside the dot
            entries; None makes the probe itself fail.
    """

    def __init__(
        self, refusal: Exception | None, names: list[str] | None
    ) -> None:
        self.refusal = refusal
        self.names = names
        self.removed: list[str] = []
        self.listed: list[str] = []

    async def rmdir(self, remote: str) -> None:
        if self.refusal is not None:
            raise self.refusal
        self.removed.append(remote)

    async def listdir(self, remote: str) -> list[str]:
        self.listed.append(remote)
        if self.names is None:
            raise asyncssh.SFTPNoSuchFile("No such file")
        return [".", "..", *self.names]


def _accessor(sftp: _FakeSFTP) -> SSHAccessor:
    accessor = SSHAccessor(SSHConfig(host="example.test"))
    accessor._sftp = sftp
    return accessor


@pytest.mark.asyncio
async def test_rmdir_removes_and_reports_nothing():
    sftp = _FakeSFTP(None, [])
    await rmdir(_accessor(sftp), PathSpec.from_str_path("/d"))
    assert len(sftp.removed) == 1
    assert sftp.listed == []


@pytest.mark.asyncio
async def test_a_typed_not_empty_maps_to_enotempty():
    sftp = _FakeSFTP(asyncssh.SFTPDirNotEmpty("Directory not empty"), ["h"])
    with pytest.raises(OSError) as exc:
        await rmdir(_accessor(sftp), PathSpec.from_str_path("/d"))
    assert exc.value.errno == errno.ENOTEMPTY


@pytest.mark.asyncio
async def test_a_version_3_not_empty_refusal_converts_to_enotempty():
    # OpenSSH speaks SFTP 3, whose one generic code covers not-empty;
    # the listing probe is what tells it apart, and without the
    # conversion the hidden-remnant guard never fires on ssh.
    sftp = _FakeSFTP(asyncssh.SFTPFailure("Failure"), ["h"])
    with pytest.raises(OSError) as exc:
        await rmdir(_accessor(sftp), PathSpec.from_str_path("/d"))
    assert exc.value.errno == errno.ENOTEMPTY
    assert len(sftp.listed) == 1


@pytest.mark.asyncio
async def test_a_version_3_failure_on_an_empty_listing_stays_itself():
    # The generic code covers refusals beyond not-empty; a directory
    # the probe shows empty keeps the server's own answer.
    sftp = _FakeSFTP(asyncssh.SFTPFailure("Failure"), [])
    with pytest.raises(asyncssh.SFTPFailure):
        await rmdir(_accessor(sftp), PathSpec.from_str_path("/d"))


@pytest.mark.asyncio
async def test_a_version_3_failure_with_a_failing_probe_stays_itself():
    # A probe that fails is a negative probe: the server's answer
    # stands, nothing is swallowed.
    sftp = _FakeSFTP(asyncssh.SFTPFailure("Failure"), None)
    with pytest.raises(asyncssh.SFTPFailure):
        await rmdir(_accessor(sftp), PathSpec.from_str_path("/d"))

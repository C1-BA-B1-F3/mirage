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

import stat
from pathlib import Path

import asyncssh

from mirage.server.ssh.keys import HOST_KEY_ALGORITHM, load_host_key


def _public(key: asyncssh.SSHKey) -> bytes:
    return key.export_public_key()


def test_first_load_mints_an_owner_only_key(tmp_path):
    path = tmp_path / "ssh" / "host_key"
    key = load_host_key(path)
    assert key.get_algorithm() == HOST_KEY_ALGORITHM
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_later_loads_keep_the_same_key(tmp_path):
    path = tmp_path / "host_key"
    first = load_host_key(path)
    assert _public(load_host_key(path)) == _public(first)


def test_an_existing_key_is_read_not_replaced(tmp_path):
    path = tmp_path / "host_key"
    mine = asyncssh.generate_private_key("ssh-ed25519")
    path.write_bytes(mine.export_private_key())
    assert _public(load_host_key(path)) == _public(mine)


def test_losing_the_mint_race_reads_the_winner(tmp_path, monkeypatch):
    path = tmp_path / "host_key"
    winner = asyncssh.generate_private_key("ssh-ed25519")
    path.write_bytes(winner.export_private_key())
    real_exists = Path.exists
    monkeypatch.setattr(
        Path, "exists", lambda self: False
        if self == path else real_exists(self))
    assert _public(load_host_key(path)) == _public(winner)

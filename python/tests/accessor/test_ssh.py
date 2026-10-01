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

from mirage.accessor.ssh import _connect_kwargs
from mirage.core.ssh.config import SSHConfig


def test_connect_kwargs_overrides():
    cfg = SSHConfig(
        host="dev",
        hostname="10.0.0.1",
        port=2222,
        username="admin",
        identity_file="~/.ssh/custom.pem",
    )
    kw = _connect_kwargs(cfg)
    assert kw["host"] == "10.0.0.1"
    assert kw["port"] == 2222
    assert kw["username"] == "admin"


def test_connect_kwargs_defaults():
    kw = _connect_kwargs(SSHConfig(host="dev"))
    assert kw["host"] == "dev"
    assert "port" not in kw
    assert "username" not in kw
    assert kw["known_hosts"] is None
    assert kw["login_timeout"] == 30


def test_connect_kwargs_password_and_passphrase():
    cfg = SSHConfig(
        host="dev", password="pw", identity_file="~/k", passphrase="pp"
    )
    kw = _connect_kwargs(cfg)
    assert kw["password"] == "pw"
    assert kw["passphrase"] == "pp"


def test_connect_kwargs_passphrase_rides_the_identity_file():
    kw = _connect_kwargs(SSHConfig(host="dev", passphrase="pp"))
    assert "passphrase" not in kw
    assert "password" not in kw

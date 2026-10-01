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

import pytest
from pydantic import ValidationError

from mirage.vfs.nextcloud.config import NextcloudConfig


def test_nextcloudconfig_defaults():
    c = NextcloudConfig(
        url="https://cloud.example.com/remote.php/dav/files/user/"
    )
    assert c.username is None
    assert c.password is None
    assert c.verify_ssl is True
    assert c.timeout == 30


def test_nextcloudconfig_immutable():
    c = NextcloudConfig(
        url="https://cloud.example.com/remote.php/dav/files/user/"
    )
    with pytest.raises(ValidationError):
        c.url = "https://other.example.com/"


def test_nextcloudconfig_with_credentials():
    c = NextcloudConfig(
        url="https://cloud.example.com/remote.php/dav/files/user/",
        username="alice",
        password="secret",
        verify_ssl=False,
    )
    assert c.username == "alice"
    assert c.password == "secret"
    assert c.verify_ssl is False

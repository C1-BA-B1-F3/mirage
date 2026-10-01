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
from pydantic import SecretStr, ValidationError

from mirage.core.google.client import TokenManager
from mirage.core.google.config import GoogleConfig


@pytest.mark.asyncio
async def test_a_supplied_token_skips_the_refresh_grant(monkeypatch):
    # A service account can mint an access token but has no refresh
    # token, so before this the only way in was to monkeypatch
    # refresh_access_token.
    async def _boom(config):
        raise AssertionError("refresh grant must not run")

    monkeypatch.setattr(
        "mirage.core.google.client.refresh_access_token", _boom
    )
    config = GoogleConfig(access_token=SecretStr("sa-token"))
    assert await TokenManager(config).get_token() == "sa-token"


@pytest.mark.asyncio
async def test_a_provider_is_called_every_request():
    # The provider owns the refresh, so caching its answer here would
    # outlive the rotation it just performed.
    tokens = iter(["tok-1", "tok-2", "tok-3"])
    manager = TokenManager(GoogleConfig(access_token=lambda: next(tokens)))
    assert [await manager.get_token() for _ in range(3)] == [
        "tok-1",
        "tok-2",
        "tok-3",
    ]


@pytest.mark.asyncio
async def test_a_provider_may_answer_with_a_secret():
    manager = TokenManager(
        GoogleConfig(access_token=lambda: SecretStr("wrapped"))
    )
    assert await manager.get_token() == "wrapped"


def test_the_refresh_grant_is_still_accepted():
    config = GoogleConfig(client_id="cid", refresh_token=SecretStr("rt"))
    assert config.access_token is None


def test_naming_no_credential_is_refused():
    with pytest.raises(ValidationError, match="either access_token"):
        GoogleConfig(api_base="http://localhost:1")

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

import time
from unittest.mock import AsyncMock, patch

import pytest

from mirage.core.google.client import TokenManager, google_headers
from mirage.core.google.config import GoogleConfig


@pytest.fixture
def config():
    return GoogleConfig(
        client_id="test-id",
        client_secret="test-secret",
        refresh_token="test-refresh",
    )


@pytest.mark.asyncio
async def test_token_manager_refreshes_on_first_call(config):
    mgr = TokenManager(config)
    with patch(
        "mirage.core.google.client.refresh_access_token",
        new_callable=AsyncMock,
        return_value=("new-token", 3600),
    ) as mock_refresh:
        token = await mgr.get_token()
        assert token == "new-token"
        mock_refresh.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_token_manager_caches_token(config):
    mgr = TokenManager(config)
    with patch(
        "mirage.core.google.client.refresh_access_token",
        new_callable=AsyncMock,
        return_value=("cached-token", 3600),
    ) as mock_refresh:
        t1 = await mgr.get_token()
        t2 = await mgr.get_token()
        assert t1 == t2 == "cached-token"
        assert mock_refresh.call_count == 1


@pytest.mark.asyncio
async def test_token_manager_refreshes_when_expired(config):
    mgr = TokenManager(config)
    with patch(
        "mirage.core.google.client.refresh_access_token",
        new_callable=AsyncMock,
        return_value=("token-1", 3600),
    ):
        await mgr.get_token()

    mgr._expires_at = time.time() - 1

    with patch(
        "mirage.core.google.client.refresh_access_token",
        new_callable=AsyncMock,
        return_value=("token-2", 3600),
    ):
        token = await mgr.get_token()
        assert token == "token-2"


@pytest.mark.asyncio
async def test_google_headers(config):
    mgr = TokenManager(config)
    with patch(
        "mirage.core.google.client.refresh_access_token",
        new_callable=AsyncMock,
        return_value=("my-token", 3600),
    ):
        headers = await google_headers(mgr)
        assert headers["Authorization"] == "Bearer my-token"

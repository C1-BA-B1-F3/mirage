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

from unittest.mock import AsyncMock, patch

import pytest

from mirage.core.gmail.labels import list_labels
from mirage.core.google.client import TokenManager
from mirage.core.google.config import GoogleConfig


@pytest.fixture
def token_manager():
    config = GoogleConfig(
        client_id="test-id",
        client_secret="test-secret",
        refresh_token="test-refresh",
    )
    mgr = TokenManager(config)
    mgr._access_token = "fake-token"
    mgr._expires_at = 9999999999
    return mgr


@pytest.mark.asyncio
async def test_list_labels(token_manager):
    api_response = {
        "labels": [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "Label_1", "name": "Work", "type": "user"},
        ]
    }
    with patch(
        "mirage.core.gmail.labels.google_get",
        new_callable=AsyncMock,
        return_value=api_response,
    ):
        result = await list_labels(token_manager)
        assert len(result) == 2
        assert result[0]["id"] == "INBOX"
        assert result[1]["name"] == "Work"


@pytest.mark.asyncio
async def test_list_labels_empty(token_manager):
    with patch(
        "mirage.core.gmail.labels.google_get",
        new_callable=AsyncMock,
        return_value={},
    ):
        result = await list_labels(token_manager)
        assert result == []

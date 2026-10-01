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

import base64
from unittest.mock import AsyncMock, patch

import pytest

from mirage.core.gmail.send import forward_message, reply_message, send_message
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
async def test_send_message(token_manager):
    with patch(
        "mirage.core.gmail.send.google_post",
        new_callable=AsyncMock,
        return_value={"id": "sent1", "threadId": "t1"},
    ) as mock_post:
        result = await send_message(
            token_manager, "bob@example.com", "Hello", "Hi Bob!"
        )
        assert result["id"] == "sent1"
        call_args = mock_post.call_args
        payload = call_args[0][2]
        assert "raw" in payload


@pytest.mark.asyncio
async def test_reply_message(token_manager):
    raw_msg = {
        "id": "msg1",
        "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "Subject", "value": "Hello"},
                {"name": "Message-ID", "value": "<abc@example.com>"},
            ],
        },
    }
    with (
        patch(
            "mirage.core.gmail.send.get_message_raw",
            new_callable=AsyncMock,
            return_value=raw_msg,
        ),
        patch(
            "mirage.core.gmail.send.google_post",
            new_callable=AsyncMock,
            return_value={"id": "reply1", "threadId": "t1"},
        ) as mock_post,
    ):
        result = await reply_message(token_manager, "msg1", "Thanks!")
        assert result["id"] == "reply1"
        payload = mock_post.call_args[0][2]
        assert payload["threadId"] == "t1"


@pytest.mark.asyncio
async def test_forward_message(token_manager):
    body_encoded = base64.urlsafe_b64encode(b"Original body").decode()
    raw_msg = {
        "id": "msg1",
        "threadId": "t1",
        "snippet": "Original body",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": body_encoded},
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "To", "value": "bob@example.com"},
                {"name": "Subject", "value": "Hello"},
                {"name": "Date", "value": "Mon, 1 Apr 2026"},
            ],
        },
    }
    with (
        patch(
            "mirage.core.gmail.messages.google_get",
            new_callable=AsyncMock,
            return_value=raw_msg,
        ),
        patch(
            "mirage.core.gmail.send.google_post",
            new_callable=AsyncMock,
            return_value={"id": "fwd1"},
        ),
    ):
        result = await forward_message(
            token_manager, "msg1", "charlie@example.com"
        )
        assert result["id"] == "fwd1"

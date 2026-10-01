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

from mirage.core.gmail.messages import (
    _decode_body,
    _extract_header,
    _parse_address,
    _parse_address_list,
    get_message_processed,
    get_message_raw,
    list_messages,
)
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


def test_extract_header():
    headers = [
        {"name": "From", "value": "alice@example.com"},
        {"name": "Subject", "value": "Hello"},
    ]
    assert _extract_header(headers, "From") == "alice@example.com"
    assert _extract_header(headers, "subject") == "Hello"
    assert _extract_header(headers, "Missing") == ""


def test_parse_address_with_name():
    result = _parse_address('"Alice Smith" <alice@example.com>')
    assert result["name"] == "Alice Smith"
    assert result["email"] == "alice@example.com"


def test_parse_address_email_only():
    result = _parse_address("alice@example.com")
    assert result["name"] == ""
    assert result["email"] == "alice@example.com"


def test_parse_address_list():
    result = _parse_address_list("alice@example.com, Bob <bob@example.com>")
    assert len(result) == 2
    assert result[0]["email"] == "alice@example.com"
    assert result[1]["email"] == "bob@example.com"


def test_parse_address_list_empty():
    assert _parse_address_list("") == []


def test_decode_body_plain():
    import base64

    text = "Hello, world!"
    encoded = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    payload = {
        "mimeType": "text/plain",
        "body": {"data": encoded},
    }
    assert _decode_body(payload) == text


def test_decode_body_multipart():
    import base64

    text = "Nested text"
    encoded = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {
                "mimeType": "text/plain",
                "body": {"data": encoded},
            },
        ],
    }
    assert _decode_body(payload) == text


def test_decode_body_empty():
    payload = {"mimeType": "text/html", "body": {"data": ""}}
    assert _decode_body(payload) == ""


@pytest.mark.asyncio
async def test_list_messages(token_manager):
    api_response = {
        "messages": [
            {"id": "msg1", "threadId": "t1"},
            {"id": "msg2", "threadId": "t2"},
        ]
    }
    with patch(
        "mirage.core.gmail.messages.google_get",
        new_callable=AsyncMock,
        return_value=api_response,
    ):
        result = await list_messages(token_manager, label_id="INBOX")
        assert len(result) == 2
        assert result[0]["id"] == "msg1"


@pytest.mark.asyncio
async def test_get_message_raw(token_manager):
    msg = {"id": "msg1", "payload": {"headers": []}}
    with patch(
        "mirage.core.gmail.messages.google_get",
        new_callable=AsyncMock,
        return_value=msg,
    ):
        result = await get_message_raw(token_manager, "msg1")
        assert result["id"] == "msg1"


@pytest.mark.asyncio
async def test_get_message_processed(token_manager):
    import base64

    body_text = "Hello!"
    encoded = base64.urlsafe_b64encode(body_text.encode()).decode().rstrip("=")
    msg = {
        "id": "msg1",
        "threadId": "t1",
        "snippet": "Hello!",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": encoded},
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "To", "value": "bob@example.com"},
                {"name": "Subject", "value": "Test"},
                {"name": "Date", "value": "Mon, 1 Apr 2026 00:00:00 +0000"},
            ],
        },
    }
    with patch(
        "mirage.core.gmail.messages.google_get",
        new_callable=AsyncMock,
        return_value=msg,
    ):
        result = await get_message_processed(token_manager, "msg1")
        assert result["id"] == "msg1"
        assert result["subject"] == "Test"
        assert result["body_text"] == body_text
        assert result["from"]["email"] == "alice@example.com"
        assert result["attachments"] == []


@pytest.mark.asyncio
async def test_get_message_processed_includes_attachment_paths(token_manager):
    msg = {
        "id": "msg2",
        "threadId": "t2",
        "labelIds": [],
        "snippet": "",
        "payload": {
            "headers": [{"name": "Subject", "value": "With Attach"}],
            "parts": [
                {
                    "filename": "invoice.pdf",
                    "mimeType": "application/pdf",
                    "body": {
                        "attachmentId": "att-xyz",
                        "size": 4096,
                    },
                }
            ],
        },
    }
    with patch(
        "mirage.core.gmail.messages.google_get",
        new_callable=AsyncMock,
        return_value=msg,
    ):
        result = await get_message_processed(token_manager, "msg2")
        assert result["attachments"] == [
            {
                "id": "att-xyz",
                "filename": "invoice.pdf",
                "path": "attachments/att-xyz_invoice.pdf",
                "mime_type": "application/pdf",
                "size": 4096,
            }
        ]

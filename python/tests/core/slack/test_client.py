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
from aioresponses import aioresponses
from yarl import URL

from mirage.core.slack.client import slack_get, slack_post
from mirage.core.slack.config import SlackConfig

BASE = "https://slack.com/api"


@pytest.fixture
def config():
    return SlackConfig(token="xoxb-test-token")


@pytest.mark.asyncio
async def test_slack_get_success(config):
    url = f"{BASE}/conversations.list?limit=10"
    with aioresponses() as m:
        m.get(url, payload={"ok": True, "channels": []})
        result = await slack_get(
            config, "conversations.list", params={"limit": 10}
        )
        sent = m.requests[("GET", URL(url))]
    assert result["ok"] is True
    assert len(sent) == 1
    assert (
        sent[0].kwargs["headers"]["Authorization"] == "Bearer xoxb-test-token"
    )


@pytest.mark.asyncio
async def test_slack_get_uses_search_token_for_search_methods():
    config = SlackConfig(token="xoxb-bot", search_token="xoxp-user")
    url = f"{BASE}/search.messages?query=hello"
    with aioresponses() as m:
        m.get(url, payload={"ok": True, "messages": {"matches": []}})
        result = await slack_get(
            config, "search.messages", params={"query": "hello"}
        )
        sent = m.requests[("GET", URL(url))]
    assert result["ok"] is True
    assert sent[0].kwargs["headers"]["Authorization"] == "Bearer xoxp-user"


@pytest.mark.asyncio
async def test_slack_get_error(config):
    # Slack reports failures in-band: HTTP 200 with ok:false.
    url = f"{BASE}/conversations.info"
    with aioresponses() as m:
        m.get(url, payload={"ok": False, "error": "channel_not_found"})
        with pytest.raises(
            RuntimeError, match=r"\(conversations\.info\): channel_not_found"
        ):
            await slack_get(config, "conversations.info")


@pytest.mark.asyncio
async def test_slack_get_http_error_keeps_slack_wording(config):
    # A non-2xx that still carries Slack's envelope keeps Slack's own
    # error string rather than a bare status line.
    url = f"{BASE}/conversations.info"
    with aioresponses() as m:
        m.get(
            url,
            status=429,
            payload={
                "ok": False,
                "error": "ratelimited",
            },
        )
        with pytest.raises(
            RuntimeError, match=r"\(conversations\.info\): ratelimited"
        ):
            await slack_get(config, "conversations.info")


@pytest.mark.asyncio
async def test_slack_get_http_error_without_envelope_reports_status(config):
    url = f"{BASE}/conversations.info"
    with aioresponses() as m:
        m.get(url, status=502, body="<html>gateway</html>")
        with pytest.raises(
            RuntimeError, match=r"\(conversations\.info\): HTTP 502"
        ):
            await slack_get(config, "conversations.info")


@pytest.mark.asyncio
async def test_slack_get_missing_scope_surfaces_scopes(config):
    url = f"{BASE}/conversations.list"
    with aioresponses() as m:
        m.get(
            url,
            payload={
                "ok": False,
                "error": "missing_scope",
                "needed": "im:read,mpim:read",
                "provided": "channels:read,users:read",
            },
        )
        with pytest.raises(
            RuntimeError,
            match=(
                r"\(conversations\.list\): missing_scope "
                r"\(needed: im:read,mpim:read; "
                r"provided: channels:read,users:read\)"
            ),
        ):
            await slack_get(config, "conversations.list")


@pytest.mark.asyncio
async def test_slack_get_missing_scope_no_needed_falls_back(config):
    url = f"{BASE}/conversations.list"
    with aioresponses() as m:
        m.get(url, payload={"ok": False, "error": "missing_scope"})
        with pytest.raises(RuntimeError) as ei:
            await slack_get(config, "conversations.list")
        assert str(ei.value).endswith(
            "Slack API error (conversations.list): missing_scope"
        )


@pytest.mark.asyncio
async def test_slack_post_success(config):
    url = f"{BASE}/chat.postMessage"
    with aioresponses() as m:
        m.post(url, payload={"ok": True, "ts": "1234567890.123456"})
        result = await slack_post(
            config,
            "chat.postMessage",
            body={
                "channel": "C123",
                "text": "hello",
            },
        )
        sent = m.requests[("POST", URL(url))]
    assert result["ok"] is True
    assert result["ts"] == "1234567890.123456"
    assert len(sent) == 1
    assert sent[0].kwargs["json"] == {"channel": "C123", "text": "hello"}

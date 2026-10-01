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

from unittest.mock import patch

import pytest

from mirage.core.hf_hub.repo import head_commit


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.repo.hub_get")
async def test_head_commit_reads_the_repo_sha(mock_get, accessor):
    mock_get.return_value = {"sha": "deadbeef"}
    assert await head_commit(accessor) == "deadbeef"


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.repo.hub_get")
async def test_head_commit_asks_the_revision_not_the_bare_repo(
    mock_get, accessor
):
    """The bare repo object answers the default branch's sha whatever
    revision was asked for, and the download cache is keyed by this sha,
    so reading it there files a `--revision dev` fetch under main's
    snapshot."""
    mock_get.return_value = {"sha": "deadbeef"}
    await head_commit(accessor)
    assert mock_get.await_args.args[1].endswith("/revision/main")


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.repo.hub_get")
async def test_head_commit_of_a_non_object_is_empty(mock_get, accessor):
    mock_get.return_value = []
    assert await head_commit(accessor) == ""


@pytest.mark.asyncio
@patch("mirage.core.hf_hub.repo.hub_get")
async def test_head_commit_is_empty_when_the_hub_reports_none(
    mock_get, accessor
):
    mock_get.return_value = {}
    assert await head_commit(accessor) == ""

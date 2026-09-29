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

import json
from unittest.mock import AsyncMock, patch

import pytest

from mirage.accessor.trello import TrelloAccessor
from mirage.cache.index import IndexEntry
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.core.trello.read import read
from mirage.core.trello.readdir import readdir
from mirage.core.trello.stat import stat
from mirage.types import PathSpec
from mirage.vfs.trello.config import TrelloConfig

CARDS = ("/workspaces/Engineering__ws1/boards/Product_Roadmap__b1"
         "/lists/Backlog__l1/cards")


@pytest.fixture
def accessor():
    return TrelloAccessor(TrelloConfig(api_key="key", api_token="token"))


@pytest.fixture
def index():
    return RAMIndexCacheStore()


def _entry(name: str, ident: str, kind: str) -> tuple[str, IndexEntry]:
    return (name,
            IndexEntry(id=ident,
                       name=name,
                       resource_type=f"trello/{kind}",
                       vfs_name=name))


async def _seed_card(index: RAMIndexCacheStore) -> None:
    # The listing a traversal would have left: a read proves the card's
    # directory exists through it before fetching the card by its id.
    await index.set_dir(CARDS, [_entry("Fix_login__c1", "c1", "card")])


@pytest.mark.asyncio
async def test_read_workspace_json(accessor, index):
    workspaces = [{"id": "ws1", "displayName": "Engineering", "name": "eng"}]
    await index.set_dir("/workspaces",
                        [_entry("Engineering__ws1", "ws1", "workspace")])
    with patch("mirage.core.trello.read.list_workspaces",
               new_callable=AsyncMock,
               return_value=workspaces):
        result = await read(
            accessor,
            PathSpec.from_str_path(
                "/workspaces/Engineering__ws1/workspace.json"),
            index,
        )
    payload = json.loads(result)
    assert payload["workspace_id"] == "ws1"
    assert payload["workspace_name"] == "Engineering"


@pytest.mark.asyncio
async def test_read_card_json(accessor, index):
    card = {
        "id": "c1",
        "name": "Fix login",
        "idBoard": "b1",
        "idList": "l1",
        "idMembers": ["m1"],
        "labels": [{
            "id": "lb1",
            "name": "bug"
        }],
        "due": "2026-04-10",
        "dueComplete": False,
        "closed": False,
        "desc": "Login is broken",
        "shortUrl": "https://trello.com/c/abc",
        "members": [{
            "id": "m1",
            "username": "alice"
        }],
    }
    await _seed_card(index)
    with patch("mirage.core.trello.read.get_card",
               new_callable=AsyncMock,
               return_value=card):
        result = await read(
            accessor,
            PathSpec.from_str_path(
                "/workspaces/Engineering__ws1/boards/Product_Roadmap__b1"
                "/lists/Backlog__l1/cards/Fix_login__c1/card.json"),
            index,
        )
    payload = json.loads(result)
    assert payload["card_id"] == "c1"
    assert payload["card_name"] == "Fix login"


@pytest.mark.asyncio
async def test_read_comments_jsonl(accessor, index):
    comments = [{
        "id": "act1",
        "date": "2026-04-05T10:00:00Z",
        "memberCreator": {
            "id": "m1",
            "fullName": "Alice"
        },
        "data": {
            "text": "This needs fixing"
        },
    }]
    await _seed_card(index)
    with patch("mirage.core.trello.read.list_card_comments",
               new_callable=AsyncMock,
               return_value=comments):
        result = await read(
            accessor,
            PathSpec.from_str_path(
                "/workspaces/Engineering__ws1/boards/Product_Roadmap__b1"
                "/lists/Backlog__l1/cards/Fix_login__c1/comments.jsonl"),
            index,
        )
    line = json.loads(result.decode().strip())
    assert line["comment_id"] == "act1"
    assert line["card_id"] == "c1"


@pytest.mark.asyncio
async def test_read_missing_path(accessor, index):
    with pytest.raises(FileNotFoundError):
        await read(accessor, PathSpec.from_str_path("/nonexistent/path"),
                   index)


WS1 = {"id": "ws1", "displayName": "Engineering", "name": "eng"}
WS2 = {"id": "ws2", "displayName": "Finance", "name": "fin"}
B1 = {"id": "b1", "name": "Product Roadmap"}
B2 = {"id": "b2", "name": "Secret"}
SECRET = "/workspaces/Engineering__ws1/boards/Secret__b2"


@pytest.mark.asyncio
async def test_a_board_outside_board_ids_is_absent_on_every_surface(index):
    """The listing drops a board ``board_ids`` leaves out, and the read
    used to go straight to the id in the path: ``cat`` served a board
    ``ls`` and ``stat`` both reported absent."""
    accessor = TrelloAccessor(
        TrelloConfig(api_key="key", api_token="token", board_ids=["b1"]))
    get_board = AsyncMock(side_effect=lambda config, board_id, session: {
        "b1": B1,
        "b2": B2
    }[board_id])
    get_card = AsyncMock(return_value={"id": "c9", "name": "Payroll"})
    with patch("mirage.core.trello.readdir.list_workspaces",
               AsyncMock(return_value=[WS1])), \
            patch("mirage.core.trello.readdir.list_workspace_boards",
                  AsyncMock(return_value=[B1, B2])), \
            patch("mirage.core.trello.read.get_board", get_board), \
            patch("mirage.core.trello.read.get_card", get_card):
        board_json = PathSpec.from_str_path(SECRET + "/board.json")
        for surface in (read, stat):
            with pytest.raises(FileNotFoundError):
                await surface(accessor, board_json, index)
        with pytest.raises(FileNotFoundError):
            await readdir(accessor, PathSpec.from_str_path(SECRET), index)
        with pytest.raises(FileNotFoundError):
            await read(
                accessor,
                PathSpec.from_str_path(
                    SECRET + "/lists/Todo__l9/cards/Payroll__c9/card.json"),
                index)
        get_board.assert_not_awaited()
        get_card.assert_not_awaited()
        scoped = await read(
            accessor,
            PathSpec.from_str_path("/workspaces/Engineering__ws1/boards"
                                   "/Product_Roadmap__b1/board.json"), index)
    assert json.loads(scoped)["board_id"] == "b1"


@pytest.mark.asyncio
async def test_a_workspace_outside_workspace_id_is_absent_to_read(index):
    accessor = TrelloAccessor(
        TrelloConfig(api_key="key", api_token="token", workspace_id="ws1"))
    with patch("mirage.core.trello.readdir.list_workspaces",
               AsyncMock(return_value=[WS1, WS2])), \
            patch("mirage.core.trello.read.list_workspaces",
                  AsyncMock(return_value=[WS1, WS2])):
        with pytest.raises(FileNotFoundError):
            await read(
                accessor,
                PathSpec.from_str_path("/workspaces/Finance__ws2"
                                       "/workspace.json"), index)
        scoped = await read(
            accessor,
            PathSpec.from_str_path("/workspaces/Engineering__ws1"
                                   "/workspace.json"), index)
    assert json.loads(scoped)["workspace_id"] == "ws1"


@pytest.mark.asyncio
async def test_a_dot_led_board_title_is_listed_and_addressable(index):
    """``sanitize_name`` kept a leading dot, so a board titled ``.plan``
    rendered ``.plan__b1``: the kit drops a dot-led name from the listing
    and classifies it as hidden, so the board was neither listed nor
    readable, with no error anywhere."""
    accessor = TrelloAccessor(TrelloConfig(api_key="key", api_token="token"))
    board = {"id": "b1", "name": ".plan"}
    with patch("mirage.core.trello.readdir.list_workspaces",
               AsyncMock(return_value=[WS1])), \
            patch("mirage.core.trello.readdir.list_workspace_boards",
                  AsyncMock(return_value=[board])), \
            patch("mirage.core.trello.read.get_board",
                  AsyncMock(return_value=board)):
        boards = PathSpec.from_str_path("/workspaces/Engineering__ws1/boards")
        listed = await readdir(accessor, boards, index)
        assert listed == ["/workspaces/Engineering__ws1/boards/plan__b1"]
        board_json = PathSpec.from_str_path(listed[0] + "/board.json")
        assert (await stat(accessor, board_json, index)).name == "board.json"
        payload = json.loads(await read(accessor, board_json, index))
    assert payload["board_name"] == ".plan"

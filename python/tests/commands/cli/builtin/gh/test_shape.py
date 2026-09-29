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

from mirage.commands.cli.builtin.gh.shape import (ZERO_TIME, ListOf, OrNull,
                                                  exported, pointer, struct)


def test_the_go_primitives_zero_fill():
    assert exported(None, "string") == ""
    assert exported(None, "int") == 0
    assert exported(None, "bool") is False
    assert exported(None, "time") == ZERO_TIME
    assert exported(None, "raw") is None


def test_a_struct_prints_in_its_own_order_and_a_nil_pointer_as_null():
    shape = struct(("b", "int"), ("a", "string"))
    assert list(exported({"b": 2}, shape).items()) == [("b", 2), ("a", "")]
    assert exported(None, pointer(("oid", "string"))) is None
    assert exported(None, ListOf("string")) is None


def test_a_user_author_keeps_its_id_and_a_bot_is_app_login():
    assert exported({
        "id": "U1",
        "login": "octo",
        "name": "Octo"
    }, "author") == {
        "id": "U1",
        "is_bot": False,
        "login": "octo",
        "name": "Octo"
    }
    assert exported({"login": "dependabot"}, "author") == {
        "is_bot": True,
        "login": "app/dependabot",
    }
    assert exported(None, OrNull("author")) is None


def test_reaction_groups_nobody_reacted_with_are_dropped():
    groups = [
        {
            "content": "THUMBS_UP",
            "users": {
                "totalCount": 2
            }
        },
        {
            "content": "LAUGH",
            "users": {
                "totalCount": 0
            }
        },
    ]
    assert exported(groups, "reactions") == [groups[0]]
    assert exported(None, "reactions") == []


def test_an_owner_leaves_an_empty_id_and_name_out():
    assert exported({
        "id": "O1",
        "login": "org"
    }, "owner") == {
        "id": "O1",
        "login": "org"
    }
    assert list(exported({
        "id": "U1",
        "name": "Me",
        "login": "me"
    }, "owner")) == ["id", "name", "login"]
    assert exported(None, "owner") == {"login": ""}

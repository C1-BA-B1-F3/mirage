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

from mirage.workspace.types import ExecutionNode


def test_execution_node_leaf():
    node = ExecutionNode(command="cat /data/file.txt", stderr=b"", exit_code=0)
    assert node.command == "cat /data/file.txt"
    assert node.op is None
    assert node.children == []
    assert node.exit_code == 0


def test_execution_node_pipe():
    node = ExecutionNode(
        op="|",
        stderr=b"",
        exit_code=0,
        children=[
            ExecutionNode(
                command="grep foo file", stderr=b"warning", exit_code=0
            ),
            ExecutionNode(command="sort", stderr=b"", exit_code=0),
        ],
    )
    assert node.op == "|"
    assert node.command is None
    assert len(node.children) == 2
    assert node.children[0].stderr == b"warning"


def test_execution_node_nested_tree():
    tree = ExecutionNode(
        op=";",
        stderr=b"",
        exit_code=0,
        children=[
            ExecutionNode(
                op="|",
                stderr=b"",
                exit_code=0,
                children=[
                    ExecutionNode(
                        command="grep foo file", stderr=b"", exit_code=1
                    ),
                    ExecutionNode(command="sort", stderr=b"", exit_code=0),
                ],
            ),
            ExecutionNode(command="echo done", stderr=b"", exit_code=0),
        ],
    )
    assert tree.children[0].children[0].exit_code == 1
    assert tree.children[1].command == "echo done"


def test_execution_node_to_dict():
    node = ExecutionNode(
        op="|",
        stderr=b"warn",
        exit_code=0,
        children=[
            ExecutionNode(command="grep foo", stderr=b"", exit_code=1),
            ExecutionNode(command="sort", stderr=b"", exit_code=0),
        ],
    )
    d = node.to_dict()
    assert d["op"] == "|"
    assert d["exit_code"] == 0
    assert len(d["children"]) == 2
    assert d["children"][0]["command"] == "grep foo"
    assert d["children"][0]["stderr"] == ""
    assert d["children"][0]["exit_code"] == 1

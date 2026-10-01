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

from mirage.core.notion.render import (
    _block_to_md,
    _rich_text_to_md,
    blocks_to_markdown,
)


class TestRichTextToMd:
    def test_plain(self):
        rt = [{"plain_text": "hello", "annotations": {}}]
        assert _rich_text_to_md(rt) == "hello"

    def test_bold(self):
        rt = [{"plain_text": "bold", "annotations": {"bold": True}}]
        assert _rich_text_to_md(rt) == "**bold**"

    def test_italic(self):
        rt = [{"plain_text": "em", "annotations": {"italic": True}}]
        assert _rich_text_to_md(rt) == "*em*"

    def test_code(self):
        rt = [{"plain_text": "x", "annotations": {"code": True}}]
        assert _rich_text_to_md(rt) == "`x`"

    def test_link(self):
        rt = [
            {
                "plain_text": "click",
                "annotations": {},
                "href": "https://example.com",
            }
        ]
        assert _rich_text_to_md(rt) == "[click](https://example.com)"

    def test_multiple(self):
        rt = [
            {"plain_text": "a ", "annotations": {}},
            {"plain_text": "b", "annotations": {"bold": True}},
        ]
        assert _rich_text_to_md(rt) == "a **b**"


class TestBlockToMd:
    def test_paragraph(self):
        block = {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"plain_text": "hi", "annotations": {}}]
            },
        }
        assert _block_to_md(block) == "hi"

    def test_heading_1(self):
        block = {
            "type": "heading_1",
            "heading_1": {
                "rich_text": [{"plain_text": "Title", "annotations": {}}]
            },
        }
        assert _block_to_md(block) == "# Title"

    def test_heading_2(self):
        block = {
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"plain_text": "Sub", "annotations": {}}]
            },
        }
        assert _block_to_md(block) == "## Sub"

    def test_bulleted_list_item(self):
        block = {
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"plain_text": "item", "annotations": {}}]
            },
        }
        assert _block_to_md(block) == "- item"

    def test_to_do_checked(self):
        block = {
            "type": "to_do",
            "to_do": {
                "rich_text": [{"plain_text": "done", "annotations": {}}],
                "checked": True,
            },
        }
        assert _block_to_md(block) == "- [x] done"

    def test_code_block(self):
        block = {
            "type": "code",
            "code": {
                "rich_text": [{"plain_text": "print(1)", "annotations": {}}],
                "language": "python",
            },
        }
        assert _block_to_md(block) == "```python\nprint(1)\n```"

    def test_divider(self):
        block = {"type": "divider", "divider": {}}
        assert _block_to_md(block) == "---"

    def test_child_page_empty(self):
        block = {"type": "child_page", "child_page": {"title": "Sub"}}
        assert _block_to_md(block) == ""


class TestBlocksToMarkdown:
    def test_multiple_blocks(self):
        blocks = [
            {
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"plain_text": "Title", "annotations": {}}]
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "body", "annotations": {}}]
                },
            },
        ]
        result = blocks_to_markdown(blocks)
        assert result == "# Title\n\nbody\n"

    def test_empty(self):
        assert blocks_to_markdown([]) == ""

    def test_nested_children_indent(self):
        blocks = [
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"plain_text": "parent", "annotations": {}}]
                },
                "children": [
                    {
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [
                                {"plain_text": "child", "annotations": {}}
                            ]
                        },
                    },
                ],
            },
        ]
        result = blocks_to_markdown(blocks)
        assert result == "- parent\n\n  - child\n"

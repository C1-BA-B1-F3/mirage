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

from typing import Any


def extract_text(messages: list[Any]) -> list[str]:
    """Extract text content from LangGraph messages.

    Args:
        messages (list[Any]): LangGraph message objects.

    Returns:
        list[str]: Non-empty text strings.
    """
    texts: list[str] = []
    for msg in messages:
        if not hasattr(msg, "content"):
            continue
        content = msg.content
        if isinstance(content, str):
            if content.strip():
                texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block["text"].strip()
                    if text:
                        texts.append(text)
    return texts

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

from mirage.core.gdocs.client import TokenManager, docs_base, google_post


async def append_text(
    token_manager: TokenManager,
    doc_id: str,
    text: str,
    tab_id: str | None = None,
) -> dict[str, Any]:
    """Append text to the end of a Google Doc, or of one of its tabs.

    A request that names no tab lands on the first one, which is
    Google's own default for every request but the three that default to
    all tabs (replaceAllText, deleteNamedRange,
    replaceNamedRangeContent). Omitting `tab_id` therefore keeps the
    first-tab behaviour rather than guessing at a better one; naming it
    is the only way to reach any other tab.

    Args:
        token_manager (TokenManager): manages OAuth2 tokens.
        doc_id (str): Google Docs document ID.
        text (str): plain text to append.
        tab_id (str | None): the tab to append to, from
            `tabs[].tabProperties.tabId`, or None for the first tab.

    Returns:
        dict: batchUpdate API response.
    """
    location = {"segmentId": ""}
    if tab_id:
        location["tabId"] = tab_id
    payload = {
        "requests": [
            {
                "insertText": {
                    "text": text,
                    "endOfSegmentLocation": location,
                }
            }
        ]
    }
    url = f"{docs_base(token_manager)}/documents/{doc_id}:batchUpdate"
    return await google_post(token_manager, url, payload)

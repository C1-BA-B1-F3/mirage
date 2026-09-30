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

from mirage.core.linear.queries import ISSUE_QUERY, TEAM_ISSUES_QUERY


def _selection(query: str, opener: str) -> list[str]:
    start = query.index(opener) + len(opener)
    depth = 1
    for i in range(start, len(query)):
        if query[i] == "{":
            depth += 1
        elif query[i] == "}":
            depth -= 1
            if depth == 0:
                return query[start:i].split()
    raise AssertionError(f"{opener!r} is never closed")


def test_the_listing_and_the_read_select_the_same_issue_fields():
    """issue.json is sized from the team listing (sizes_always_known)
    and read from the issue query, so a field one selects and the other
    does not makes the listed size disagree with the bytes a read
    delivers."""
    listed = _selection(TEAM_ISSUES_QUERY, "nodes {")
    read = _selection(ISSUE_QUERY, "issue(id: $issueId) {")
    assert "identifier" in listed
    assert listed == read

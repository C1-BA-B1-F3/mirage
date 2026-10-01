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

from mirage.core.hierarchy.codec import JSON_NAME
from mirage.core.hierarchy.scope import Scope, Slot, make_detect_scope
from mirage.types import ContentType

_TEAM = ("teams", Slot("team", id_key="team_id"))
_ISSUE = _TEAM + ("issues", Slot("issue", id_key="issue_id"))

# One description of the tree: readdir, stat and read all classify
# through it, so the file surface cannot disagree with itself about what
# a path means. Every dynamic level is a `label__id` name whose id rides
# in the slots (a team's label is itself two-part, `KEY__Name`, which the
# LAST-separator split keeps intact).
SCOPES = (
    Scope(kind="teams", segments=("teams",), probed=False),
    Scope(kind="team", segments=_TEAM),
    Scope(
        kind="team_json",
        segments=_TEAM + ("team.json",),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="members", segments=_TEAM + ("members",)),
    Scope(
        kind="member",
        segments=_TEAM
        + ("members", Slot("member", JSON_NAME, id_key="member_id")),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="issues", segments=_TEAM + ("issues",)),
    Scope(kind="issue", segments=_ISSUE),
    Scope(
        kind="issue_json",
        segments=_ISSUE + ("issue.json",),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(
        kind="comments_jsonl",
        segments=_ISSUE + ("comments.jsonl",),
        leaf=True,
        filetype=ContentType.TEXT,
    ),
    Scope(kind="projects", segments=_TEAM + ("projects",)),
    Scope(
        kind="project",
        segments=_TEAM
        + ("projects", Slot("project", JSON_NAME, id_key="project_id")),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="cycles", segments=_TEAM + ("cycles",)),
    Scope(
        kind="cycle",
        segments=_TEAM
        + ("cycles", Slot("cycle", JSON_NAME, id_key="cycle_id")),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="documents", segments=_TEAM + ("documents",)),
    Scope(
        kind="document",
        segments=_TEAM
        + ("documents", Slot("document", JSON_NAME, id_key="document_id")),
        leaf=True,
        filetype=ContentType.JSON,
    ),
)

detect_scope = make_detect_scope(SCOPES)

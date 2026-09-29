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

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from mirage.commands.cli.builtin.gh.accessor import (camel, gh_repo,
                                                     json_fields, list_limit,
                                                     text_out, typed_out)
from mirage.commands.cli.types import CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.core.github.config import GhConfig
from mirage.core.github.repo import (create_repo, fork_repo, list_repos,
                                     list_repository_fields, login,
                                     read_readme, rename_repo,
                                     repository_fields, view_repo)
from mirage.io.types import ByteSource, IOResult
from mirage.types import JsonValue

Primitive: TypeAlias = Literal["string", "int", "bool", "time", "raw"]

ZERO_TIME = "0001-01-01T00:00:00Z"


@dataclass(frozen=True, slots=True)
class _Struct:
    """Ordered, zero-filled Go fields; nullable structs preserve null."""
    fields: tuple[tuple[str, "Shape", str | None], ...]
    nullable: bool


@dataclass(frozen=True, slots=True)
class _List:
    """A Go slice that preserves null when the answer carried none."""
    item: "Shape"


# The Go type gh decodes a field into, which is what decides how it
# prints. A string prints "" for null, a number 0 and a bool false;
# "time" is a non-pointer time.Time, whose zero is the year-one
# timestamp; "raw" is a pointer (or a nullable time) and stays null.
Shape: TypeAlias = Primitive | _Struct | _List


def _struct(*fields: tuple[str, Shape] | tuple[str, Shape, str]) -> _Struct:
    return _Struct(
        tuple((f[0], f[1], f[2] if len(f) > 2 else None) for f in fields),
        False)


def _pointer(*fields: tuple[str, Shape]) -> _Struct:
    return _Struct(tuple((name, shape, None) for name, shape in fields), True)


def _exported(value: Any, shape: Shape) -> Any:
    """One value as gh prints it once decoded into ``shape``.

    Args:
        value (Any): the value as the answer carried it.
        shape (Shape): the Go type gh decodes it into.
    """
    if shape == "string":
        return value if isinstance(value, str) else ""
    if shape == "int":
        return value if isinstance(value,
                                   int) and not isinstance(value, bool) else 0
    if shape == "bool":
        return value if isinstance(value, bool) else False
    if shape == "time":
        return value if isinstance(value, str) else ZERO_TIME
    if shape == "raw":
        return value
    if isinstance(shape, _List):
        return ([_exported(item, shape.item)
                 for item in value] if isinstance(value, list) else None)
    assert isinstance(shape, _Struct)
    if value is None and shape.nullable:
        return None
    row = value if isinstance(value, dict) else {}
    return {
        name: _exported(row.get(source or name), inner)
        for name, inner, source in shape.fields
    }


_OWNER = _struct(("id", "string"), ("login", "string"))
_USER = _struct(("id", "string"), ("login", "string"), ("name", "string"),
                ("databaseId", "int"))
_COUNT = _struct(("totalCount", "int"))
# gh prints a related repository (a fork's parent, a template) as three
# facts.
_RELATED = _pointer(("id", "string"), ("name", "string"), ("owner", _OWNER))


@dataclass(frozen=True, slots=True)
class RepoField:
    """One ``--json`` field: the GraphQL selection gh sends for it and how
    the answer prints.

    Args:
        select (str): the selection inside ``repository { }``.
        shape (Shape): the Go type gh decodes the answer into.
        unwrap (str | None): gh's own flattening of a connection: its
            ``nodes``, its ``edges``, or the topic inside each topic
            node, which prints null rather than ``[]`` for a repository
            with none.
    """
    select: str
    shape: Shape
    unwrap: Literal["nodes", "edges", "topics"] | None = None


def _plain(name: str, shape: Shape) -> tuple[str, RepoField]:
    return name, RepoField(name, shape)


# Every field `gh repo view --json` and `gh repo list --json` accept in
# gh 2.85, each with the selection gh put on the wire for it (captured
# with GH_DEBUG=api) and the shape of gh's own Repository type.
REPO_FIELD_TABLE: dict[str, RepoField] = dict([
    _plain("archivedAt", "raw"),
    ("assignableUsers",
     RepoField("assignableUsers(first:100){nodes{id,login,name}}",
               _List(_USER), "nodes")),
    ("codeOfConduct",
     RepoField(
         "codeOfConduct{key,name,url}",
         _pointer(("key", "string"), ("name", "string"), ("url", "string")))),
    ("contactLinks",
     RepoField(
         "contactLinks{about,name,url}",
         _List(
             _struct(("about", "string"), ("name", "string"),
                     ("url", "string"))))),
    _plain("createdAt", "time"),
    ("defaultBranchRef",
     RepoField("defaultBranchRef{name}", _struct(("name", "string")))),
    _plain("deleteBranchOnMerge", "bool"),
    _plain("description", "string"),
    _plain("diskUsage", "int"),
    _plain("forkCount", "int"),
    ("fundingLinks",
     RepoField("fundingLinks{platform,url}",
               _List(_struct(("platform", "string"), ("url", "string"))))),
    _plain("hasDiscussionsEnabled", "bool"),
    _plain("hasIssuesEnabled", "bool"),
    _plain("hasProjectsEnabled", "bool"),
    _plain("hasWikiEnabled", "bool"),
    _plain("homepageUrl", "string"),
    _plain("id", "string"),
    _plain("isArchived", "bool"),
    _plain("isBlankIssuesEnabled", "bool"),
    _plain("isEmpty", "bool"),
    _plain("isFork", "bool"),
    _plain("isInOrganization", "bool"),
    _plain("isMirror", "bool"),
    _plain("isPrivate", "bool"),
    _plain("isSecurityPolicyEnabled", "bool"),
    _plain("isTemplate", "bool"),
    _plain("isUserConfigurationRepository", "bool"),
    ("issueTemplates",
     RepoField(
         "issueTemplates{name,title,body,about}",
         _List(
             _struct(("name", "string"), ("title", "string"),
                     ("body", "string"), ("about", "string"))))),
    ("issues", RepoField("issues(states:OPEN){totalCount}", _COUNT)),
    ("labels",
     RepoField(
         "labels(first:100){nodes{id,color,name,description}}",
         _List(
             _struct(("id", "string"), ("name", "string"),
                     ("description", "string"), ("color", "string"))),
         "nodes")),
    ("languages",
     RepoField(
         "languages(first:100){edges{size,node{name}}}",
         _List(_struct(("size", "int"), ("node", _struct(
             ("name", "string"))))), "edges")),
    ("latestRelease",
     RepoField(
         "latestRelease{publishedAt,tagName,name,url}",
         _pointer(("name", "string"), ("tagName", "string"), ("url", "string"),
                  ("publishedAt", "time")))),
    ("licenseInfo",
     RepoField(
         "licenseInfo{key,name,nickname}",
         _pointer(("key", "string"), ("name", "string"),
                  ("nickname", "string")))),
    ("mentionableUsers",
     RepoField("mentionableUsers(first:100){nodes{id,login,name}}",
               _List(_USER), "nodes")),
    _plain("mergeCommitAllowed", "bool"),
    ("milestones",
     RepoField(
         "milestones(first:100,states:OPEN)"
         "{nodes{number,title,description,dueOn}}",
         _List(
             _struct(("number", "int"), ("title", "string"),
                     ("description", "string"), ("dueOn", "raw"))), "nodes")),
    _plain("mirrorUrl", "string"),
    _plain("name", "string"),
    _plain("nameWithOwner", "string"),
    _plain("openGraphImageUrl", "string"),
    ("owner", RepoField("owner{id,login}", _OWNER)),
    ("parent", RepoField("parent{id,name,owner{id,login}}", _RELATED)),
    ("primaryLanguage",
     RepoField("primaryLanguage{name}", _pointer(("name", "string")))),
    ("projects",
     RepoField(
         "projects(first:100,states:OPEN)"
         "{nodes{id,name,number,body,resourcePath}}",
         _List(
             _struct(("id", "string"), ("name", "string"), ("number", "int"),
                     ("resourcePath", "string"))), "nodes")),
    # gh has no flattening for this one, so it prints its Go struct as
    # is: the untagged `Nodes` field under its own capitalised name.
    ("projectsV2",
     RepoField(
         'projectsV2(first:100,query:"is:open")'
         "{nodes{id,number,title,resourcePath,closed,url}}",
         _struct(
             ("Nodes",
              _List(
                  _struct(("id", "string"), ("title", "string"),
                          ("number", "int"), ("resourcePath", "string"),
                          ("closed", "bool"), ("url", "string"))), "nodes")))),
    ("pullRequestTemplates",
     RepoField("pullRequestTemplates{body,filename}",
               _List(_struct(("filename", "string"), ("body", "string"))))),
    ("pullRequests", RepoField("pullRequests(states:OPEN){totalCount}",
                               _COUNT)),
    _plain("pushedAt", "raw"),
    _plain("rebaseMergeAllowed", "bool"),
    ("repositoryTopics",
     RepoField("repositoryTopics(first:100){nodes{topic{name}}}",
               _List(_struct(("name", "string"))), "topics")),
    _plain("securityPolicyUrl", "string"),
    _plain("squashMergeAllowed", "bool"),
    _plain("sshUrl", "string"),
    _plain("stargazerCount", "int"),
    ("templateRepository",
     RepoField("templateRepository{id,name,owner{id,login}}", _RELATED)),
    _plain("updatedAt", "time"),
    _plain("url", "string"),
    _plain("usesCustomOpenGraphImage", "bool"),
    _plain("viewerCanAdminister", "bool"),
    _plain("viewerDefaultCommitEmail", "string"),
    _plain("viewerDefaultMergeMethod", "string"),
    _plain("viewerHasStarred", "bool"),
    _plain("viewerPermission", "string"),
    _plain("viewerPossibleCommitEmails", _List("string")),
    _plain("viewerSubscription", "string"),
    _plain("visibility", "string"),
    ("watchers", RepoField("watchers{totalCount}", _COUNT)),
])

REPO_FIELDS = tuple(REPO_FIELD_TABLE)


def _repo_selection(fields: list[str]) -> str:
    """The GraphQL selection for the fields a line asked for, in its
    order.

    Args:
        fields (list[str]): the ``--json`` fields.
    """
    return ",".join(REPO_FIELD_TABLE[field].select
                    for field in dict.fromkeys(fields))


def _exported_repo(node: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """One repository's answer as gh exports the fields asked for.

    Args:
        node (dict[str, Any]): the GraphQL ``Repository``.
        fields (list[str]): the ``--json`` fields.
    """
    row: dict[str, Any] = {}
    for field in fields:
        spec = REPO_FIELD_TABLE[field]
        value = node.get(field)
        connection = value if isinstance(value, dict) else {}
        if spec.unwrap == "nodes":
            value = connection.get("nodes")
        elif spec.unwrap == "edges":
            value = connection.get("edges")
        elif spec.unwrap == "topics":
            topics = [
                item.get("topic") for item in connection.get("nodes") or []
            ]
            value = topics or None
        row[field] = _exported(value, spec.shape)
    return row


def _repo(value: Any) -> dict[str, Any]:
    row = camel(value)
    result = row if isinstance(row, dict) else {}
    if "fullName" in result:
        result["nameWithOwner"] = result.pop("fullName")
    if "defaultBranch" in result:
        result["defaultBranchRef"] = {"name": result.pop("defaultBranch")}
    if "private" in result:
        result["isPrivate"] = result.pop("private")
    if "fork" in result:
        result["isFork"] = result.pop("fork")
    owner = result.get("owner")
    if isinstance(owner, dict) and "login" not in owner and "name" in owner:
        owner["login"] = owner["name"]
    return result


def summary(repo: JsonValue, readme: str | None) -> str:
    """gh's own text view of a repository.

    Two tab-separated header lines and then the README verbatim, with the
    `--` separator omitted entirely when there is no README. Probed
    against gh 2.85, whose description line is present and empty for a
    repository that has none.

    Args:
        repo (JsonValue): the REST repository object.
        readme (str | None): the decoded README, None when absent.

    Returns:
        str: what gh prints.
    """
    fields = repo if isinstance(repo, dict) else {}
    name = fields.get("full_name")
    description = fields.get("description")
    head = (f"name:\t{name if isinstance(name, str) else ''}\n"
            f"description:\t"
            f"{description if isinstance(description, str) else ''}\n")
    if readme is None:
        return head
    return f"{head}--\n{readme}"


async def view(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    """``gh repo view``.

    With ``--json`` it asks GraphQL for exactly the fields named, the
    way gh does, so every field gh accepts is answered in gh's own
    shape; the text view reads the REST object and the README.

    Args:
        inv (CLIInvocation[GhConfig]): the line's invocation record.
    """
    fl = FlagView(inv.flags)
    operand = inv.texts[0] if inv.texts else None
    ref = gh_repo(inv.config, operand or fl.as_str("repo"))
    fields = json_fields(fl, REPO_FIELDS)
    if fields is not None:
        node = await repository_fields(inv.config, ref,
                                       _repo_selection(fields))
        return await typed_out(_exported_repo(node, fields), fl, "",
                               REPO_FIELDS)
    repo = await view_repo(inv.config, ref)
    return await typed_out(repo, fl,
                           summary(repo, await read_readme(inv.config, ref)),
                           REPO_FIELDS)


async def list_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    """``gh repo list``, over GraphQL for ``--json`` as ``view`` is.

    Args:
        inv (CLIInvocation[GhConfig]): the line's invocation record.
    """
    fl = FlagView(inv.flags)
    owner = inv.texts[0] if inv.texts else None
    limit = list_limit(fl, 30)
    fields = json_fields(fl, REPO_FIELDS)
    if fields is not None:
        nodes = await list_repository_fields(inv.config, owner, limit,
                                             _repo_selection(fields))
        return await typed_out(
            [_exported_repo(node, fields) for node in nodes], fl, "",
            REPO_FIELDS)
    rows = [
        _repo(value) for value in await list_repos(inv.config, owner, limit)
    ]
    human = "".join(f'{row.get("nameWithOwner", "")}\t'
                    f'{row.get("description", "")}\t'
                    f'{row.get("visibility", "")}\t'
                    f'{row.get("updatedAt", "")}\n' for row in rows)
    return await typed_out(rows, fl, human, REPO_FIELDS)


async def create_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    spec = inv.texts[0] if inv.texts else ""
    if not spec:
        raise ValueError(
            "a repository name is required in noninteractive mode")
    parts = spec.split("/")
    if len(parts) > 2 or any(not part for part in parts):
        raise ValueError(f'invalid repository name: "{spec}"')
    owner = parts[0] if len(parts) == 2 else None
    name = parts[-1]
    if fl.as_bool("public") and fl.as_bool("private"):
        raise ValueError("--public and --private are mutually exclusive")
    body: dict[str, JsonValue] = {
        "name": name,
        "private": fl.as_bool("private"),
        "auto_init": fl.as_bool("add_readme"),
    }
    for flag, key in (("description", "description"), ("homepage",
                                                       "homepage")):
        value = fl.as_str(flag)
        if value is not None:
            body[key] = value
    created = _repo(await create_repo(inv.config, owner, body))
    return text_out(f'{created.get("url", "")}\n')


async def fork(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    operand = inv.texts[0] if inv.texts else None
    source = gh_repo(inv.config, operand)
    name = fl.as_str("fork_name")
    forked = await fork_repo(inv.config, source, name)
    landed = forked.get("full_name") if isinstance(forked, dict) else None
    full = landed if isinstance(
        landed, str) else (f"{await login(inv.config)}/{name or source.repo}")
    return text_out(f"✓ Created fork {full}\n")


async def rename(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    # gh takes the *new name* as the operand and the repository to rename as
    # -R, which is the reverse of what the shape of the line suggests.
    target = gh_repo(inv.config, fl.as_str("repo"))
    name = inv.texts[0] if inv.texts else ""
    if not name:
        raise ValueError("a new repository name is required")
    renamed = await rename_repo(inv.config, target, name)
    landed = renamed.get("full_name") if isinstance(renamed, dict) else None
    full = landed if isinstance(landed, str) else name
    return text_out(f"✓ Renamed repository {full}\n")

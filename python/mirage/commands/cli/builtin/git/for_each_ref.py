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

import asyncio
import re

from dulwich.objects import Commit, Tag
from dulwich.repo import BaseRepo

from mirage.commands.cli.builtin.git.errors import GitError
from mirage.commands.cli.builtin.git.objects import abbrev_for
from mirage.commands.cli.builtin.git.session import opened
from mirage.commands.cli.builtin.git.util import fatal
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.types import ByteSource, IOResult
from mirage.utils.fnmatch import fnmatch

DEFAULT_FORMAT = "%(objectname) %(objecttype)\t%(refname)"
PLACEHOLDER = re.compile(r"%\(([^)]+)\)|%([0-9a-fA-F]{2})")
SHORT_PREFIX = re.compile(r"^refs/(heads|tags|remotes)/")


def _path_match(parts: list[str], name: list[str]) -> bool:
    """Match a pattern against a ref one component at a time.

    Args:
        parts (list[str]): the pattern's ``/``-separated components.
        name (list[str]): the ref name's components.
    """
    if not parts:
        return not name
    head, rest = parts[0], parts[1:]
    if head == "**":
        return any(_path_match(rest, name[i:]) for i in range(len(name) + 1))
    return bool(name) and fnmatch(name[0], head) and _path_match(
        rest, name[1:])


def ref_selected(name: str, patterns: tuple[str, ...]) -> bool:
    """Whether a ref is one of the patterns', as ``match_name_as_path``.

    A pattern selects a ref it spells in full or up to a ``/``, or one
    it matches as a ``WM_PATHNAME`` glob: ``*`` stops at a ``/``, so
    ``refs/*`` selects nothing while ``refs/*/*`` and ``refs/**``
    select every branch (git 2.47.3 and 2.50.1).

    Args:
        name (str): the full ref name.
        patterns (tuple[str, ...]): the operands; none selects all.
    """
    if not patterns:
        return True
    components = name.split("/")
    for pattern in patterns:
        if name.startswith(pattern) and (len(name) == len(pattern)
                                         or name[len(pattern)] == "/"
                                         or pattern.endswith("/")):
            return True
        if _path_match(pattern.split("/"), components):
            return True
    return False


def _formatted(repo: BaseRepo, patterns: tuple[str, ...], template: str,
               count: int) -> bytes:
    """Expand the format once per selected ref, in refname order.

    Args:
        repo (BaseRepo): the opened repository.
        patterns (tuple[str, ...]): the ref patterns.
        template (str): the ``--format`` string.
        count (int): ``--count``, zero for every ref.
    """
    rows = []
    for ref in sorted(repo.refs.allkeys()):
        name = ref.decode()
        if not name.startswith("refs/") or not ref_selected(name, patterns):
            continue
        obj = repo.object_store[repo.refs[ref]]
        message = obj.message.decode("utf-8", "replace") if isinstance(
            obj, (Commit, Tag)) else ""
        atoms = {
            "refname": name,
            "refname:short": SHORT_PREFIX.sub("", name),
            "objectname": obj.id.decode(),
            "objectname:short": obj.id.decode()[:abbrev_for(repo)],
            "objecttype": obj.type_name.decode(),
            "subject": message.split("\n\n", 1)[0].rstrip().replace("\n", " "),
            "contents": message,
        }

        def expand(match: re.Match[str]) -> str:
            atom = match.group(1)
            if atom is None:
                return chr(int(match.group(2), 16))
            if atom not in atoms:
                raise GitError(f"unknown field name: {atom}")
            return atoms[atom]

        rows.append(PLACEHOLDER.sub(expand, template) + "\n")
        if count and len(rows) >= count:
            break
    return "".join(rows).encode()


async def for_each_ref(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """Format the repository's references, including packed refs.

    Args:
        inv (CLIInvocation[None]): optional ref patterns and format.
    """
    fl = FlagView(inv.flags)
    try:
        count = fl.as_int("count") or 0
        if count < 0:
            raise GitError(f"invalid --count argument: {count}")
        repo, _ = await opened(fl, inv.doors or CLIDoors())
        template = fl.as_str("format")
        out = await asyncio.to_thread(
            _formatted, repo, inv.texts,
            DEFAULT_FORMAT if template is None else template, count)
        return out, IOResult()
    except GitError as exc:
        return fatal(exc)

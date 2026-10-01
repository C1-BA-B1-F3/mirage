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

import re
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import Any, cast

from mirage.commands.builtin.generic.find import (find_generic,
                                                  find_walk_generic)
from mirage.commands.builtin.generic_bind.adapter import (CommandIO,
                                                          with_path_guards,
                                                          with_policy_guard)
from mirage.commands.builtin.utils.output import format_records
from mirage.commands.builtin.utils.paths import default_paths
from mirage.commands.config import CommandOpts, command
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.context import hidden_paths_intersect, path_rules_active
from mirage.core.generic.find import make_search_backed_find
from mirage.core.slug_tree.tree import SlugTree
from mirage.core.slug_tree.types import A
from mirage.io.types import ByteSource, IOResult, materialize
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_prefix_of
from mirage.vfs.types import StatOp

_TIME_TESTS = frozenset({"-mtime", "-newer", "-newermt"})
_TIME_DIRECTIVE = re.compile(r"%[aAcCtTBW]")


def _reads_times(texts: list[str]) -> bool:
    """Whether the expression reads a timestamp, which the light stat
    only approximates from the listing.

    Args:
        texts (list[str]): the raw expression words.
    """
    return any(word in _TIME_TESTS or (
        word == "-printf" and _TIME_DIRECTIVE.search(value) is not None)
               for word, value in zip(texts, [*texts[1:], ""]))


def _is_bare_name(texts: list[str]) -> bool:
    return bool(texts) and not texts[0].startswith("-") and texts[0] not in (
        "(", ")", "!")


def _default_name(name: str | None, texts: list[str]) -> str | None:
    if name is not None:
        return name
    if _is_bare_name(texts):
        return texts[0]
    return None


def _expr_texts(texts: list[str]) -> list[str]:
    if _is_bare_name(texts):
        return []
    return texts


async def _normalize_find_output(
    stdout: ByteSource | None,
    search_path: PathSpec,
) -> ByteSource | None:
    if stdout is None:
        return None
    data = await materialize(stdout)
    root = mount_prefix_of(search_path.virtual,
                           search_path.vfs_path).rstrip("/") or "/"
    lines = data.decode().splitlines()
    normalized = [root if line == root + "/" else line for line in lines]
    return format_records(normalized)


def make_find(vfs: str, io: CommandIO, tree: SlugTree[A], stat: StatOp,
              stat_light: StatOp) -> Callable[..., Any]:
    """Build ``find`` for a slug-tree backend, filtered over one tree walk.

    Args:
        vfs (str): the backend the command registers for.
        io (CommandIO): the backend's command IO.
        tree (SlugTree[A]): the backend's tree.
        stat (StatOp): the full stat, paid only when the expression
            reads times (``-mtime``, ``-newer``, a ``-printf`` time).
        stat_light (StatOp): the index-only stat used otherwise.
    """
    find_core = make_search_backed_find(tree.resolve, stat, tree.walk)
    walk_full = with_policy_guard(with_path_guards(io))
    walk_light = with_policy_guard(
        with_path_guards(replace(io, stat=stat_light)))

    @command("find", vfs=vfs, spec=SPECS["find"])
    async def find(
        accessor: A,
        paths: list[PathSpec],
        texts: list[str],
        opts: CommandOpts,
    ) -> tuple[ByteSource | None, IOResult]:
        paths = default_paths(paths, opts.cwd)
        paths = await io.resolve_glob(accessor, paths, opts.index)
        search_path = paths[0]

        fl = FlagView(opts.flags, spec=SPECS["find"])
        # Push-down choices: a bare word acts as the -name filter, and the
        # heavier per-document stat is only paid when the expression reads
        # times.
        bag = dict(opts.flags)
        default_name = _default_name(fl.as_str("name"), texts)
        if default_name is not None:
            bag["name"] = default_name
        reads_times = _reads_times(texts)
        stat_fn = partial(stat if reads_times else stat_light,
                          accessor,
                          index=opts.index)
        # A native find op classifies on the raw backend tree, so under
        # hidden paths or a path rule it would answer for entries the
        # session cannot see; the walk classifies through the guarded
        # readdir/stat, the same fork the factory builder takes (rung 0).
        if (path_rules_active()
                or any(hidden_paths_intersect(p.virtual) for p in paths)):
            walk_io = walk_full if reads_times else walk_light
            stdout, result = await find_walk_generic(
                paths,
                _expr_texts(texts),
                replace(opts, flags=bag),
                readdir=partial(walk_io.readdir, accessor),
                stat=partial(walk_io.stat, accessor))
            return await _normalize_find_output(stdout, search_path), result
        stdout, result = await find_generic(paths,
                                            _expr_texts(texts),
                                            replace(opts, flags=bag),
                                            find_core=partial(
                                                find_core,
                                                accessor,
                                                index=opts.index),
                                            stat=stat_fn)
        return await _normalize_find_output(stdout, search_path), result

    return cast(Callable[..., Any], find)

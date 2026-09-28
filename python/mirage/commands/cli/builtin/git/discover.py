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

import posixpath
from io import BytesIO

from dulwich.config import ConfigFile

from mirage.commands.cli.builtin.git.constants import GIT_DIR
from mirage.commands.cli.builtin.git.errors import (  # yapf: disable
    InvalidGitFileError, NotARepositoryError, NoWorkingDirectoryError)
from mirage.commands.cli.builtin.git.io import read_file, read_optional
from mirage.commands.cli.builtin.git.types import RepoLocation
from mirage.ops.types import MountRoot, StatPath
from mirage.runtime.types import DispatchFn
from mirage.types import FileType

GITDIR_PREFIX = "gitdir:"
COMMON_DIR = "commondir"


def _normalize(path: str) -> str:
    """Strip a virtual path to its canonical no-trailing-slash spelling.

    Args:
        path (str): absolute virtual path, with or without a trailing
            slash (mount prefixes carry one, operands usually do not).
    """
    stripped = path.rstrip("/")
    return stripped or "/"


def _parent(path: str) -> str:
    """The directory above a normalized virtual path, "/" at the top.

    Args:
        path (str): normalized absolute virtual path.
    """
    return posixpath.dirname(path) or "/"


def _against(base: str, target: str) -> str:
    """Resolve a path a git file names, relative to the file's directory.

    git writes either form. A submodule and a ``--relative-paths``
    worktree point relatively so the pair can be moved together; an
    ordinary ``git worktree add`` writes an absolute path.

    Args:
        base (str): directory the naming file lives in.
        target (str): the path as the file spelled it.
    """
    return _normalize(posixpath.normpath(posixpath.join(base, target)))


async def _follow_gitfile(dispatch: DispatchFn, stat_path: StatPath,
                          gitfile: str) -> str:
    """Read a ``.git`` file and return the directory it points at.

    A ``.git`` that is a file rather than a directory holds one
    ``gitdir: <path>`` line. git writes one for every linked worktree
    (``git worktree add``) and every submodule, so the real git
    directory sits outside the tree being worked in, and reading the
    file as if it were a directory is how this used to fail.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        stat_path (StatPath): dispatcher-backed stat, both channels.
        gitfile (str): absolute virtual path of the ``.git`` file.
    """
    text = (await read_file(dispatch, gitfile)).decode("utf-8",
                                                       errors="replace")
    line = text.strip()
    if not line.startswith(GITDIR_PREFIX):
        raise InvalidGitFileError(gitfile)
    target = line[len(GITDIR_PREFIX):].strip()
    if not target:
        raise InvalidGitFileError(gitfile)
    resolved = _against(_parent(gitfile), target)
    if await stat_path(resolved) is None:
        # An absolute pointer names a path on the backend's own
        # filesystem, which is only reachable when the mount happens to
        # span it: a worktree mounted alone cannot see the repository it
        # was cut from. git says the same thing when the target is gone.
        raise NotARepositoryError(resolved, quoted=False)
    return resolved


async def _common_dir(dispatch: DispatchFn, gitdir: str) -> str:
    """The shared git directory behind a per-worktree one.

    A linked worktree's git directory carries a ``commondir`` file
    naming the repository it belongs to, usually as ``../..``. Objects,
    packed-refs and branches live there; only HEAD and the index are
    the worktree's own. An ordinary checkout has no such file and is its
    own common directory.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        gitdir (str): absolute virtual path of the git directory.
    """
    data = await read_optional(dispatch, posixpath.join(gitdir, COMMON_DIR))
    if data is None:
        return gitdir
    target = data.decode("utf-8", errors="replace").strip()
    return _against(gitdir, target) if target else gitdir


async def discover(dispatch: DispatchFn,
                   stat_path: StatPath,
                   mount_root: MountRoot,
                   start: str,
                   gitdir: str | None = None,
                   worktree: str | None = None) -> RepoLocation:
    """Find the repository governing a path, or raise git's own fatal.

    Walks up from ``start`` looking for a ``.git`` entry, stopping at the
    mount root. Real git stops discovery at a filesystem boundary unless
    GIT_DISCOVERY_ACROSS_FILESYSTEM is set, and a mount prefix is exactly
    that boundary: crossing it would probe a different backend for a
    repository that has nothing to do with the operand.

    Existence comes from ``stat_path`` rather than one backend's stat
    because on a prefix store a directory is not an object: ``.git``
    answers on readdir while a point lookup misses it entirely. That is
    the same fact ``find`` asks about its own start point.

    What is found is not always the git directory. A ``.git`` file
    points at one elsewhere, and the directory it points at may share
    its objects with another, so the three paths are resolved here and
    carried separately rather than derived again by each verb.

    Args:
        dispatch (DispatchFn): workspace op dispatcher, for the two files
            that redirect a git directory.
        stat_path (StatPath): dispatcher-backed stat asking both channels
            a backend can answer on; None means nothing is there.
        mount_root (MountRoot): the mount prefix serving a path.
        start (str): absolute virtual path to start from, normally the
            session cwd or the argument of ``-C``.
        gitdir (str | None): explicit repository path; skips upward discovery.
        worktree (str | None): explicit working tree, relative to start.
    """
    root = _normalize(mount_root(start))
    if gitdir is not None:
        here = await stat_path(start)
        if here is None:
            raise NoWorkingDirectoryError(start)
        if here.type is not FileType.DIRECTORY:
            raise NoWorkingDirectoryError(start, "Not a directory")
        candidate = _against(start, gitdir)
        info = await stat_path(candidate)
        if info is None:
            raise NotARepositoryError(gitdir)
        resolved = (candidate if info.type is FileType.DIRECTORY else await
                    _follow_gitfile(dispatch, stat_path, candidate))
        common = await _common_dir(dispatch, resolved)
        for path, kind in ((f"{resolved}/HEAD", FileType.FILE),
                           (f"{common}/objects", FileType.DIRECTORY),
                           (f"{common}/refs", FileType.DIRECTORY)):
            entry = await stat_path(path)
            if entry is None or entry.type is not kind:
                raise NotARepositoryError(gitdir)
        return await _location(dispatch, resolved, common, start, start,
                               worktree, root)
    current = _normalize(start)
    first = True
    while True:
        candidate = posixpath.join(current, GIT_DIR)
        info = await stat_path(candidate)
        if info is not None:
            gitdir = (candidate if info.type is FileType.DIRECTORY else await
                      _follow_gitfile(dispatch, stat_path, candidate))
            common = await _common_dir(dispatch, gitdir)
            return await _location(dispatch, gitdir, common, start, current,
                                   worktree, root)
        if first:
            # git enters ``-C`` before it looks for anything, so a path it
            # cannot enter fails on its own terms even when a directory
            # above it holds a repository. A file counts as one it cannot
            # enter: tolerating it would walk up and run in the parent
            # repository, which for a write verb means mutating a
            # repository the caller did not name. Asked only after the
            # first probe missed, because a hit already proves the
            # directory is there.
            here = await stat_path(current)
            if here is None:
                raise NoWorkingDirectoryError(start)
            if here.type is not FileType.DIRECTORY:
                raise NoWorkingDirectoryError(start, "Not a directory")
            first = False
        if current == root or current == "/":
            raise NotARepositoryError()
        current = _parent(current)


async def _location(dispatch: DispatchFn, gitdir: str, common: str, start: str,
                    default_worktree: str, worktree: str | None,
                    root: str) -> RepoLocation:
    """Resolve the work tree once for every verb, after locating metadata.

    CLI/environment paths are relative to -C; core.worktree is relative
    to the git directory, as in native git 2.54.0.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        gitdir (str): resolved checkout metadata directory.
        common (str): shared repository directory.
        start (str): invocation directory after -C.
        default_worktree (str): discovered root, or start for explicit gitdir.
        worktree (str | None): command-line or environment override.
        root (str): mount boundary used for discovery.
    """
    if worktree is not None:
        selected = _against(start, worktree)
    else:
        data = await read_optional(dispatch, f"{common}/config")
        config = ConfigFile.from_file(BytesIO(data or b""))
        try:
            configured = config.get((b"core", ), b"worktree")
        except KeyError:
            configured = None
        selected = (_against(gitdir, configured.decode("utf-8"))
                    if configured is not None else default_worktree)
    return RepoLocation(gitdir, common, selected, root)

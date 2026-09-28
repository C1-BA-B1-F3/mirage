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

import pytest

from mirage.commands.cli.builtin.git.discover import (discover,
                                                      require_work_tree)
from mirage.commands.cli.builtin.git.errors import (  # yapf: disable
    BadConfigValueError, InvalidGitFileError, NotARepositoryError,
    NotAWorkTreeError, NoWorkingDirectoryError, WorkTreeChdirError)
from mirage.types import ContentType, FileStat, FileType


def _stat_over(present: set[str], files: set[str] = frozenset()):
    """A stat_path that answers only for the given virtual paths.

    Args:
        present (set[str]): paths that exist as directories.
        files (set[str]): paths that exist as regular files.
    """

    async def stat_path(path: str) -> FileStat | None:
        if path in files:
            return FileStat(name=path.rsplit("/", 1)[-1],
                            type=FileType.FILE,
                            content=ContentType.TEXT)
        if path not in present:
            return None
        return FileStat(name=path.rsplit("/", 1)[-1], type=FileType.DIRECTORY)

    return stat_path


def _reads(contents: dict[str, bytes]):
    """A dispatcher that serves the given paths and misses everything else.

    Args:
        contents (dict[str, bytes]): virtual path to file body.
    """

    async def dispatch(op: str, path, **_kwargs):
        assert op == "read", op
        virtual = getattr(path, "virtual", path)
        if virtual not in contents:
            raise FileNotFoundError(virtual)
        return contents[virtual], None

    return dispatch


def _no_reads():
    """A dispatcher for a plain checkout, where nothing redirects."""
    return _reads({})


def _root(prefix: str):
    """A mount_root that reports one prefix for every path.

    Args:
        prefix (str): the mount prefix to report.
    """
    return lambda path: prefix


@pytest.mark.asyncio
async def test_finds_repo_at_start_point():
    repo = await discover(_no_reads(), _stat_over({"/repo/.git"}),
                          _root("/repo/"), "/repo")
    assert repo.gitdir == "/repo/.git"
    assert repo.commondir == "/repo/.git"
    assert repo.worktree == "/repo"
    assert repo.mount_root == "/repo"


@pytest.mark.asyncio
async def test_walks_up_to_the_repo_root():
    repo = await discover(_no_reads(),
                          _stat_over({"/repo/.git", "/repo/src/deep"}),
                          _root("/repo/"), "/repo/src/deep")
    assert repo.gitdir == "/repo/.git"
    assert repo.worktree == "/repo"


@pytest.mark.asyncio
async def test_nearest_repo_wins_over_an_outer_one():
    stat_path = _stat_over(
        {"/repo/.git", "/repo/vendor/.git", "/repo/vendor/src"})
    repo = await discover(_no_reads(), stat_path, _root("/repo/"),
                          "/repo/vendor/src")
    assert repo.gitdir == "/repo/vendor/.git"
    assert repo.worktree == "/repo/vendor"


@pytest.mark.asyncio
async def test_stops_at_the_mount_root():
    # A .git above the mount belongs to a different backend, so git's
    # own filesystem-boundary rule must not reach it.
    stat_path = _stat_over({"/.git", "/repo/src"})
    with pytest.raises(NotARepositoryError):
        await discover(_no_reads(), stat_path, _root("/repo/"), "/repo/src")


@pytest.mark.asyncio
async def test_missing_repo_raises_the_git_fatal():
    with pytest.raises(NotARepositoryError) as excinfo:
        await discover(_no_reads(), _stat_over({"/repo/src"}), _root("/repo/"),
                       "/repo/src")
    assert str(excinfo.value) == ("not a git repository (or any of the "
                                  "parent directories): .git")


@pytest.mark.asyncio
async def test_trailing_slashes_do_not_change_the_walk():
    repo = await discover(_no_reads(), _stat_over({"/repo/.git", "/repo/src"}),
                          _root("/repo/"), "/repo/src/")
    assert repo.gitdir == "/repo/.git"


@pytest.mark.asyncio
async def test_root_mount_terminates():
    with pytest.raises(NotARepositoryError):
        await discover(_no_reads(), _stat_over({"/a/b/c"}), _root("/"),
                       "/a/b/c")


@pytest.mark.asyncio
async def test_a_linked_worktree_follows_its_gitdir_pointer():
    # `git worktree add` leaves a .git *file*, not a directory. Reading
    # it as one is ENOTDIR on the first byte of HEAD.
    stat_path = _stat_over({"/repo/.git/worktrees/wt"},
                           files={"/repo/wt/.git"})
    dispatch = _reads({
        "/repo/wt/.git": b"gitdir: /repo/.git/worktrees/wt\n",
        "/repo/.git/worktrees/wt/commondir": b"../..\n",
    })
    repo = await discover(dispatch, stat_path, _root("/repo/"), "/repo/wt")
    assert repo.gitdir == "/repo/.git/worktrees/wt"
    assert repo.commondir == "/repo/.git"
    assert repo.worktree == "/repo/wt"


@pytest.mark.asyncio
async def test_a_relative_pointer_resolves_against_the_file():
    # What a submodule writes, and what `git worktree add
    # --relative-paths` writes, so the pair can be moved together.
    stat_path = _stat_over({"/repo/.git/modules/lib"},
                           files={"/repo/lib/.git"})
    dispatch = _reads({"/repo/lib/.git": b"gitdir: ../.git/modules/lib\n"})
    repo = await discover(dispatch, stat_path, _root("/repo/"), "/repo/lib")
    assert repo.gitdir == "/repo/.git/modules/lib"
    assert repo.commondir == "/repo/.git/modules/lib"


@pytest.mark.asyncio
async def test_a_pointer_out_of_the_mount_is_gits_unquoted_fatal():
    # A worktree mounted without the repository it was cut from: the
    # absolute path names the backend's own filesystem, which this mount
    # does not span. git words this one without quotes.
    stat_path = _stat_over(set(), files={"/repo/.git"})
    dispatch = _reads(
        {"/repo/.git": b"gitdir: /elsewhere/.git/worktrees/wt\n"})
    with pytest.raises(NotARepositoryError) as excinfo:
        await discover(dispatch, stat_path, _root("/repo/"), "/repo")
    assert str(excinfo.value) == (
        "not a git repository: /elsewhere/.git/worktrees/wt")


@pytest.mark.asyncio
async def test_a_git_file_that_is_not_a_pointer_is_refused():
    stat_path = _stat_over(set(), files={"/repo/.git"})
    dispatch = _reads({"/repo/.git": b"not a pointer\n"})
    with pytest.raises(InvalidGitFileError) as excinfo:
        await discover(dispatch, stat_path, _root("/repo/"), "/repo")
    assert str(excinfo.value) == "invalid gitfile format: /repo/.git"


@pytest.mark.asyncio
async def test_a_pointer_with_no_target_is_refused():
    stat_path = _stat_over(set(), files={"/repo/.git"})
    dispatch = _reads({"/repo/.git": b"gitdir:\n"})
    with pytest.raises(InvalidGitFileError):
        await discover(dispatch, stat_path, _root("/repo/"), "/repo")


@pytest.mark.asyncio
async def test_a_plain_checkout_is_its_own_common_dir():
    # No commondir file: the one directory holds both halves, which is
    # every repository that was never `git worktree add`ed.
    repo = await discover(_no_reads(), _stat_over({"/repo/.git"}),
                          _root("/repo/"), "/repo")
    assert repo.commondir == repo.gitdir


@pytest.mark.asyncio
async def test_a_start_that_is_not_there_is_a_different_fatal():
    # git tells the two apart: a directory it could not enter is not the
    # same complaint as a directory holding no repository.
    with pytest.raises(NoWorkingDirectoryError) as excinfo:
        await discover(_no_reads(), _stat_over(set()), _root("/repo/"),
                       "/repo/gone")
    assert str(excinfo.value) == ("cannot change to '/repo/gone': "
                                  "No such file or directory")


@pytest.mark.asyncio
async def test_a_start_that_is_a_file_is_refused():
    # A file is a path git cannot enter, and saying so matters more than
    # it looks: discovery walks upwards, so tolerating it would run in
    # the repository above and let a write verb mutate one nobody named.
    with pytest.raises(NoWorkingDirectoryError) as excinfo:
        await discover(_no_reads(),
                       _stat_over({"/repo", "/repo/.git"}, {"/repo/a.txt"}),
                       _root("/repo/"), "/repo/a.txt")
    assert str(excinfo.value) == ("cannot change to '/repo/a.txt': "
                                  "Not a directory")


@pytest.mark.asyncio
async def test_a_missing_start_beats_a_repository_above_it():
    # git enters -C before it looks for anything, so `git -C gone` fails
    # even standing inside a repository that would otherwise be found by
    # walking up.
    stat_path = _stat_over({"/repo", "/repo/.git"})
    with pytest.raises(NoWorkingDirectoryError):
        await discover(_no_reads(), stat_path, _root("/repo/"), "/repo/gone")


@pytest.mark.asyncio
async def test_core_worktree_is_relative_to_the_git_directory():
    stat_path = _stat_over({"/repo/.git", "/repo/src"})
    dispatch = _reads({"/repo/.git/config": b"[core]\n\tworktree = ../src\n"})
    repo = await discover(dispatch, stat_path, _root("/repo/"), "/repo")
    assert repo.worktree == "/repo/src"


@pytest.mark.asyncio
async def test_a_linked_worktree_ignores_its_repositorys_core_worktree():
    # git reads core.worktree only from a repository's own config, and a
    # linked worktree's config is the repository's: applying it would
    # put the tree next to the main checkout's metadata.
    stat_path = _stat_over({"/repo/.git/worktrees/wt"},
                           files={"/repo/wt/.git"})
    dispatch = _reads({
        "/repo/wt/.git": b"gitdir: /repo/.git/worktrees/wt\n",
        "/repo/.git/worktrees/wt/commondir": b"../..\n",
        "/repo/.git/config": b"[core]\n\tworktree = ..\n",
    })
    repo = await discover(dispatch, stat_path, _root("/repo/"), "/repo/wt")
    assert repo.worktree == "/repo/wt"


@pytest.mark.asyncio
async def test_a_relative_core_worktree_git_cannot_enter_fails_every_verb():
    dispatch = _reads({"/repo/.git/config": b"[core]\n\tworktree = gone\n"})
    with pytest.raises(WorkTreeChdirError) as excinfo:
        await discover(dispatch, _stat_over({"/repo/.git"}), _root("/repo/"),
                       "/repo")
    assert str(excinfo.value) == ("cannot chdir to 'gone': "
                                  "No such file or directory")


@pytest.mark.asyncio
async def test_a_named_work_tree_beats_the_config():
    dispatch = _reads({
        "/repo/.git/config":
        b"[core]\n\tbare = true\n\tworktree = gone\n",
    })
    repo = await discover(dispatch, _stat_over({"/repo/.git"}),
                          _root("/repo/"), "/repo", None, "../elsewhere")
    assert repo.worktree == "/elsewhere"


@pytest.mark.asyncio
async def test_a_named_git_file_leading_nowhere_names_its_target():
    # git's read_gitfile refuses the pointer's target, unquoted, before
    # it quotes the --git-dir it was handed.
    stat_path = _stat_over({"/", "/repo/docs"}, files={"/repo/stray"})
    dispatch = _reads({"/repo/stray": b"gitdir: docs\n"})
    with pytest.raises(NotARepositoryError) as excinfo:
        await discover(dispatch, stat_path, _root("/"), "/", "/repo/stray")
    assert str(excinfo.value) == "not a git repository: /repo/docs"


@pytest.mark.asyncio
async def test_a_bare_repository_has_no_work_tree_to_enter():
    dispatch = _reads({"/repo/.git/config": b"[core]\n\tbare = true\n"})
    stat_path = _stat_over({"/repo", "/repo/.git"})
    repo = await discover(dispatch, stat_path, _root("/repo/"), "/repo")
    with pytest.raises(NotAWorkTreeError):
        await require_work_tree(dispatch, stat_path, repo, False)
    await require_work_tree(dispatch, stat_path, repo, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("worktree", ["/repo/missing", "/repo/a.txt"])
async def test_a_named_work_tree_must_be_a_directory(worktree):
    stat_path = _stat_over({"/repo", "/repo/.git"}, files={"/repo/a.txt"})
    repo = await discover(_no_reads(), stat_path, _root("/repo/"), "/repo",
                          None, worktree)
    with pytest.raises(NotAWorkTreeError):
        await require_work_tree(_no_reads(), stat_path, repo, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [
    b"[Core]\n\tBare = yes\n",
    b"[core]\n\tbare = 1\n",
    b"[core]\n\tbare\n",
])
async def test_core_bare_is_read_as_git_reads_a_boolean(config):
    dispatch = _reads({"/repo/.git/config": config})
    stat_path = _stat_over({"/repo", "/repo/.git"})
    repo = await discover(dispatch, stat_path, _root("/repo/"), "/repo")
    with pytest.raises(NotAWorkTreeError):
        await require_work_tree(dispatch, stat_path, repo, False)


@pytest.mark.asyncio
async def test_an_unreadable_core_bare_fails_even_a_named_work_tree():
    # git parses core.bare at setup, before it asks which tree was named,
    # and dies at the first value it cannot read.
    dispatch = _reads(
        {"/repo/.git/config": b"[core]\n\tbare = maybe\n\tbare = false\n"})
    with pytest.raises(BadConfigValueError) as excinfo:
        await discover(dispatch, _stat_over({"/repo", "/repo/.git"}),
                       _root("/repo/"), "/repo", None, ".")
    assert str(excinfo.value) == ("bad boolean config value 'maybe' "
                                  "for 'core.bare'")


@pytest.mark.asyncio
async def test_a_linked_worktree_ignores_core_bare_but_still_parses_it():
    stat_path = _stat_over({"/repo/.git/worktrees/wt", "/repo/wt"},
                           files={"/repo/wt/.git"})
    contents = {
        "/repo/wt/.git": b"gitdir: /repo/.git/worktrees/wt\n",
        "/repo/.git/worktrees/wt/commondir": b"../..\n",
        "/repo/.git/config": b"[core]\n\tbare = true\n",
    }
    repo = await discover(_reads(contents), stat_path, _root("/repo/"),
                          "/repo/wt")
    await require_work_tree(_reads(contents), stat_path, repo, False)
    contents["/repo/.git/config"] += b"\tbare = maybe\n"
    with pytest.raises(BadConfigValueError):
        await discover(_reads(contents), stat_path, _root("/repo/"),
                       "/repo/wt")

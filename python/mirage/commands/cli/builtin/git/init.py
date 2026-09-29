import posixpath

from mirage.commands.cli.builtin.git.discover import discover
from mirage.commands.cli.builtin.git.errors import (GitError,
                                                    NoWorkingDirectoryError,
                                                    NoWorkspaceError)
from mirage.commands.cli.builtin.git.io import (ensure_dir, read_optional,
                                                write_once)
from mirage.commands.cli.builtin.git.refs import valid_ref_name
from mirage.commands.cli.builtin.git.util import fatal, start_point
from mirage.commands.cli.types import CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.types import ByteSource, IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import FileType


async def lay_out(dispatch: DispatchFn, gitdir: str, branch: str,
                  config: str) -> None:
    """Write a new git directory's skeleton, keeping what is there.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        gitdir (str): absolute virtual path of the git directory.
        branch (str): the branch HEAD starts on.
        config (str): the config file's contents.
    """
    for directory in ("objects/info", "objects/pack", "refs/heads",
                      "refs/tags", "info"):
        await ensure_dir(dispatch, f"{gitdir}/{directory}")
    await write_once(dispatch, f"{gitdir}/HEAD",
                     f"ref: refs/heads/{branch}\n".encode())
    await write_once(dispatch, f"{gitdir}/config", config.encode())
    await write_once(
        dispatch, f"{gitdir}/description",
        b"Unnamed repository; edit this file 'description' "
        b"to name the repository.\n")


async def init(inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """Initialize through the dispatcher, preserving an existing repository.

    No host templates, hooks or default-branch advisory are installed.

    Args:
        inv (CLIInvocation[None]): location and initialization flags.
    """
    fl = FlagView(inv.flags)
    doors = inv.doors
    try:
        if (doors is None or doors.dispatch is None or doors.stat_path is None
                or doors.ns is None or doors.ns.mounts is None):
            raise NoWorkspaceError()
        dispatch = doors.dispatch
        start = start_point(fl)
        here = await doors.stat_path(start)
        if here is None or here.type is not FileType.DIRECTORY:
            raise NoWorkingDirectoryError(
                start, "No such file or directory"
                if here is None else "Not a directory")
        target = posixpath.normpath(
            posixpath.join(start, inv.texts[0] if inv.texts else "."))
        bare = fl.as_bool("bare")
        explicit = fl.as_str("git_dir")
        gitdir = posixpath.normpath(posixpath.join(
            start,
            explicit)) if explicit else target if bare else posixpath.join(
                target, ".git")
        branch = fl.as_str("initial_branch") or "master"
        if not valid_ref_name(f"refs/heads/{branch}") or branch.startswith(
                "-"):
            raise GitError(f"invalid branch name: '{branch}'")
        info = await doors.stat_path(gitdir)
        if info is not None and (info.type is not FileType.DIRECTORY
                                 or await read_optional(
                                     dispatch, f"{gitdir}/HEAD") is not None):
            location = await discover(dispatch, doors.stat_path,
                                      doors.ns.mounts.root_of, target, gitdir,
                                      fl.as_str("work_tree"))
            gitdir = location.commondir
        existing = await read_optional(dispatch, f"{gitdir}/HEAD") is not None
        config = ("[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n"
                  f"\tbare = {'true' if bare else 'false'}\n")
        await lay_out(dispatch, gitdir, branch, config)
        action = "Reinitialized existing" if existing else "Initialized empty"
        text = f"{action} Git repository in {gitdir}/\n"
        warning = ""
        if existing and fl.as_str("initial_branch"):
            warning = f"warning: re-init: ignored --initial-branch={branch}\n"
        return b"" if fl.as_bool("quiet") else text.encode(), IOResult(
            stderr=warning.encode())
    except GitError as exc:
        return fatal(exc)

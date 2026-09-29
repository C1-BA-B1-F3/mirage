import asyncio
import posixpath
import re
from io import BytesIO

from dulwich.config import ConfigFile
from dulwich.repo import BaseRepo

from mirage.commands.cli.builtin.git.errors import GitError, NoWorkspaceError
from mirage.commands.cli.builtin.git.history import (LogFlags, parse_flags,
                                                     ref_commits, select)
from mirage.commands.cli.builtin.git.io import read_file, read_optional
from mirage.commands.cli.builtin.git.refs import read_head
from mirage.commands.cli.builtin.git.revparse import (resolve_object,
                                                      split_revisions)
from mirage.commands.cli.builtin.git.session import opened
from mirage.commands.cli.builtin.git.util import (check_operands, escaped,
                                                  fatal, start_point)
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.types import ByteSource, IOResult
from mirage.utils.posix import translate_classes
from mirage.version import __version__

SHOW_TOPLEVEL = "--show-toplevel"


async def repo_config(inv: CLIInvocation[None], fl: FlagView) -> ConfigFile:
    doors = inv.doors or CLIDoors()
    _, location = await opened(fl, doors)
    assert doors.dispatch is not None
    return ConfigFile.from_file(
        BytesIO(await read_file(doors.dispatch,
                                f"{location.commondir}/config")))


async def remote(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    try:
        check_operands(inv.texts, marked=escaped(inv.argv))
        cfg = await repo_config(inv, fl)
        lines = []
        for section in sorted(cfg.sections()):
            if len(section) != 2 or section[0] != b"remote":
                continue
            name = section[1].decode()
            if not fl.as_bool("verbose"):
                lines.append(name)
                continue
            values = list(cfg.items(section))
            urls = [v.decode() for k, v in values if k == b"url"]
            push = [v.decode() for k, v in values if k == b"pushurl"] or urls
            if urls:
                lines.append(f"{name}\t{urls[0]} (fetch)")
            lines.extend(f"{name}\t{url} (push)" for url in push)
        return ("".join(f"{line}\n" for line in lines).encode(), IOResult())
    except GitError as exc:
        return fatal(exc)


async def global_sources(inv: CLIInvocation[None],
                         listing: bool) -> list[tuple[str, ConfigFile]]:
    """The per-user config files ``--global`` reads, in git's order.

    ``$GIT_CONFIG_GLOBAL`` alone when set, else the XDG file then
    ``~/.gitconfig``, each read through the dispatcher from the
    session's own ``HOME`` so the answer is the workspace's and never
    the host's. Only ``--list`` refuses when neither exists.

    Args:
        inv (CLIInvocation[None]): the invocation, for its env and doors.
        listing (bool): ``--list`` was given.
    """
    dispatch = inv.doors.dispatch if inv.doors is not None else None
    if dispatch is None:
        raise NoWorkspaceError()
    home = inv.env.get("HOME", "")
    override = inv.env.get("GIT_CONFIG_GLOBAL")
    if override is None and not home:
        raise GitError("$HOME not set")
    target = override or posixpath.join(home, ".gitconfig")
    xdg = inv.env.get("XDG_CONFIG_HOME") or posixpath.join(home, ".config")
    paths = [target] if override is not None else [
        posixpath.join(xdg, "git/config"), target
    ]
    sources = []
    for source in paths:
        data = await read_optional(dispatch, source)
        if data is not None:
            sources.append((source, ConfigFile.from_file(BytesIO(data))))
    if not sources and listing:
        raise GitError(f"unable to read config file '{target}': "
                       "No such file or directory")
    return sources


async def config(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    try:
        if fl.as_bool("global"):
            sources = await global_sources(inv, fl.as_bool("list"))
        else:
            doors = inv.doors or CLIDoors()
            _, location = await opened(fl, doors)
            assert doors.dispatch is not None
            source = f"{location.commondir}/config"
            data = await read_file(doors.dispatch, source)
            ordinary = location.commondir == location.worktree + "/.git"
            if ordinary and start_point(fl) == location.worktree:
                source = ".git/config"
            sources = [(source, ConfigFile.from_file(BytesIO(data)))]
        listing = fl.as_bool("list")
        regexp = fl.as_bool("get_regexp")
        origin = fl.as_bool("show_origin")
        if not listing and not inv.texts:
            return None, IOResult(exit_code=129,
                                  stderr=b"error: wrong number of arguments\n")
        key = inv.texts[0] if inv.texts else ""
        try:
            pattern = re.compile(translate_classes(
                config_key(key))) if regexp else None
        except re.error:
            return None, IOResult(
                exit_code=6,
                stderr=f"error: invalid key pattern: {key}\n".encode())
        values = []
        for source, cfg in sources:
            for section in cfg.sections():
                for name, value in cfg.items(section):
                    full = b".".join((*section, name.lower())).decode()
                    if listing or (pattern.search(full)
                                   if pattern else full == config_key(key)):
                        values.append((source, full, value.decode()))
        if not listing and not regexp:
            values = values[-1:]
        lines = [
            (f"file:{source}\t" if origin else "") +
            (name + ("=" if listing else " ") if listing or regexp else "") +
            value + "\n" for source, name, value in values
        ]
        return "".join(lines).encode(), IOResult(
            exit_code=0 if values or listing else 1)

    except GitError as exc:
        return fatal(exc)


def _show_refs(repo: BaseRepo, patterns: tuple[str, ...]) -> bytes:
    return "".join(f"{repo.refs[ref].decode()} {ref.decode()}\n"
                   for ref in sorted(repo.refs.allkeys())
                   if ref.startswith(b"refs/") and (not patterns or any(
                       ref.decode() == p or ref.decode().endswith('/' + p)
                       for p in patterns))).encode()


async def show_ref(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    try:
        repo, _ = await opened(FlagView(inv.flags), inv.doors or CLIDoors())
        out = await asyncio.to_thread(_show_refs, repo, tuple(inv.texts))
        return out, IOResult(exit_code=0 if out else 1)
    except GitError as exc:
        return fatal(exc)


def _revisions(repo: BaseRepo, revisions: tuple[str, ...],
               flags: LogFlags) -> list[bytes]:
    starts, hidden = split_revisions(repo, revisions)
    if flags.all_refs:
        starts[:0] = ref_commits(repo)
    return [commit.id for commit in select(repo, starts, flags, tuple(hidden))]


async def rev_list(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    try:
        check_operands(inv.texts, marked=escaped(inv.argv))
        repo, _ = await opened(fl, inv.doors or CLIDoors())
        flags = parse_flags(fl)
        if not inv.texts and not flags.all_refs:
            return None, IOResult(
                exit_code=129,
                stderr=b"usage: git rev-list [<options>] <commit>...\n")
        commits = await asyncio.to_thread(_revisions, repo, tuple(inv.texts),
                                          flags)
        return (f"{len(commits)}\n".encode() if fl.as_bool("count") else
                b"".join(oid + b"\n" for oid in commits)), IOResult()
    except GitError as exc:
        return fatal(exc)


async def version(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    return f"git version {__version__} (Mirage)\n".encode(), IOResult()


def config_key(key: str) -> str:
    parts = key.split('.')
    parts[0] = parts[0].lower()
    parts[-1] = parts[-1].lower()
    return '.'.join(parts)


def _parse_revision(repo: BaseRepo, revision: str, abbrev: bool,
                    head_ref: str | None) -> bytes:
    """Resolve an object or its abbreviated symbolic name.

    Args:
        repo (BaseRepo): repository to read.
        revision (str): the requested revision.
        abbrev (bool): emit a ref name instead of an object id.
        head_ref (str | None): symbolic HEAD target, if any.
    """
    oid = resolve_object(repo, revision).id
    if not abbrev:
        return oid + b'\n'
    if revision == 'HEAD':
        return (
            (head_ref.removeprefix('refs/heads/') if head_ref else 'HEAD') +
            '\n').encode()
    refs = repo.refs.allkeys()
    for name in (revision, 'refs/' + revision, 'refs/tags/' + revision,
                 'refs/heads/' + revision, 'refs/remotes/' + revision):
        if name.encode() in refs:
            for prefix in ('refs/heads/', 'refs/tags/', 'refs/remotes/'):
                if name.startswith(prefix):
                    return (name.removeprefix(prefix) + '\n').encode()
            return (name + '\n').encode()
    return b''


def _revisions_before(argv: tuple[str, ...], count: int, option: str) -> int:
    """How many revisions rev-parse prints ahead of one of its options.

    rev-parse answers its arguments in line order, so ``HEAD
    --show-toplevel`` prints the id first. Every word after the option
    that is not a dash word is one of the later revisions.

    Args:
        argv (tuple[str, ...]): the line's verbatim tokens.
        count (int): how many revisions the line names.
        option (str): the option's spelling.
    """
    if option not in argv:
        return 0
    after = argv[argv.index(option) + 1:]
    return count - sum(1 for word in after if not word.startswith("-"))


async def rev_parse(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """Resolve revisions supplied to rev-parse.

    Args:
        inv (CLIInvocation[None]): the parsed invocation.
    """
    fl = FlagView(inv.flags)
    try:
        check_operands(inv.texts, marked=escaped(inv.argv))
        doors = inv.doors or CLIDoors()
        toplevel = fl.as_bool("show_toplevel")
        repo, location = await opened(fl, doors, work_tree=toplevel)
        assert doors.dispatch is not None
        head = await read_head(doors.dispatch, location.gitdir)
        rows = [
            await asyncio.to_thread(_parse_revision, repo, revision,
                                    fl.as_bool("abbrev_ref"), head.ref)
            for revision in inv.texts
        ]
        if toplevel:
            rows.insert(_revisions_before(inv.argv, len(rows), SHOW_TOPLEVEL),
                        f"{location.worktree}\n".encode())
        return b"".join(rows), IOResult()
    except GitError as exc:
        return fatal(exc)

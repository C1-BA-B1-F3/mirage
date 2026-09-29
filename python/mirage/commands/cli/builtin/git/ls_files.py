import fnmatch
import posixpath

from mirage.commands.cli.builtin.git.errors import GitError
from mirage.commands.cli.builtin.git.index import read_index
from mirage.commands.cli.builtin.git.pathspec import repo_relative
from mirage.commands.cli.builtin.git.render import quote_path
from mirage.commands.cli.builtin.git.repo import config_bool
from mirage.commands.cli.builtin.git.session import opened
from mirage.commands.cli.builtin.git.util import fatal, start_point
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.types import ByteSource, IOResult


async def ls_files(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """List index paths, including conflict stages when requested.

    Args:
        inv (CLIInvocation[None]): parsed index-listing invocation.
    """
    fl = FlagView(inv.flags)
    try:
        doors = inv.doors or CLIDoors()
        _, location = await opened(fl, doors)
        assert doors.dispatch is not None
        fully = await config_bool(doors.dispatch, location, b'core',
                                  b'quotepath', True)
        state = await read_index(doors.dispatch, location.gitdir)
        prefix = repo_relative(location, start_point(fl), '.')
        patterns = [
            repo_relative(location, start_point(fl), text)
            for text in inv.texts
        ]
        rows = [(path, 0, entry) for path, entry in state.entries.items()]
        rows.extend(
            (path, stage, entry) for path, conflict in state.conflicts.items()
            for stage, entry in enumerate((conflict.ancestor, conflict.this,
                                           conflict.other), 1)
            if entry is not None)
        out = []
        for path, stage, entry in sorted(rows):
            name = path.decode('utf-8', 'surrogateescape')
            if prefix and not name.startswith(prefix + '/'):
                continue
            if patterns and not any(
                    not pattern or name == pattern or name.startswith(
                        pattern + '/') or fnmatch.fnmatchcase(name, pattern)
                    for pattern in patterns):
                continue
            relative = posixpath.relpath(name, prefix or '.')
            label = relative if fl.as_bool('z') else quote_path(
                relative, False, fully)
            metadata = ''
            if fl.as_bool('stage'):
                metadata = f'{entry.mode:06o} {entry.sha.decode()} {stage}\t'
            out.append(metadata + label + ('\0' if fl.as_bool('z') else '\n'))
        return ''.join(out).encode('utf-8', 'surrogateescape'), IOResult()
    except GitError as exc:
        return fatal(exc)

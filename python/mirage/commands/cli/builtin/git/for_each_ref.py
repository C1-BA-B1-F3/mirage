import asyncio
import fnmatch
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


def _list(repo: BaseRepo, patterns: tuple[str, ...], template: str,
          count: int) -> bytes:
    refs = [
        ref for ref in sorted(repo.refs.allkeys()) if ref.startswith(b'refs/')
    ]
    rows = []
    for ref in refs:
        name = ref.decode()
        if patterns and not any(name == p or name.startswith(
                p.rstrip('/') + '/') or fnmatch.fnmatchcase(name, p)
                                for p in patterns):
            continue
        obj = repo.object_store[repo.refs[ref]]
        message = obj.message.decode('utf-8', 'replace') if isinstance(
            obj, (Commit, Tag)) else ''
        atoms = {
            'refname': name,
            'refname:short': re.sub(r'^refs/(heads|tags|remotes)/', '', name),
            'objectname': obj.id.decode(),
            'objectname:short': obj.id.decode()[:abbrev_for(repo)],
            'objecttype': obj.type_name.decode(),
            'subject': message.split('\n\n', 1)[0].rstrip().replace('\n', ' '),
            'contents': message
        }

        def expand(match: re.Match[str]) -> str:
            atom = match.group(1)
            if atom is None:
                return chr(int(match.group(2), 16))
            if atom not in atoms:
                raise GitError(f'unknown field name: {atom}')
            return atoms[atom]

        rows.append(
            re.sub(r'%\(([^)]+)\)|%([0-9a-fA-F]{2})', expand, template) + '\n')
        if count and len(rows) >= count:
            break
    return ''.join(rows).encode()


async def for_each_ref(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """Format the repository's references, including packed refs.

    Args:
        inv (CLIInvocation[None]): optional ref patterns and format.
    """
    fl = FlagView(inv.flags)
    try:
        count = fl.as_int('count') or 0
        if count < 0:
            raise GitError('invalid --count argument: ' + str(count))
        repo, _ = await opened(fl, inv.doors or CLIDoors())
        template = fl.as_str('format')
        out = await asyncio.to_thread(
            _list, repo, tuple(inv.texts),
            '%(objectname) %(objecttype)\t%(refname)'
            if template is None else template, count)
        return out, IOResult()
    except GitError as exc:
        return fatal(exc)

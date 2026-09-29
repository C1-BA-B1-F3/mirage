import subprocess

import pytest

from mirage.commands.cli.builtin.git import GIT
from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

from .conftest import mounted, pack_everything


@pytest.mark.asyncio
async def test_init_reinit_and_empty_inspection():
    with Workspace({'/repo': RAMVFS()}, mode=MountMode.WRITE) as ws:
        ws.register_cli('git', GIT)
        for command in ('mkdir -p /repo/project/.git',
                        'git init -q -b main /repo/project',
                        'git -C /repo/project stash list',
                        'git init -q /repo/project'):
            result = await ws.shell(command)
            assert result.exit_code == 0, await result.stderr_str()
        result = await ws.shell('cat /repo/project/.git/HEAD')
        assert await result.stdout_str() == 'ref: refs/heads/main\n'
        result = await ws.shell('git -C /repo/project fsck')
        assert result.exit_code == 0
        assert await result.stderr_str() == (
            'notice: HEAD points to an unborn branch (main)\n'
            'notice: No default references\n')
        result = await ws.shell('git -C /repo/project stash show')
        assert result.exit_code == 1
        assert await result.stderr_str() == 'No stash entries found.\n'
        assert (await
                ws.shell('git help')).stdout == (await
                                                 ws.shell('git --help')).stdout
        assert (await ws.shell('git help status')).stdout == (
            await ws.shell('git status --help')).stdout


@pytest.mark.asyncio
@pytest.mark.parametrize('packed', [False, True])
async def test_fsck_real_objects_and_missing_blob(repo_path, packed):
    if packed:
        pack_everything(repo_path)
    with mounted(repo_path) as ws:
        ws.register_cli('git', GIT)
        result = await ws.shell('git -C /repo fsck --no-dangling')
        assert result.exit_code == 0, await result.stderr_str()
    if not packed:
        oid = subprocess.check_output(
            ['git', '-C',
             str(repo_path), 'rev-parse', 'HEAD:a.txt'],
            text=True).strip()
        (repo_path / '.git' / 'objects' / oid[:2] / oid[2:]).unlink()
        with mounted(repo_path) as ws:
            ws.register_cli('git', GIT)
            result = await ws.shell('git -C /repo fsck --no-dangling')
            assert result.exit_code != 0
            assert oid in await result.stderr_str()


@pytest.mark.asyncio
async def test_stash_reads_native_reflog_and_diff(repo_path):
    path = repo_path / 'a.txt'
    path.write_text(path.read_text() + 'stashed change\n')
    subprocess.run([
        'git', '-C',
        str(repo_path), '-c', 'user.name=Test', '-c',
        'user.email=test@example.com', 'stash', 'push', '-m', 'saved'
    ],
                   check=True,
                   capture_output=True)
    with mounted(repo_path) as ws:
        ws.register_cli('git', GIT)
        for arguments in (['stash', 'list'], ['stash',
                                              'show'], ['stash', 'show', '-p'],
                          ['stash', 'show', '--name-only', 'stash@{0}']):
            native = subprocess.check_output(
                ['git', '-C', str(repo_path), *arguments])
            result = await ws.shell('git -C /repo ' + ' '.join(arguments))
            assert result.exit_code == 0, await result.stderr_str()
            assert result.stdout == native

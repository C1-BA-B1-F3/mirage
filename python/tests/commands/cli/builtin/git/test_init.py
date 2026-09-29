import pytest

from mirage.commands.cli.builtin.git import GIT
from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


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

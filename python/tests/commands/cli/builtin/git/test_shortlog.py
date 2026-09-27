import asyncio
import shlex
import subprocess

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('command', [
    'shortlog HEAD',
    'shortlog -sne HEAD',
    'shortlog -e HEAD~2..HEAD',
    'shortlog -sn HEAD..HEAD',
    'shortlog -sne --all',
    'shortlog -sne --author=Nobody HEAD',
])
async def test_shortlog_matches_git(git_ws, repo_path, command):
    native = await asyncio.to_thread(
        subprocess.run,
        ['git', '-C', str(repo_path), *shlex.split(command)],
        capture_output=True)
    assert native.returncode == 0, native.stderr
    actual = await git_ws.shell('git -C /repo ' + command)
    assert (actual.exit_code, actual.stdout or b'', actual.stderr
            or b'') == (native.returncode, native.stdout, native.stderr)

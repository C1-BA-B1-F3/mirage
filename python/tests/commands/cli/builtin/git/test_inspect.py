import asyncio
import shlex
import subprocess

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [
    "remote -v",
    "show-ref",
    "show-ref main",
    "rev-list --all --count",
    "rev-list HEAD",
    "log -1 --date=iso --format=%ad",
    "log -1 --date=iso-strict --format=%ad",
    "log -1 --format=%aI%n%ai%n%cI%n%ci",
    "log -1 --pretty=raw",
    "log --oneline --decorate -2",
    "log --decorate -1",
    "branch -a -vv",
    "show --name-status --format= HEAD",
    "show --summary --format=%h HEAD",
    "diff-tree --no-commit-id --name-only -r HEAD",
    "diff-tree HEAD",
    "diff-tree -r HEAD",
])
async def test_reads_match_git(git_ws, repo_path, command):
    native = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(repo_path), *shlex.split(command)],
        capture_output=True)
    actual = await git_ws.shell("git -C /repo " + command)
    assert (actual.exit_code, actual.stdout or b"", actual.stderr
            or b"") == (native.returncode, native.stdout, native.stderr)


@pytest.mark.asyncio
async def test_remote_and_tracking_reads(git_ws, repo_path):
    for args in [
        ['remote', 'add', 'origin', 'https://example.com/org/repo.git'],
        [
            'remote', 'set-url', '--push', 'origin',
            'ssh://git@example.com/org/repo.git'
        ],
        ['update-ref', 'refs/remotes/origin/main', 'HEAD~1'],
        ['branch', '--set-upstream-to=origin/main', 'main'],
    ]:
        await asyncio.to_thread(
            subprocess.run, ['git', '-C', str(repo_path), *args],
            check=True,
            capture_output=True)
    for command in [
            'remote', 'remote -v', 'config --get remote.origin.url',
            'branch -a -vv', 'branch -v'
    ]:
        native = await asyncio.to_thread(
            subprocess.run,
            ['git', '-C', str(repo_path), *shlex.split(command)],
            capture_output=True)
        actual = await git_ws.shell('git -C /repo ' + command)
        assert (actual.exit_code, actual.stdout or b'', actual.stderr
                or b'') == (native.returncode, native.stdout, native.stderr)

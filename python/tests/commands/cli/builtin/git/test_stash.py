import subprocess

import pytest

from mirage.commands.cli.builtin.git import GIT

from .conftest import mounted


@pytest.mark.asyncio
async def test_stash_reads_native_reflog_and_diff(repo_path):
    path = repo_path / "a.txt"
    path.write_text(path.read_text() + "stashed change\n")
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "stash",
            "push",
            "-m",
            "saved",
        ],
        check=True,
        capture_output=True,
    )
    with mounted(repo_path) as ws:
        ws.register_cli("git", GIT)
        for arguments in (
            ["stash", "list"],
            ["stash", "show"],
            ["stash", "show", "-p"],
            ["stash", "show", "--name-only", "stash@{0}"],
        ):
            native = subprocess.check_output(
                ["git", "-C", str(repo_path), *arguments]
            )
            result = await ws.shell("git -C /repo " + " ".join(arguments))
            assert result.exit_code == 0, await result.stderr_str()
            assert result.stdout == native

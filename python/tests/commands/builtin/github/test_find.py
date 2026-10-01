import pytest

from mirage.commands.builtin.github.find import find
from mirage.commands.config import CommandOpts
from mirage.context import reset_current_session, set_current_session
from mirage.io.types import materialize
from mirage.types import HiddenPaths, PathSpec
from mirage.workspace.session import SessionState


@pytest.mark.asyncio
async def test_find_mtime_does_not_return_entries_without_timestamps(
        github_env):
    accessor, index = github_env
    stdout, io = await find(accessor, [PathSpec.from_str_path('/')], [],
                            CommandOpts(index=index, flags={'mtime': '-1'}))

    assert await materialize(stdout) == b""
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_find_missing_start_reports_error(github_env):
    accessor, index = github_env
    stdout, io = await find(accessor, [PathSpec.from_str_path('/missing')], [],
                            CommandOpts(index=index))

    assert await materialize(stdout) == b""
    assert io.exit_code == 1
    assert b"missing" in await materialize(io.stderr)


@pytest.mark.asyncio
async def test_a_hidden_child_leaves_its_directory_empty(github_env):
    accessor, index = github_env
    hidden = HiddenPaths(paths=("/docs/guide.md", ))
    session = SessionState(session_id="veiled", hidden_paths=hidden)
    token = set_current_session(session)
    try:
        stdout, io = await find(accessor, [PathSpec.from_str_path('/docs')],
                                ["-type", "d", "-empty"],
                                CommandOpts(index=index))
        out = await materialize(stdout)
    finally:
        reset_current_session(token)

    assert out == b"/docs\n"
    assert io.exit_code == 0

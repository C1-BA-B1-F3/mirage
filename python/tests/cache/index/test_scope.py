import asyncio

import pytest

from mirage.cache.index.scope import command_scope, command_started, tick


def test_no_scope_means_no_stamp():
    assert command_started() is None


@pytest.mark.asyncio
async def test_each_command_gets_a_later_stamp():
    async with command_scope():
        first = command_started()
    async with command_scope():
        second = command_started()
    assert first is not None and second is not None
    assert second > first
    assert command_started() is None


@pytest.mark.asyncio
async def test_a_nested_command_restores_the_outer_stamp():
    # A $(...) inside a command runs its own commands; leaving it must not
    # leave the outer command holding the inner, later stamp.
    async with command_scope():
        outer = command_started()
        async with command_scope():
            inner = command_started()
        assert command_started() == outer
    assert inner is not None and outer is not None and inner > outer


@pytest.mark.asyncio
async def test_a_write_draws_a_tick_after_the_running_command():
    async with command_scope():
        started = command_started()
        written = tick()
    assert started is not None and written > started


@pytest.mark.asyncio
async def test_concurrent_commands_keep_their_own_stamps():
    seen: list[tuple[int | None, int | None]] = []

    async def one() -> None:
        async with command_scope():
            mine = command_started()
            await asyncio.sleep(0)
            seen.append((mine, command_started()))

    await asyncio.gather(one(), one())
    assert all(before == after for before, after in seen)
    assert seen[0][0] != seen[1][0]

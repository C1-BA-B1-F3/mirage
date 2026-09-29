# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import pytest

from mirage.commands.builtin.generic.head import head_generic, head_multi
from mirage.commands.config import CommandOpts
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key


def _paths(*names: str) -> list[PathSpec]:
    return [
        PathSpec(vfs_path=mount_key(n, ""),
                 virtual=n,
                 directory="/d",
                 resolved=True) for n in names
    ]


async def _collect(gen) -> bytes:
    out = b""
    async for chunk in gen:
        out += chunk
    return out


@pytest.mark.asyncio
async def test_head_multi_bytes_reader_no_headers():
    data = {"/a": b"a1\na2\na3\n", "/b": b"b1\nb2\n"}

    async def read(p):
        return data[p.virtual]

    out = await _collect(
        head_multi(_paths("/a", "/b"), read=read, n=1, show_headers=False))
    assert out == b"a1\nb1\n"


@pytest.mark.asyncio
async def test_head_multi_with_headers():
    data = {"/a": b"a1\na2\n", "/b": b"b1\nb2\n"}

    async def read(p):
        return data[p.virtual]

    out = await _collect(
        head_multi(_paths("/a", "/b"), read=read, n=1, show_headers=True))
    assert out == b"==> /a <==\na1\n\n==> /b <==\nb1\n"


@pytest.mark.asyncio
async def test_head_multi_stream_reader():
    chunks = {"/a": [b"a1\n", b"a2\n"], "/b": [b"b1\n"]}

    def read(p):

        async def gen():
            for ch in chunks[p.virtual]:
                yield ch

        return gen()

    out = await _collect(
        head_multi(_paths("/a", "/b"), read=read, n=5, show_headers=True))
    assert out == b"==> /a <==\na1\na2\n\n==> /b <==\nb1\n"


def _stdin(raw: str) -> PathSpec:
    virtual = "/dev/stdin" if raw == "/dev/stdin" else "/-"
    return PathSpec(vfs_path=virtual.strip("/"),
                    virtual=virtual,
                    directory="/",
                    resolved=True,
                    raw_path=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw, header", [
    ("-", b"==> standard input <==\n"),
    ("/dev/stdin", b"==> /dev/stdin <==\n"),
])
async def test_head_multi_names_stdin_the_way_gnu_does(raw, header):
    # GNU head 9.7 heads `-` "standard input", no parentheses, and
    # /dev/stdin as the path it is.

    async def read(p):
        return b"b\n"

    out = await _collect(
        head_multi([_stdin(raw)], read=read, n=1, show_headers=True))
    assert out == header + b"b\n"


@pytest.mark.asyncio
async def test_head_v_heads_a_stdin_nobody_named():
    # `printf 'b\n' | head -v` prints `==> standard input <==` first.

    async def unused(p):
        raise AssertionError(f"no operand to reach: {p}")

    out, io = await head_generic([], [],
                                 CommandOpts(flags={"verbose": True},
                                             stdin=b"b\n"), unused, unused)
    assert (await
            _collect(out), io.exit_code) == (b"==> standard input <==\nb\n", 0)

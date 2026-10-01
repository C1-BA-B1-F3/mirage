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


def test_tail_default(env):
    lines = "".join(f"line{i}\n" for i in range(1, 20))
    env.create_file("f.txt", lines.encode())
    assert env.mirage("tail /data/f.txt") == env.native("tail f.txt")


def test_tail_n3(env):
    env.create_file("f.txt", b"a\nb\nc\nd\ne\n")
    assert env.mirage("tail -n 3 /data/f.txt") == env.native("tail -n 3 f.txt")


def test_tail_c5(env):
    env.create_file("f.txt", b"hello world\n")
    assert env.mirage("tail -c 5 /data/f.txt") == env.native("tail -c 5 f.txt")


def test_tail_stdin(env):
    data = b"a\nb\nc\nd\ne\n"
    assert env.mirage("tail -n 3", stdin=data) == env.native(
        "tail -n 3", stdin=data
    )


def test_tail_plus_n(env):
    env.create_file("f.txt", b"a\nb\nc\nd\ne\n")
    assert env.mirage("tail -n +3 /data/f.txt") == env.native(
        "tail -n +3 f.txt"
    )


def test_tail_plus_n_stdin(env):
    data = b"a\nb\nc\nd\ne\n"
    assert env.mirage("tail -n +2", stdin=data) == env.native(
        "tail -n +2", stdin=data
    )


def test_tail_q(env):
    env.create_file("a.txt", b"aaa\n")
    result = env.mirage("tail -q /data/a.txt")
    assert "aaa" in result


def test_tail_v(env):
    env.create_file("a.txt", b"aaa\n")
    result = env.mirage("tail -v /data/a.txt")
    assert "aaa" in result

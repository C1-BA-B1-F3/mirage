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


def test_uniq_default(env):
    env.create_file("f.txt", b"a\na\nb\nc\nc\n")
    assert env.mirage("uniq /data/f.txt") == env.native("uniq f.txt")


def test_uniq_c(env):
    env.create_file("f.txt", b"a\na\nb\nc\nc\nc\n")
    m_lines = env.mirage("uniq -c /data/f.txt").strip().split("\n")
    n_lines = env.native("uniq -c f.txt").strip().split("\n")
    m_pairs = [(x.split()[0], x.split()[1]) for x in m_lines if x.strip()]
    n_pairs = [(x.split()[0], x.split()[1]) for x in n_lines if x.strip()]
    assert m_pairs == n_pairs


def test_uniq_d(env):
    env.create_file("f.txt", b"a\na\nb\nc\nc\n")
    assert env.mirage("uniq -d /data/f.txt") == env.native("uniq -d f.txt")


def test_uniq_u(env):
    env.create_file("f.txt", b"a\na\nb\nc\nc\n")
    assert env.mirage("uniq -u /data/f.txt") == env.native("uniq -u f.txt")


def test_uniq_stdin(env):
    data = b"a\na\nb\n"
    assert env.mirage("uniq", stdin=data) == env.native("uniq", stdin=data)


def test_uniq_i(env):
    data = b"Hello\nhello\nWorld\n"
    assert env.mirage("uniq -i", stdin=data) == env.native(
        "uniq -i", stdin=data
    )


def test_uniq_f(env):
    data = b"a 1\nb 1\nc 2\n"
    assert env.mirage("uniq -f 1", stdin=data) == env.native(
        "uniq -f 1", stdin=data
    )


def test_uniq_w(env):
    data = b"abc\nabd\nxyz\n"
    assert env.mirage("uniq -w 2", stdin=data) == "abc\nxyz\n"


def test_uniq_s(env):
    data = b"xxhello\nyyhello\nzzworld\n"
    assert env.mirage("uniq -s 2", stdin=data) == env.native(
        "uniq -s 2", stdin=data
    )

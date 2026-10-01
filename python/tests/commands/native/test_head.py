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


def test_head_default(env):
    lines = "".join(f"line{i}\n" for i in range(1, 20))
    env.create_file("f.txt", lines.encode())
    assert env.mirage("head /data/f.txt") == env.native("head f.txt")


def test_head_n5(env):
    env.create_file("f.txt", b"a\nb\nc\nd\ne\nf\n")
    assert env.mirage("head -n 5 /data/f.txt") == env.native("head -n 5 f.txt")


def test_head_c5(env):
    env.create_file("f.txt", b"hello world\n")
    assert env.mirage("head -c 5 /data/f.txt") == env.native("head -c 5 f.txt")


def test_head_stdin(env):
    data = b"a\nb\nc\nd\ne\nf\n"
    assert env.mirage("head -n 3", stdin=data) == env.native(
        "head -n 3", stdin=data
    )


def test_head_fewer_lines(env):
    env.create_file("f.txt", b"a\nb\n")
    assert env.mirage("head /data/f.txt") == env.native("head f.txt")

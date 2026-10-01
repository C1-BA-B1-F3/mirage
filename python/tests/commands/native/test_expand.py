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


def test_expand_default(env):
    data = b"hello\tworld\n"
    assert env.mirage("expand", stdin=data) == env.native("expand", stdin=data)


def test_expand_t(env):
    data = b"hello\tworld\n"
    assert env.mirage("expand -t 4", stdin=data) == env.native(
        "expand -t 4", stdin=data
    )


def test_expand_file(env):
    env.create_file("f.txt", b"a\tb\tc\n")
    assert env.mirage("expand /data/f.txt") == env.native("expand f.txt")


def test_expand_i(env):
    data = b"\thello\tworld\n"
    result = env.mirage("expand -i", stdin=data)
    assert result == "        hello\tworld\n"


def test_expand_i_multiple_leading(env):
    data = b"\t\thello\tworld\n"
    result = env.mirage("expand -i", stdin=data)
    assert result == "                hello\tworld\n"

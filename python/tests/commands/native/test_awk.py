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


def test_awk_print_field(env):
    data = b"alice 30\nbob 25\n"
    assert env.mirage("awk '{print $1}'", stdin=data) == env.native(
        "awk '{print $1}'", stdin=data
    )


def test_awk_F(env):
    data = b"a,b,c\n1,2,3\n"
    assert env.mirage("awk -F , '{print $2}'", stdin=data) == env.native(
        "awk -F , '{print $2}'", stdin=data
    )


def test_awk_file(env):
    env.create_file("f.txt", b"alice 30\nbob 25\n")
    assert env.mirage("awk '{print $2}' /data/f.txt") == env.native(
        "awk '{print $2}' f.txt"
    )


def test_awk_f(env):
    if env.resource_type == "redis":
        return
    env.create_file("prog.awk", b"{print $1}")
    env.create_file("data.txt", b"hello world\nfoo bar\n")
    assert env.mirage("awk -f /data/prog.awk /data/data.txt") == env.native(
        "awk -f prog.awk data.txt"
    )


def test_awk_v(env):
    env.create_file("f.txt", b"hello world\n")
    assert env.mirage("awk -v x=hello '{print x}' /data/f.txt") == env.native(
        "awk -v x=hello '{print x}' f.txt"
    )

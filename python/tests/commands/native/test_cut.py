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


def test_cut_f_d(env):
    env.create_file("f.txt", b"a:b:c\nd:e:f\n")
    assert env.mirage("cut -f 1 -d : /data/f.txt") == env.native(
        "cut -f 1 -d : f.txt"
    )


def test_cut_f_tab(env):
    env.create_file("f.txt", b"a\tb\tc\n")
    assert env.mirage("cut -f 2 /data/f.txt") == env.native("cut -f 2 f.txt")


def test_cut_c(env):
    env.create_file("f.txt", b"hello world\n")
    assert env.mirage("cut -c 1-5 /data/f.txt") == env.native(
        "cut -c 1-5 f.txt"
    )


def test_cut_stdin(env):
    data = b"a,b,c\nd,e,f\n"
    assert env.mirage("cut -f 1 -d ,", stdin=data) == env.native(
        "cut -f 1 -d ,", stdin=data
    )


def test_cut_complement(env):
    data = b"a:b:c:d\n"
    assert env.mirage("cut -d: -f2 --complement", stdin=data) == "a:c:d\n"


def test_cut_z(env):
    data = b"a:b\x00c:d\x00"
    result = env.mirage("cut -d: -f1 -z", stdin=data)
    assert result == "a\x00c\x00"

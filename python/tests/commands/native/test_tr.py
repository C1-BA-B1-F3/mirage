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


def test_tr_basic(env):
    data = b"hello\n"
    assert env.mirage("tr h H", stdin=data) == env.native("tr h H", stdin=data)


def test_tr_d(env):
    data = b"hello world\n"
    assert env.mirage("tr -d aeiou", stdin=data) == env.native(
        "tr -d aeiou", stdin=data
    )


def test_tr_s(env):
    data = b"baanaanaa\n"
    assert env.mirage("tr -s a", stdin=data) == env.native(
        "tr -s a", stdin=data
    )


def test_tr_range(env):
    data = b"hello\n"
    assert env.mirage("tr a-z A-Z", stdin=data) == env.native(
        "tr a-z A-Z", stdin=data
    )


def test_tr_cd(env):
    data = b"Hello World 123\n"
    assert env.mirage("tr -cd a-z", stdin=data) == env.native(
        "tr -cd a-z", stdin=data
    )

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


def test_comm_default(env):
    env.create_file("a.txt", b"a\nb\nc\n")
    env.create_file("b.txt", b"b\nc\nd\n")
    assert env.mirage("comm /data/a.txt /data/b.txt") == env.native(
        "comm a.txt b.txt"
    )


def test_comm_1(env):
    env.create_file("a.txt", b"a\nb\nc\n")
    env.create_file("b.txt", b"b\nc\nd\n")
    assert env.mirage("comm -1 /data/a.txt /data/b.txt") == env.native(
        "comm -1 a.txt b.txt"
    )


def test_comm_23(env):
    env.create_file("a.txt", b"a\nb\nc\n")
    env.create_file("b.txt", b"b\nc\nd\n")
    assert env.mirage("comm -23 /data/a.txt /data/b.txt") == env.native(
        "comm -23 a.txt b.txt"
    )


def test_comm_nocheck_order(env):
    env.create_file("a.txt", b"a\nb\nc\n")
    env.create_file("b.txt", b"b\nc\nd\n")
    assert env.mirage(
        "comm --nocheck-order /data/a.txt /data/b.txt"
    ) == env.mirage("comm /data/a.txt /data/b.txt")


def test_comm_3(env):
    env.create_file("a.txt", b"a\nb\nc\n")
    env.create_file("b.txt", b"b\nc\nd\n")
    assert env.mirage("comm -3 /data/a.txt /data/b.txt") == env.native(
        "comm -3 a.txt b.txt"
    )


def test_comm_check_order(env):
    env.create_file("a.txt", b"a\nb\nc\n")
    env.create_file("b.txt", b"b\nc\nd\n")
    result = env.mirage("comm --check-order /data/a.txt /data/b.txt")
    assert len(result) > 0

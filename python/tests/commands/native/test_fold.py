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


def test_fold_w(env):
    data = b"abcdefghijklmnopqrstuvwxyz\n"
    assert env.mirage("fold -w 10", stdin=data) == env.native(
        "fold -w 10", stdin=data
    )


def test_fold_file(env):
    env.create_file("f.txt", b"abcdefghijklmnopqrstuvwxyz\n")
    assert env.mirage("fold -w 10 /data/f.txt") == env.native(
        "fold -w 10 f.txt"
    )


def test_fold_s(env):
    data = b"hello world this is a test\n"
    assert env.mirage("fold -w 12 -s", stdin=data) == env.native(
        "fold -w 12 -s", stdin=data
    )

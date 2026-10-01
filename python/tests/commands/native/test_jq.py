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


def test_jq_r(env):
    data = b'{"name": "hello"}\n'
    assert env.mirage("jq -r .name", stdin=data) == env.native(
        "jq -r .name", stdin=data
    )


def test_jq_c(env):
    data = b'{"a": 1, "b": 2}\n'
    assert env.mirage("jq -c .", stdin=data) == env.native(
        "jq -c .", stdin=data
    )


def test_jq_s(env):
    data = b"1\n2\n3\n"
    assert env.mirage("jq -s .", stdin=data) == env.native(
        "jq -s .", stdin=data
    )

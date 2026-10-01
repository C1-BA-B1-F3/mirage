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


def test_echo_basic(env):
    assert env.mirage("echo hello world") == env.native("echo hello world")


def test_echo_n(env):
    assert env.mirage("echo -n hello") == env.native("/bin/echo -n hello")


def test_echo_e_newline(env):
    assert env.mirage(r"echo -e 'hello\nworld'") == env.native(
        r"printf '%s\n' 'hello' 'world'"
    )


def test_echo_e_tab(env):
    assert env.mirage(r"echo -e 'col1\tcol2'") == env.native(
        r"printf 'col1\tcol2\n'"
    )


def test_echo_e_backslash(env):
    assert env.mirage(r"echo -e 'a\\b'") == env.native(r"printf 'a\\b\n'")


def test_echo_e_carriage_return(env):
    assert env.mirage(r"echo -e 'hello\rbye'") == env.native(
        r"printf 'hello\rbye\n'"
    )


def test_echo_e_mixed(env):
    assert env.mirage(r"echo -e 'a\tb\nc'") == env.native(
        r"printf 'a\tb\nc\n'"
    )


def test_echo_e_no_escape(env):
    assert env.mirage("echo -e hello") == env.native("printf 'hello\n'")

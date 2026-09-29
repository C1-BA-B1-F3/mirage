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


def test_subshell_isolates_readonly(shell):
    out = shell.mirage("(readonly X=1); X=2; echo $X")
    assert out == "2\n"


def test_subshell_isolates_arrays(shell):
    out = shell.mirage('(a=(1 2 3)); echo "${a[0]:-empty}"')
    assert out == "empty\n"


def test_subshell_isolates_shell_options(shell):
    out = shell.mirage("set -e; (set +e; true); echo continued")
    assert out == "continued\n"


def test_function_prefix_is_restored_after_the_call(shell):
    out = shell.mirage(
        'f() { echo "FOO=$FOO"; }; FOO=bar f; echo "after=$FOO"')
    assert out == "FOO=bar\nafter=\n"


def test_command_prefix_does_not_persist(shell):
    out = shell.mirage('FOO=bar echo "FOO=$FOO"; echo "after=$FOO"')
    assert "after=\n" in out


def test_readonly_blocks_prefix_assignment(shell):
    out = shell.mirage("readonly X=1; X=2 echo done; echo $X")
    assert out.endswith("1\n")


def test_array_in_mixed_string_no_data_loss(shell):
    out = shell.mirage('a=(1 2 3); echo "x${a[@]}y"')
    assert "x" in out and "y" in out
    assert "1" in out and "3" in out


def test_array_single_element_with_prefix_suffix(shell):
    out = shell.mirage('a=(only); echo "x${a[@]}y"')
    assert out == "xonlyy\n"


def test_errexit_inside_subshell_body(shell):
    out = shell.mirage("set -e; (false; echo unreached); echo after")
    assert "unreached" not in out


def test_errexit_inside_function_body(shell):
    out = shell.mirage("set -e; f() { false; echo unreached; }; f; echo after")
    assert "unreached" not in out


def test_errexit_inside_compound_group(shell):
    out = shell.mirage("set -e; { false; echo unreached; }; echo after")
    assert "unreached" not in out

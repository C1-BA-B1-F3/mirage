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


def test_semicolon(shell):
    assert shell.mirage("echo hello; echo world") == shell.native(
        "echo hello; echo world"
    )


def test_and_success(shell):
    assert shell.mirage("true && echo yes") == shell.native("true && echo yes")


def test_and_failure(shell):
    assert shell.mirage("false && echo yes") == shell.native(
        "false && echo yes"
    )


def test_or_success(shell):
    assert shell.mirage("true || echo fallback") == shell.native(
        "true || echo fallback"
    )


def test_or_failure(shell):
    assert shell.mirage("false || echo fallback") == shell.native(
        "false || echo fallback"
    )


def test_and_or_chain(shell):
    assert shell.mirage("true && echo a || echo b") == shell.native(
        "true && echo a || echo b"
    )


def test_and_or_chain_fail(shell):
    assert shell.mirage("false && echo a || echo b") == shell.native(
        "false && echo a || echo b"
    )


def test_semicolon_continues_after_failure(shell):
    assert shell.mirage("false; echo still") == shell.native(
        "false; echo still"
    )


def test_exit_code_true(shell):
    assert shell.mirage_exit("true") == 0


def test_exit_code_false(shell):
    assert shell.mirage_exit("false") == 1


def test_and_chain_three(shell):
    cmd = "true && true && echo all_true"
    assert shell.mirage(cmd) == shell.native(cmd)


def test_or_chain_three(shell):
    cmd = "false || false || echo last_resort"
    assert shell.mirage(cmd) == shell.native(cmd)


def test_mixed_and_or_semi(shell):
    cmd = "echo a; false && echo b; echo c"
    assert shell.mirage(cmd) == shell.native(cmd)


def test_semicolon_three(shell):
    cmd = "echo a; echo b; echo c"
    assert shell.mirage(cmd) == shell.native(cmd)


def test_and_with_grep(shell):
    shell.create_file("f.txt", b"hello\n")
    m = shell.mirage("grep hello /data/f.txt && echo found")
    n = shell.native("grep hello f.txt && echo found")
    assert m == n


def test_or_with_grep(shell):
    shell.create_file("f.txt", b"hello\n")
    m = shell.mirage("grep nope /data/f.txt || echo missing")
    n = shell.native("grep nope f.txt || echo missing")
    assert m == n

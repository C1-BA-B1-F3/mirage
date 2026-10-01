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


def test_grep_q_in_if(shell):
    shell.create_file("f.txt", b"hello world\n")
    cmd_m = "if grep -q hello /data/f.txt; then echo found; fi"
    cmd_n = "if grep -q hello f.txt; then echo found; fi"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_grep_q_in_if_no_match(shell):
    shell.create_file("f.txt", b"hello world\n")
    cmd_m = (
        "if grep -q missing /data/f.txt; then echo found; else echo nope; fi"
    )
    cmd_n = "if grep -q missing f.txt; then echo found; else echo nope; fi"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_grep_q_in_and(shell):
    shell.create_file("f.txt", b"hello world\n")
    cmd_m = "grep -q hello /data/f.txt && echo yes"
    cmd_n = "grep -q hello f.txt && echo yes"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_grep_q_in_and_no_match(shell):
    shell.create_file("f.txt", b"hello world\n")
    cmd_m = "grep -q missing /data/f.txt && echo yes"
    cmd_n = "grep -q missing f.txt && echo yes"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_grep_q_in_or(shell):
    shell.create_file("f.txt", b"hello world\n")
    cmd_m = "grep -q missing /data/f.txt || echo fallback"
    cmd_n = "grep -q missing f.txt || echo fallback"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_grep_q_in_while(shell):
    shell.create_file("f.txt", b"hello\n")
    cmd_m = (
        "while grep -q missing /data/f.txt;"
        " do echo loop; break; done; echo done"
    )
    cmd_n = "while grep -q missing f.txt; do echo loop; break; done; echo done"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_pipe_stays_lazy(shell):
    shell.create_file("f.txt", b"hello\nworld\nfoo\nbar\n")
    cmd_m = "cat /data/f.txt | grep o"
    cmd_n = "cat f.txt | grep o"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_pipe_chain_stays_lazy(shell):
    shell.create_file("f.txt", b"c\na\nb\na\nc\n")
    cmd_m = "cat /data/f.txt | sort | uniq"
    cmd_n = "cat f.txt | sort | uniq"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_and_both_sides_output(shell):
    cmd = "echo a && echo b"
    assert shell.mirage(cmd) == shell.native(cmd)


def test_or_left_succeeds_output(shell):
    cmd = "echo a || echo b"
    assert shell.mirage(cmd) == shell.native(cmd)


def test_and_exit_code_on_failure(shell):
    assert shell.mirage_exit("false && echo yes") == shell.native_exit(
        "false && echo yes"
    )


def test_or_exit_code_on_success(shell):
    assert shell.mirage_exit("true || echo no") == shell.native_exit(
        "true || echo no"
    )


def test_redirect_materializes(shell):
    shell.create_file("f.txt", b"hello\nworld\n")
    cmd_m = "grep hello /data/f.txt > /data/out.txt; cat /data/out.txt"
    cmd_n = "grep hello f.txt > out.txt; cat out.txt"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_semicolon_exit_code_with_grep(shell):
    shell.create_file("f.txt", b"hello\n")
    cmd_m = "grep missing /data/f.txt; echo $?"
    cmd_n = "grep missing f.txt; echo $?"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)


def test_semicolon_materializes_both_sides(shell):
    shell.create_file("f.txt", b"hello\nworld\n")
    cmd_m = "grep hello /data/f.txt; grep world /data/f.txt"
    cmd_n = "grep hello f.txt; grep world f.txt"
    assert shell.mirage(cmd_m) == shell.native(cmd_n)

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


def test_grep_basic(env):
    env.create_file("f.txt", b"hello world\nfoo bar\nhello again\n")
    assert env.mirage("grep hello /data/f.txt") == env.native(
        "grep hello f.txt"
    )


def test_grep_i(env):
    env.create_file("f.txt", b"Hello\nworld\nHELLO\n")
    assert env.mirage("grep -i hello /data/f.txt") == env.native(
        "grep -i hello f.txt"
    )


def test_grep_v(env):
    env.create_file("f.txt", b"hello\nworld\nfoo\n")
    assert env.mirage("grep -v hello /data/f.txt") == env.native(
        "grep -v hello f.txt"
    )


def test_grep_n(env):
    env.create_file("f.txt", b"hello\nworld\nhello\n")
    assert env.mirage("grep -n hello /data/f.txt") == env.native(
        "grep -n hello f.txt"
    )


def test_grep_c(env):
    env.create_file("f.txt", b"hello\nworld\nhello\n")
    assert env.mirage("grep -c hello /data/f.txt") == env.native(
        "grep -c hello f.txt"
    )


def test_grep_w(env):
    env.create_file("f.txt", b"hello\nhelloworld\nhello there\n")
    assert env.mirage("grep -w hello /data/f.txt") == env.native(
        "grep -w hello f.txt"
    )


def test_grep_F(env):
    env.create_file("f.txt", b"a.b\na*b\naXb\n")
    assert env.mirage("grep -F 'a.b' /data/f.txt") == env.native(
        "grep -F 'a.b' f.txt"
    )


def test_grep_o(env):
    env.create_file("f.txt", b"hello world\nfoo hello\n")
    assert env.mirage("grep -o hello /data/f.txt") == env.native(
        "grep -o hello f.txt"
    )


def test_grep_m(env):
    env.create_file("f.txt", b"a\na\na\na\n")
    assert env.mirage("grep -m 2 a /data/f.txt") == env.native(
        "grep -m 2 a f.txt"
    )


def test_grep_iv(env):
    env.create_file("f.txt", b"Hello\nworld\nHELLO\nfoo\n")
    assert env.mirage("grep -iv hello /data/f.txt") == env.native(
        "grep -iv hello f.txt"
    )


def test_grep_nw(env):
    env.create_file("f.txt", b"hello\nhelloworld\nhello there\n")
    assert env.mirage("grep -nw hello /data/f.txt") == env.native(
        "grep -nw hello f.txt"
    )


def test_grep_Fc(env):
    env.create_file("f.txt", b"a.b\na.b\naXb\n")
    assert env.mirage("grep -Fc 'a.b' /data/f.txt") == env.native(
        "grep -Fc 'a.b' f.txt"
    )


def test_grep_no_match(env):
    env.create_file("f.txt", b"hello\nworld\n")
    assert env.mirage("grep zzz /data/f.txt") == env.native("grep zzz f.txt")


def test_grep_stdin(env):
    data = b"hello world\nfoo bar\nhello again\n"
    assert env.mirage("grep hello", stdin=data) == env.native(
        "grep hello", stdin=data
    )


def test_grep_stdin_i(env):
    data = b"Hello\nworld\nHELLO\n"
    assert env.mirage("grep -i hello", stdin=data) == env.native(
        "grep -i hello", stdin=data
    )


def test_grep_stdin_c(env):
    data = b"a\nb\na\n"
    assert env.mirage("grep -c a", stdin=data) == env.native(
        "grep -c a", stdin=data
    )


def test_grep_A(env):
    env.create_file("f.txt", b"a\nb\nc\nd\ne\n")
    assert env.mirage("grep -A 1 c /data/f.txt") == env.native(
        "grep -A 1 c f.txt"
    )


def test_grep_B(env):
    env.create_file("f.txt", b"a\nb\nc\nd\ne\n")
    assert env.mirage("grep -B 1 c /data/f.txt") == env.native(
        "grep -B 1 c f.txt"
    )


def test_grep_C(env):
    env.create_file("f.txt", b"a\nb\nc\nd\ne\n")
    assert env.mirage("grep -C 1 c /data/f.txt") == env.native(
        "grep -C 1 c f.txt"
    )


def test_grep_A_multiple_matches(env):
    env.create_file("f.txt", b"x\na\nb\nc\na\nd\ne\n")
    assert env.mirage("grep -A 1 a /data/f.txt") == env.native(
        "grep -A 1 a f.txt"
    )


def test_grep_B_multiple_matches(env):
    env.create_file("f.txt", b"x\ny\na\nb\nc\na\n")
    assert env.mirage("grep -B 1 a /data/f.txt") == env.native(
        "grep -B 1 a f.txt"
    )


def test_grep_C_multiple_matches(env):
    env.create_file("f.txt", b"w\nx\na\ny\nz\na\nb\n")
    assert env.mirage("grep -C 1 a /data/f.txt") == env.native(
        "grep -C 1 a f.txt"
    )


def test_grep_A_overlapping(env):
    env.create_file("f.txt", b"a\nb\na\nc\nd\n")
    assert env.mirage("grep -A 2 a /data/f.txt") == env.native(
        "grep -A 2 a f.txt"
    )


def test_grep_e_stdin(env):
    data = b"hello\nworld\nfoo\n"
    assert env.mirage("grep -e hello", stdin=data) == env.native(
        "grep -e hello", stdin=data
    )


def test_grep_An_combined(env):
    env.create_file("f.txt", b"a\nb\nc\nd\ne\n")
    assert env.mirage("grep -n -A 1 c /data/f.txt") == env.native(
        "grep -n -A 1 c f.txt"
    )


def test_grep_Ci(env):
    env.create_file("f.txt", b"aaa\nbbb\nAAA\nccc\n")
    assert env.mirage("grep -C 1 -i aaa /data/f.txt") == env.native(
        "grep -C 1 -i aaa f.txt"
    )


def test_grep_A_stdin(env):
    data = b"a\nb\nc\nd\ne\n"
    assert env.mirage("grep -A 1 c", stdin=data) == env.native(
        "grep -A 1 c", stdin=data
    )


def test_grep_C_stdin(env):
    data = b"a\nb\nc\nd\ne\n"
    assert env.mirage("grep -C 1 c", stdin=data) == env.native(
        "grep -C 1 c", stdin=data
    )


def test_grep_r(env):
    env.create_file("f.txt", b"hello\nworld\n")
    result = env.mirage("grep -r -l hello /data")
    assert "f.txt" in result


def test_grep_l(env):
    env.create_file("a.txt", b"hello\n")
    result = env.mirage("grep -r -l hello /data")
    assert "a.txt" in result


def test_grep_E(env):
    data = b"foo\nbar\nbaz\n"
    assert env.mirage("grep -E 'foo|bar'", stdin=data) == env.native(
        "grep -E 'foo|bar'", stdin=data
    )


def test_grep_q(env):
    env.create_file("f.txt", b"hello\n")
    result = env.mirage("grep -q hello /data/f.txt")
    assert result == ""


def test_grep_R(env):
    env.create_file("f.txt", b"hello\n")
    result = env.mirage("grep -R hello /data")
    assert "hello" in result


def test_grep_H(env):
    env.create_file("f.txt", b"hello\n")
    result = env.mirage("grep -H hello /data/f.txt")
    assert "hello" in result


def test_grep_h(env):
    env.create_file("f.txt", b"hello\n")
    result = env.mirage("grep -r -h hello /data")
    assert "hello" in result

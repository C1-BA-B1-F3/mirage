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


def test_wc_l(env):
    env.create_file("f.txt", b"a\nb\nc\n")
    assert (
        env.mirage("wc -l /data/f.txt").strip().split()[0]
        == env.native("wc -l f.txt").strip().split()[0]
    )


def test_wc_w(env):
    env.create_file("f.txt", b"hello world\nfoo\n")
    assert (
        env.mirage("wc -w /data/f.txt").strip().split()[0]
        == env.native("wc -w f.txt").strip().split()[0]
    )


def test_wc_c(env):
    env.create_file("f.txt", b"hello\n")
    assert (
        env.mirage("wc -c /data/f.txt").strip().split()[0]
        == env.native("wc -c f.txt").strip().split()[0]
    )


def test_wc_stdin_l(env):
    data = b"a\nb\nc\n"
    assert (
        env.mirage("wc -l", stdin=data).strip()
        == env.native("wc -l", stdin=data).strip()
    )


def test_wc_default_counts(env):
    env.create_file("f.txt", b"hello world\nfoo bar\n")
    m_parts = env.mirage("wc /data/f.txt").strip().split()
    n_parts = env.native("wc f.txt").strip().split()
    assert m_parts[:3] == n_parts[:3]


def test_wc_L(env):
    env.create_file("f.txt", b"short\na much longer line\nmed\n")
    assert (
        env.mirage("wc -L /data/f.txt").strip().split()[0]
        == env.native("wc -L f.txt").strip().split()[0]
    )


def test_wc_L_stdin(env):
    data = b"short\na much longer line\nmed\n"
    assert (
        env.mirage("wc -L", stdin=data).strip()
        == env.native("wc -L", stdin=data).strip()
    )


def test_wc_L_empty(env):
    env.create_file("f.txt", b"")
    assert (
        env.mirage("wc -L /data/f.txt").strip().split()[0]
        == env.native("wc -L f.txt").strip().split()[0]
    )


def test_wc_L_single_line(env):
    env.create_file("f.txt", b"hello world\n")
    assert (
        env.mirage("wc -L /data/f.txt").strip().split()[0]
        == env.native("wc -L f.txt").strip().split()[0]
    )


def test_wc_m(env):
    env.create_file("f.txt", b"hello\n")
    result = env.mirage("wc -m /data/f.txt").strip().split()[0]
    native = env.native("wc -m f.txt").strip().split()[0]
    assert result == native

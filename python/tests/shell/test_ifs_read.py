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


def test_ifs_comma_splits_read(shell):
    out = shell.mirage('IFS=, read a b c <<< "1,2,3"; echo "$a:$b:$c"')
    assert out == "1:2:3\n"


def test_ifs_default_whitespace(shell):
    out = shell.mirage('echo "1 2 3" | { read a b c; echo "$a:$b:$c"; }')
    assert out == "1:2:3\n"


def test_ifs_prefix_does_not_persist(shell):
    out = shell.mirage('IFS=, read a b c <<< "1,2,3"; '
                       'echo "${IFS-default}"')
    assert "," not in out


def test_env_prefix_to_command(shell):
    out = shell.mirage("FOO=bar bash -c 'echo $FOO'")
    assert "bar" in out


def test_env_prefix_after_word_expansion(shell):
    out = shell.mirage('FOO=bar bash -c "echo [$FOO]"')
    assert out == "[]\n"


def test_ifs_colon_split(shell):
    out = shell.mirage('IFS=: read a b c <<< "x:y:z"; echo "$a-$b-$c"')
    assert out == "x-y-z\n"


def test_read_trims_trailing_default_ifs_whitespace(shell):
    out = shell.mirage('read a b <<< "  x  y  "; echo "[$b]"')
    assert out == "[y]\n"


def test_read_single_var_keeps_inner_whitespace(shell):
    out = shell.mirage('read a <<< "  x  y  "; echo "[$a]"')
    assert out == "[x  y]\n"


def test_read_keeps_trailing_nonws_ifs_chars(shell):
    out = shell.mirage('IFS=: read a b <<< "x:y:z:"; echo "[$b]"')
    assert out == "[y:z:]\n"


def test_read_single_var_nonws_ifs_intact(shell):
    out = shell.mirage('IFS=: read a <<< ":x:"; echo "[$a]"')
    assert out == "[:x:]\n"


def test_read_rebinds_stdin_on_next_line(shell):
    shell.mirage('read za <<< "first"')
    out = shell.mirage('read zb <<< "second"; echo "$zb"')
    assert out == "second\n"


def test_read_pipe_after_previous_line(shell):
    shell.mirage("printf 'a\\n' | { read z1; echo $z1; }")
    out = shell.mirage("printf 'b\\n' | { read z2; echo $z2; }")
    assert out == "b\n"

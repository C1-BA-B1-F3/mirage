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

SELECT_CMD = "select x in aa bb; do echo got:$x; break; done"


def test_select_picks_choice_from_stdin(shell):
    code, out, err = shell.mirage_result(f"printf '2\\n' | {SELECT_CMD}")
    assert code == 0
    assert out == "got:bb\n"
    assert err == "1) aa\n2) bb\n#? "


def test_select_invalid_choice_sets_empty(shell):
    out = shell.mirage(
        "printf '9\\n' | select x in aa bb; do echo got:${x:-none}; break; "
        "done"
    )
    assert out == "got:none\n"


def test_select_reply_holds_raw_line(shell):
    out = shell.mirage(
        "printf 'zz\\n' | select x in aa bb; do echo r:$REPLY; break; done"
    )
    assert out == "r:zz\n"


def test_select_empty_line_redisplays_menu(shell):
    _, out, err = shell.mirage_result(f"printf '\\n2\\n' | {SELECT_CMD}")
    assert out == "got:bb\n"
    assert err == "1) aa\n2) bb\n#? 1) aa\n2) bb\n#? "


def test_select_eof_ends_loop(shell):
    # bash terminates the prompt line with a newline at EOF.
    code, out, err = shell.mirage_result(
        "printf '' | select x in aa bb; do echo body; done; echo after"
    )
    assert code == 0
    assert out == "\nafter\n"
    assert err == "1) aa\n2) bb\n#? "


def test_select_loops_until_break(shell):
    out = shell.mirage(
        "printf '1\\n2\\n' | select x in aa bb; do echo got:$x; "
        "if [ $x = bb ]; then break; fi; done"
    )
    assert out == "got:aa\ngot:bb\n"

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


def test_break_exits_inner_loop_only(shell):
    out = shell.mirage(
        "for i in 1 2; do for j in a b; do echo $i$j; break; done; done"
    )
    assert out == "1a\n2a\n"


def test_break_two_exits_both_loops(shell):
    out = shell.mirage(
        "for i in 1 2; do for j in a b; do echo $i$j; break 2; done; done"
    )
    assert out == "1a\n"


def test_break_level_beyond_depth_breaks_all(shell):
    out = shell.mirage(
        "for i in 1 2; do for j in a b; do echo $i$j; break 9; done; done"
    )
    assert out == "1a\n"


def test_continue_two_continues_outer_loop(shell):
    out = shell.mirage(
        "for i in 1 2; do for j in a b; do "
        "if [ $j = a ]; then continue 2; fi; echo $i$j; done; "
        "echo inner:$i; done"
    )
    assert out == ""


def test_continue_plain_skips_iteration(shell):
    out = shell.mirage(
        "for i in 1 2 3; do if [ $i = 2 ]; then continue; fi; echo $i; done"
    )
    assert out == "1\n3\n"


def test_break_two_in_while_inside_for(shell):
    out = shell.mirage(
        "for i in 1 2; do n=0; while [ $n -lt 3 ]; do "
        "n=$((n+1)); echo $i:$n; break 2; done; done"
    )
    assert out == "1:1\n"

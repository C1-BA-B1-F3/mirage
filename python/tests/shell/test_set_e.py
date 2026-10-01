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


def test_set_e_exits_on_failure(shell):
    out = shell.mirage("set -e; false; echo unreached")
    assert "unreached" not in out


def test_set_e_continues_when_passes(shell):
    out = shell.mirage("set -e; true; echo ok")
    assert out == "ok\n"


def test_set_e_allows_or_chain(shell):
    out = shell.mirage("set -e; false || echo recovered; echo done")
    assert out == "recovered\ndone\n"


def test_set_e_allows_and_chain_skip(shell):
    out = shell.mirage("set -e; false && echo skipped; echo done")
    assert out == "done\n"


def test_set_e_allows_if_condition(shell):
    out = shell.mirage("set -e; if false; then echo a; else echo b; fi")
    assert out == "b\n"


def test_set_e_allows_while_condition(shell):
    out = shell.mirage(
        "set -e; X=0; while [ $X -lt 2 ]; do echo $X; "
        "X=$((X+1)); done; echo done"
    )
    assert out == "0\n1\ndone\n"


def test_set_plus_e_disables(shell):
    out = shell.mirage("set -e; set +e; false; echo ok")
    assert out == "ok\n"


def test_set_o_errexit_alias(shell):
    out = shell.mirage("set -o errexit; false; echo unreached")
    assert "unreached" not in out


def test_set_e_pipeline_failure(shell):
    out = shell.mirage("set -e; false | true; echo after")
    assert out == "after\n"


def test_set_e_exits_on_and_list_tail_failure(shell):
    # bash exits when the command after the final && fails.
    out = shell.mirage("set -e; true && false; echo unreached")
    assert "unreached" not in out


def test_set_e_exits_on_or_list_tail_failure(shell):
    out = shell.mirage("set -e; false || false; echo unreached")
    assert "unreached" not in out


def test_set_e_negated_command_immune(shell):
    out = shell.mirage("set -e; ! true; echo ok")
    assert out == "ok\n"


def test_set_e_negated_pipeline_immune(shell):
    out = shell.mirage("set -e; ! true | true; echo ok")
    assert out == "ok\n"


def test_set_e_list_tail_in_and_of_negated(shell):
    out = shell.mirage("set -e; true && ! true; echo ok")
    assert out == "ok\n"

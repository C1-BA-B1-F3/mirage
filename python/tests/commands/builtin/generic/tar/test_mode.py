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

import pytest

from mirage.commands.builtin.generic.tar.mode import is_create_mode


def test_dash_c_and_long_create_turn_the_mode_on():
    assert is_create_mode(("-czf", "out.tgz", "dir"))
    assert is_create_mode(("--create", "-f", "out.tar", "dir"))


def test_extract_and_list_stay_off():
    assert not is_create_mode(("-xzf", "a.tgz", "./m/x.json"))
    assert not is_create_mode(("-tzf", "a.tgz"))


def test_only_the_first_word_may_be_a_dashless_cluster():
    assert is_create_mode(("cf", "a.tar", "d"))
    assert not is_create_mode(("-xf", "a.tar", "crate"))


def test_long_options_never_read_as_clusters():
    assert not is_create_mode(("--exclude", "c", "-xf", "a.tar"))


def test_option_terminator_ends_the_scan():
    # GNU reads everything after -- as an operand: `-c` and even `-C
    # out` name members there (`tar: -C: Not found in archive`).
    assert not is_create_mode(("-xf", "a.tar", "--", "-c"))
    assert not is_create_mode(("-xf", "a.tar", "--", "--create"))
    assert is_create_mode(("-cf", "a.tar", "--", "-c"))


@pytest.mark.parametrize(
    "argv,create",
    [
        (["--crea", "-f", "a.tar", "d"], True),
        (["--cr=x"], True),
        # Ambiguous in tar's own table, so no mode at all.
        (["--c", "-f", "a.tar"], False),
        (["--get", "-f", "a.tar"], False),
    ])
def test_a_long_word_reads_as_tars_getopt_long_reads_it(argv, create):
    assert is_create_mode(argv) is create

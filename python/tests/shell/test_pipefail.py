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


def test_pipefail_off_default(shell):
    assert shell.mirage("false | true; echo $?") == "0\n"


def test_pipefail_on_propagates_failure(shell):
    assert shell.mirage("set -o pipefail; false | true; echo $?") == "1\n"


def test_pipefail_zero_when_all_pass(shell):
    assert shell.mirage("set -o pipefail; true | true; echo $?") == "0\n"


def test_pipefail_disabled_via_plus_o(shell):
    assert (
        shell.mirage("set -o pipefail; set +o pipefail; false | true; echo $?")
        == "0\n"
    )


def test_pipefail_rightmost_failure(shell):
    assert (
        shell.mirage("set -o pipefail; false | false | true; echo $?") == "1\n"
    )

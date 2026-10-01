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


def test_declare_assigns_at_top_level(shell):
    assert shell.mirage("declare zd1=5; echo $zd1") == "5\n"


def test_declare_is_local_inside_function(shell):
    out = shell.mirage(
        "zf1() { declare dz=in; echo $dz; }; zf1; echo ${dz:-unset}"
    )
    assert out == "in\nunset\n"


def test_typeset_is_local_inside_function(shell):
    out = shell.mirage(
        "zf2() { typeset tz=in; echo $tz; }; zf2; echo ${tz:-unset}"
    )
    assert out == "in\nunset\n"


def test_declare_shadows_global_inside_function(shell):
    out = shell.mirage(
        "gv=g; zf3() { declare gv=l; echo $gv; }; zf3; echo $gv"
    )
    assert out == "l\ng\n"

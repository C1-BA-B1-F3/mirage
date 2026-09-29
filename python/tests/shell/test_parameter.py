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

from mirage.shell.parameter import scan_parameter


@pytest.mark.parametrize("reference,name,suffix",
                         [('$10', '1', '0'), ('$123abc', '1', '23abc'),
                          ('$49.99', '4', '9.99'), ('$00', '0', '0'),
                          ('${10}x', '10', 'x'), ('${0012}x', '0012', 'x'),
                          ('$name_12.x', 'name_12', '.x'),
                          ('${name_12}.x', 'name_12', '.x'),
                          ('$_x9-y', '_x9', '-y'), ('$a[0]', 'a', '[0]'),
                          ('$nameé', 'name', 'é'), ('$1é', '1', 'é'),
                          ('$@suffix', '@', 'suffix'),
                          ('$*suffix', '*', 'suffix'),
                          ('$#suffix', '#', 'suffix'),
                          ('$?suffix', '?', 'suffix'),
                          ('$$suffix', '$', 'suffix'),
                          ('$!suffix', '!', 'suffix'),
                          ('$-suffix', '-', 'suffix'),
                          ('${@}suffix', '@', 'suffix'),
                          ('${*}suffix', '*', 'suffix'),
                          ('${#}suffix', '#', 'suffix'),
                          ('${?}suffix', '?', 'suffix'),
                          ('${$}suffix', '$', 'suffix'),
                          ('${!}suffix', '!', 'suffix'),
                          ('${-}suffix', '-', 'suffix')])
@pytest.mark.parametrize("prefix", ["", "é💡 "])
def test_parameter_boundaries(reference, name, suffix, prefix):
    source = prefix + reference
    ref = scan_parameter(source, len(prefix))
    assert ref is not None
    actual_name, end = ref
    assert actual_name == name
    assert source[end:] == suffix


@pytest.mark.parametrize("reference", [
    '$', '$.', '$é', '$١', '$(', '$((', "$'quoted'", '$"quoted"', '${}',
    '${name', '${12abc}', '${name:-x}', '${#name}', '${!name}', '${a[0]}',
    '${name/x/y}', 'name'
])
def test_nonreferences_and_complex_expansions_are_not_consumed(reference):
    assert scan_parameter(reference, 0) is None

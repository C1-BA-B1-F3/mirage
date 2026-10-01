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

from mirage.shell.helpers import get_function_body
from mirage.shell.parse import parse
from mirage.shell.printer import function_text

# Each body as GNU bash 5.2.37 prints it under `declare -f f`.
_CASES = [
    (
        "f() { if a; then b; elif c; then d; else e; fi; }",
        "f () \n{ \n    if a; then\n        b;\n    else\n        if c; "
        "then\n            d;\n        else\n            e;\n        fi;\n"
        "    fi\n}",
    ),
    (
        "f() { for ((i=0;i<3;i++)); do echo $i; done; }",
        "f () \n{ \n    for ((i=0; i<3; i++))\n    do\n        echo $i;\n"
        "    done\n}",
    ),
    (
        "f() { case $1 in a) echo A;; b|c) echo BC;; *) echo other;; esac; }",
        "f () \n{ \n    case $1 in \n        a)\n            echo A\n"
        "        ;;\n        b | c)\n            echo BC\n        ;;\n"
        "        *)\n            echo other\n        ;;\n    esac\n}",
    ),
    ("f() { ( cd /; ls ); }", "f () \n{ \n    ( cd /;\n    ls )\n}"),
    (
        "f() { { echo a; echo b; } >out; }",
        "f () \n{ \n    { \n        echo a;\n        echo b\n    } > out\n}",
    ),
    (
        "f() { g() { echo inner; }; g; }",
        "f () \n{ \n    function g () \n    { \n        echo inner\n"
        "    };\n    g\n}",
    ),
    ("f() ( echo sub )", "f () \n{ \n    ( echo sub )\n}"),
    (
        "f() { echo a &> f; echo b &>> f; echo c >| f; cat <> f; "
        "echo d 3>&-; exec 4<&0; }",
        "f () \n{ \n    echo a &> f;\n    echo b &>> f;\n    echo c >| f;\n"
        "    cat 0<> f;\n    echo d 3>&-;\n    exec 4<&0\n}",
    ),
    (
        "f() { cat <<A; cat <<B\na\nA\nb\nB\n}",
        "f () \n{ \n    cat <<A\na\nA\n\n    cat <<B\nb\nB\n\n}",
    ),
    ("f() { echo $'it\\'s'; }", "f () \n{ \n    echo 'it'\\''s'\n}"),
    (
        "f() { echo a >&2; echo b 1>&2; cat <&3; cat 0<&3; echo c 2>&-; "
        "echo d >&-; cat 5<f; echo e 5>f; echo f 1>f; cat 0<f; cat 3<<<x; }",
        "f () \n{ \n    echo a 1>&2;\n    echo b 1>&2;\n    cat 0<&3;\n"
        "    cat 0<&3;\n    echo c 2>&-;\n    echo d 1>&-;\n    cat 5< f;\n"
        "    echo e 5> f;\n    echo f > f;\n    cat < f;\n    cat 3<<< x\n}",
    ),
    (
        "f() { x=$(a; b); y=$(a | b); z=$(if x; then y; fi); w=$( a && b ); }",
        "f () \n{ \n    x=$(a; b);\n    y=$(a | b);\n    z=$(if x; then\n"
        "    y;\nfi);\n    w=$(a && b)\n}",
    ),
    (
        "f() { [[ $x ]]; [[  a  ==  b  ]]; [[ a == b && c != d ]]; "
        '[[ (a) ]]; [[ !$x ]]; [[ a<b ]]; [[ "q" ]]; [[ -f x&&$a==b* ]]; }',
        "f () \n{ \n    [[ -n $x ]];\n    [[ a == b ]];\n"
        "    [[ a == b && c != d ]];\n    [[ ( -n a ) ]];\n"
        '    [[ -n !$x ]];\n    [[ a < b ]];\n    [[ -n "q" ]];\n'
        "    [[ -f x && -n $a==b* ]]\n}",
    ),
]


@pytest.mark.parametrize("source,expected", _CASES)
def test_function_text_prints_the_body_as_bash_does(source, expected):
    definition = parse(source).named_children[0]
    assert function_text("f", get_function_body(definition)) == expected

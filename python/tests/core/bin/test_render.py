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

from mirage.core.bin.render import render_stub


def test_stub_says_its_note_and_runs_the_command_by_name():
    assert render_stub("ls", "ls is built into mirage.") == (
        b'#!/bin/sh\n# ls is built into mirage.\ncommand ls "$@"\n')


def test_stub_quotes_a_name_the_shell_would_split():
    assert b"command 'my tool' \"$@\"" in render_stub("my tool", "note")

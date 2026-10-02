// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

// Startup letters bash has that `set` does not. `c` takes the program text
// from the next word and `s` reads it from stdin; the rest have nothing to
// configure in an embedded shell, which has no login profile, no rc file and
// no tty. Letters that name a `set` option (-e -u -x -f) are not here:
// parseOptionWord already knows them, so the two spellings cannot drift.
export const BASH_START_FLAGS = new Set(['c', 's', 'l', 'i'])

// bash's long options, mapped to whether the option takes the next word. A
// flat set of names to ignore cannot say that `--rcfile FILE` swallows FILE,
// and read `bash --rcfile run.sh` as "run run.sh". Anything absent is refused
// rather than mistaken for a script operand, which is what made
// `bash --version` report a missing file.
export const BASH_LONG_OPTIONS: Readonly<Record<string, boolean>> = Object.freeze({
  '--login': false,
  '--noediting': false,
  '--noprofile': false,
  '--norc': false,
  '--posix': false,
  '--init-file': true,
  '--rcfile': true,
})

// GNU prints the refusal and the usage line together, both under the
// builtin's own name as typed (`source` or `.`), and exits 2 without ending
// the script.
export const SOURCE_USAGE = 'filename argument required\n{name}: usage: {name} filename [arguments]'

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

export const SIGNAL_NAMES: readonly (readonly [string, number])[] = Object.freeze([
  ['HUP', 1],
  ['INT', 2],
  ['QUIT', 3],
  ['ILL', 4],
  ['TRAP', 5],
  ['ABRT', 6],
  ['FPE', 8],
  ['KILL', 9],
  ['SEGV', 11],
  ['BUS', 7],
  ['PIPE', 13],
  ['ALRM', 14],
  ['TERM', 15],
  ['USR1', 10],
  ['USR2', 12],
  ['CHLD', 17],
  ['URG', 23],
  ['STOP', 19],
  ['TSTP', 20],
  ['CONT', 18],
  ['TTIN', 21],
  ['TTOU', 22],
  ['SYS', 31],
  ['POLL', 29],
  ['VTALRM', 26],
  ['PROF', 27],
  ['XCPU', 24],
  ['XFSZ', 25],
  ['IOT', 6],
  ['CLD', 17],
  ['PWR', 30],
  ['WINCH', 28],
  ['IO', 29],
  ['STKFLT', 16],
  ['EXIT', 0],
])

export const SIGRTMIN = 34
export const SIGRTMAX = 64

export const SIGKILL = 9
export const SIGCHLD = 17
export const SIGSTOP = 19

// Signals whose default action leaves a process running: the command
// carries on past the deadline.
export const CONTINUE_SIGNALS: ReadonlySet<number> = new Set([0, SIGCHLD, 18, 23, 28])

// The job-control stops. timeout sends CONT after them unless run with
// --foreground, so there only the command stays stopped.
export const STOP_SIGNALS: ReadonlySet<number> = new Set([SIGSTOP, 20, 21, 22])

// What timeout cannot ignore when it signals its own process group, so it
// dies of them too: KILL, and the two glibc reserves for itself.
export const SELF_KILLING_SIGNALS: ReadonlySet<number> = new Set([SIGKILL, 32, 33])

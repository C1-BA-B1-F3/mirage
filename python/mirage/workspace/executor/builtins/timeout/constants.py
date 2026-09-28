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

# gnulib's sig2str table as glibc builds it on x86-64 Linux, in table
# order: a number's name is the first entry holding it (6 is ABRT, not
# IOT; 29 is POLL, not IO).
SIGNAL_NAMES: tuple[tuple[str, int], ...] = (
    ("HUP", 1),
    ("INT", 2),
    ("QUIT", 3),
    ("ILL", 4),
    ("TRAP", 5),
    ("ABRT", 6),
    ("FPE", 8),
    ("KILL", 9),
    ("SEGV", 11),
    ("BUS", 7),
    ("PIPE", 13),
    ("ALRM", 14),
    ("TERM", 15),
    ("USR1", 10),
    ("USR2", 12),
    ("CHLD", 17),
    ("URG", 23),
    ("STOP", 19),
    ("TSTP", 20),
    ("CONT", 18),
    ("TTIN", 21),
    ("TTOU", 22),
    ("SYS", 31),
    ("POLL", 29),
    ("VTALRM", 26),
    ("PROF", 27),
    ("XCPU", 24),
    ("XFSZ", 25),
    ("IOT", 6),
    ("CLD", 17),
    ("PWR", 30),
    ("WINCH", 28),
    ("IO", 29),
    ("STKFLT", 16),
    ("EXIT", 0),
)

SIGRTMIN = 34
SIGRTMAX = 64

SIGKILL = 9
SIGCHLD = 17
SIGSTOP = 19

# Signals whose default action leaves a process running: the command
# carries on past the deadline.
CONTINUE_SIGNALS = frozenset({0, SIGCHLD, 18, 23, 28})

# The job-control stops. timeout sends CONT after them unless run with
# --foreground, so there only the command stays stopped.
STOP_SIGNALS = frozenset({SIGSTOP, 20, 21, 22})

# What timeout cannot ignore when it signals its own process group, so
# it dies of them too: KILL, and the two glibc reserves for itself.
SELF_KILLING_SIGNALS = frozenset({SIGKILL, 32, 33})

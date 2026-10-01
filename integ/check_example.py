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
"""Run an example program and assert its whole output against a truth file.

Usage: python3 integ/check_example.py integ/truth/python/ram.json
       python3 integ/check_example.py --emit integ/truth/python/ram.json

Replaces the substring-matching check_lines.sh. Three things that could
not be asserted before are asserted now: the exit code, the ORDER of the
output, and every line of it rather than the handful a truth txt listed.

The truth file owns the command, so a workflow step names one path and
CI cannot drift from what the truth was captured against. A file may
declare several runs (the python and typescript spelling of the same
example); `--variant` picks one, and `--emit` runs every variant it can
and refuses to write if they disagree, which is what keeps a shared
truth file honest as a cross-language parity gate.

Line matchers, in the order of preference an author should reach for:
    "text"                        one line, exactly this
    {"re": "..."}                 one line, fullmatch of this pattern
    {"volatile": "sample"}        one line, content not asserted
    {"count": N, "sha256": "..."} N lines, digested (bulk data blocks)

`--emit` picks these itself: it runs the example twice and any line that
differs between the runs becomes a `re` with digit runs generalized, or
a `volatile` when even that does not hold. Tighten a `volatile` by hand
into an `re` whenever the line has a stable shape worth pinning.

Both of those runs happen on ONE machine, so `--emit` sees run-to-run
volatility and is blind to host-to-host volatility: a line that is
stable on the author's Mac and different on CI's Ubuntu is emitted as a
literal. Three classes of line have to be widened by hand after an
emit, all of which reached CI as literals before this was written down:

    a temp root      mkdtemp is /var/folders/... on macOS, /tmp on Linux
    a checkout mtime actions/checkout stamps the repo files on clone
    an env value     REDIS_URL is db 1 locally and db 0 on the runners

The rule of thumb: a literal earns its place when the example itself
determines it, and has to become an `re` when the machine does.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import NamedTuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIGEST_LINES = 40
BREAK_LINE = re.compile(r"^\s*$|^===|^---")
DIGITS = re.compile(r"\d+")

# A truth line is either the literal text or one of the escape objects
# the docstring lists; spelled out rather than left as `object`, which
# would push an isinstance chain onto every reader.
Matcher = str | dict[str, str | int]


class Run(NamedTuple):
    name: str
    command: list[str]
    cwd: str


class Capture(NamedTuple):
    lines: list[str]
    exit_code: int


def load_runs(truth: dict) -> list[Run]:
    """Read the run table out of a truth file.

    Args:
        truth (dict): the parsed truth file.

    Returns:
        list[Run]: one entry per declared variant.
    """
    runs = truth["runs"]
    return [
        Run(name=name, command=list(spec["command"]), cwd=spec.get("cwd", "."))
        for name, spec in runs.items()
    ]


def capture(run: Run) -> Capture:
    """Run one variant and collect its merged output.

    Args:
        run (Run): the variant to execute.

    Returns:
        Capture: the output lines and the process exit code.
    """
    proc = subprocess.run(
        run.command,
        cwd=os.path.join(REPO_ROOT, run.cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    text = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return Capture(lines=lines, exit_code=proc.returncode)


def digest(lines: list[str]) -> str:
    """Hash a block of lines the way a `count`/`sha256` matcher expects.

    Args:
        lines (list[str]): the block, without trailing newline handling.

    Returns:
        str: the hex sha256 of the newline-joined block.
    """
    body = "".join(line + "\n" for line in lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def generalize(first: str, second: str) -> str | None:
    """Derive a pattern covering two spellings of one volatile line.

    Only digit runs are generalized: a timestamp or a byte count differs
    between runs but keeps its shape, while a random temp-file name does
    not and is left for the caller to report as unasserted.

    Args:
        first (str): the line from the first run.
        second (str): the line from the second run.

    Returns:
        str | None: a fullmatch pattern, or None if it does not fit.
    """
    parts = DIGITS.split(first)
    pattern = r"\d+".join(re.escape(part) for part in parts)
    if re.fullmatch(pattern, first) and re.fullmatch(pattern, second):
        return pattern
    return None


def runs_of(lines: list[str]) -> list[tuple[int, int]]:
    """Split output into blocks a digest may collapse.

    A block breaks at a blank line and at the examples' own `===` and
    `---` section markers, so a bulk data dump becomes one long block
    while narrated output stays line by line.

    Args:
        lines (list[str]): the captured output.

    Returns:
        list[tuple[int, int]]: half-open [start, end) spans.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for index, line in enumerate(lines):
        if BREAK_LINE.match(line):
            if index > start:
                spans.append((start, index))
            spans.append((index, index + 1))
            start = index + 1
    if start < len(lines):
        spans.append((start, len(lines)))
    return spans


def build_lines(
    first: list[str], second: list[str], digest_over: int
) -> list[Matcher]:
    """Turn two captures into the truth file's matcher list.

    Args:
        first (list[str]): output of the first run.
        second (list[str]): output of the second run.
        digest_over (int): collapse blocks longer than this.

    Returns:
        list[Matcher]: the matchers, in output order.
    """
    out: list[Matcher] = []
    for start, end in runs_of(first):
        block = first[start:end]
        twin = second[start:end] if end <= len(second) else []
        if end - start > digest_over and block == twin:
            out.append({"count": end - start, "sha256": digest(block)})
            continue
        for offset, line in enumerate(block):
            other = twin[offset] if offset < len(twin) else None
            if other == line:
                out.append(line)
                continue
            pattern = generalize(line, other) if other is not None else None
            out.append({"re": pattern} if pattern else {"volatile": line})
    return out


def match_line(matcher: Matcher, line: str) -> str | None:
    """Test one line against one matcher.

    Args:
        matcher (Matcher): a string, `re`, or `volatile` matcher.
        line (str): the captured line.

    Returns:
        str | None: a failure description, or None when it matched.
    """
    if isinstance(matcher, str):
        return None if matcher == line else f"expected {matcher!r}"
    if "volatile" in matcher:
        return None
    pattern = matcher["re"]
    if re.fullmatch(pattern, line):
        return None
    return f"expected match /{pattern}/"


def compare(matchers: list[Matcher], lines: list[str]) -> list[str]:
    """Walk the matcher list against the captured output.

    Args:
        matchers (list[Matcher]): the truth file's line matchers.
        lines (list[str]): the captured output.

    Returns:
        list[str]: failure messages, empty when the output matched.
    """
    problems: list[str] = []
    cursor = 0
    for index, matcher in enumerate(matchers):
        if isinstance(matcher, dict) and "count" in matcher:
            count = matcher["count"]
            block = lines[cursor : cursor + count]
            if len(block) < count:
                problems.append(
                    f"line {cursor + 1}: output ended inside a "
                    f"{count}-line block"
                )
                return problems
            actual = digest(block)
            if actual != matcher["sha256"]:
                problems.append(
                    f"line {cursor + 1}: {count}-line block "
                    f"digest {actual[:16]} != "
                    f"{matcher['sha256'][:16]}"
                )
            cursor += count
            continue
        if cursor >= len(lines):
            problems.append(
                f"line {cursor + 1}: output ended, matcher "
                f"{index + 1} of {len(matchers)} unmatched"
            )
            return problems
        failure = match_line(matcher, lines[cursor])
        if failure:
            problems.append(
                f"line {cursor + 1}: {failure}, got {lines[cursor]!r}"
            )
        cursor += 1
    if cursor < len(lines):
        extra = len(lines) - cursor
        problems.append(
            f"line {cursor + 1}: {extra} unexpected trailing "
            f"line(s), first is {lines[cursor]!r}"
        )
    return problems


def check(truth: dict, path: str, variant: str | None) -> int:
    """Run the selected variant and report against the truth file.

    Args:
        truth (dict): the parsed truth file.
        path (str): the truth file's path, for messages.
        variant (str | None): which run to execute.

    Returns:
        int: the process exit status.
    """
    runs = load_runs(truth)
    if variant is not None:
        runs = [run for run in runs if run.name == variant]
        if not runs:
            print(
                f"FAIL: {path} declares no run named {variant!r}",
                file=sys.stderr,
            )
            return 1
    elif len(runs) != 1:
        names = ", ".join(run.name for run in runs)
        print(
            f"FAIL: {path} declares runs ({names}); pass --variant",
            file=sys.stderr,
        )
        return 1
    run = runs[0]
    result = capture(run)
    problems = compare(truth["lines"], result.lines)
    if result.exit_code != truth["exit"]:
        problems.insert(
            0, f"exit {result.exit_code}, expected {truth['exit']}"
        )
    if problems:
        print(f"FAIL: {path} [{run.name}]", file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        if len(problems) > 20:
            print(f"  ... and {len(problems) - 20} more", file=sys.stderr)
        return 1
    print(
        f"OK: {path} [{run.name}] "
        f"({len(truth['lines'])} matchers, {len(result.lines)} lines)"
    )
    return 0


def emit(truth: dict, path: str, variant: str | None, digest_over: int) -> int:
    """Recapture the truth file from live runs.

    Every variant runs twice: twice to spot volatile lines, and every
    variant so a shared truth file cannot record one language's output
    as if both produced it.

    Args:
        truth (dict): the parsed truth file.
        path (str): the truth file's path.
        variant (str | None): restrict to one run, or None for all.
        digest_over (int): collapse blocks longer than this.

    Returns:
        int: the process exit status.
    """
    runs = load_runs(truth)
    if variant is not None:
        runs = [run for run in runs if run.name == variant]
    captured: dict[str, list[Matcher]] = {}
    exits: dict[str, int] = {}
    for run in runs:
        first = capture(run)
        second = capture(run)
        captured[run.name] = build_lines(
            first.lines, second.lines, digest_over
        )
        exits[run.name] = first.exit_code
        print(
            f"  captured {run.name}: {len(first.lines)} lines, "
            f"exit {first.exit_code}",
            file=sys.stderr,
        )
    names = list(captured)
    for name in names[1:]:
        if (
            captured[name] != captured[names[0]]
            or exits[name] != exits[names[0]]
        ):
            print(
                f"FAIL: {path} runs {names[0]!r} and {name!r} disagree; "
                "a shared truth file must hold for both",
                file=sys.stderr,
            )
            return 1
    truth["lines"] = captured[names[0]]
    truth["exit"] = exits[names[0]]
    with open(os.path.join(REPO_ROOT, path), "w", encoding="utf-8") as fh:
        json.dump(truth, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"WROTE: {path} ({len(truth['lines'])} matchers)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("truth")
    parser.add_argument("--variant")
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--digest-over", type=int, default=DIGEST_LINES)
    args = parser.parse_args()
    with open(os.path.join(REPO_ROOT, args.truth), encoding="utf-8") as fh:
        truth = json.load(fh)
    if args.emit:
        return emit(truth, args.truth, args.variant, args.digest_over)
    return check(truth, args.truth, args.variant)


if __name__ == "__main__":
    sys.exit(main())

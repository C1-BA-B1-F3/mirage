from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = REPO / "python"
# A path handed to a function that declared PathSpec. Narrow on purpose:
# running full strict over python/tests reports ~2374 errors, of which
# 634 are `str` where a pydantic field declares SecretStr (which pydantic
# coerces at runtime) and most of the rest are the monkeypatched fakes
# CLAUDE.md sanctions. Neither is a defect, so gating on them would buy
# noise. This one class is a real rule violation every time: the callee
# reads `.mount_path` or `.virtual`, so a bare string is an
# AttributeError waiting for the branch to be reached -- which is
# exactly how it survived in tests/e2e/test_snapshot_drift_live.py,
# skipped without a live versioned bucket.
PATTERN = re.compile(
    r"^(?P<loc>[^:]+:\d+): error: Argument .*? has "
    r'incompatible type "str"; expected "PathSpec'
)


def main() -> int:
    """Fail when a test hands a bare str to a PathSpec parameter.

    Returns:
        0 when no test violates the rule, 1 otherwise.
    """
    proc = subprocess.run(
        [
            str(PY / ".venv/bin/mypy"),
            "--namespace-packages",
            "--explicit-package-bases",
            "tests",
        ],
        cwd=PY,
        capture_output=True,
        text=True,
    )
    hits = [
        m.group("loc")
        for line in proc.stdout.splitlines()
        if (m := PATTERN.match(line))
    ]
    if hits:
        print(
            f"{len(hits)} test call site(s) pass a str where the callee "
            f"declares PathSpec. Wrap the path in a PathSpec -- the callee "
            f"reads its fields, so the string only survives until that "
            f"branch runs:\n  " + "\n  ".join(hits),
            file=sys.stderr,
        )
        return 1
    print(
        "test PathSpec discipline: no bare strings passed to PathSpec "
        "parameters"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

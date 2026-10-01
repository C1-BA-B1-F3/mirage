from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TS_SRC = [
    REPO / "typescript/packages/core/src",
    REPO / "typescript/packages/node/src",
    REPO / "typescript/packages/browser/src",
]
# `normalizeFields(input, {rename: {...}})` and the shared rename-map
# constants the S3-alias families feed it. The declaration matters as much
# as the map: `export const`, a type annotation between the name and the
# `=`, and a camelCase name are all forms in use, and a pattern that misses
# one lets a redundant entry through in silence -- which is exactly what
# `export const S3_BROWSER_RENAME` did to the first version of this gate.
RENAME_PROP_RE = re.compile(r"rename:\s*\{([^{}]*)\}", re.S)
RENAME_CONST_RE = re.compile(
    r"^(?:export\s+)?const\s+\w*rename\w*[^=\n]*=\s*\{([^{}]*)\}",
    re.M | re.S | re.I,
)
# The key may be bare or quoted (either style); the value is a string
# literal, so it is always quoted.
PAIR_RE = re.compile(
    r"""['"]?([A-Za-z0-9_]+)['"]?\s*:\s*['"]([A-Za-z0-9_]+)['"]"""
)
SNAKE_RE = re.compile(r"_([a-z0-9])")


def snake_to_camel(snake: str) -> str:
    """Reimplement `snakeToCamel` from utils/normalize.ts.

    Args:
        snake: The python-side field name.

    Returns:
        The camelCase spelling `normalizeFields` produces by default.
    """
    return SNAKE_RE.sub(lambda m: m.group(1).upper(), snake)


def redundant_pairs(text: str) -> list[tuple[str, str]]:
    """Find rename entries that only restate the default mapping.

    Args:
        text: One TypeScript source file.

    Returns:
        The `(source, target)` pairs whose target is exactly what
        `snakeToCamel` would have produced anyway.
    """
    found: list[tuple[str, str]] = []
    for match in RENAME_PROP_RE.finditer(text):
        found.extend(PAIR_RE.findall(match.group(1)))
    for match in RENAME_CONST_RE.finditer(text):
        found.extend(PAIR_RE.findall(match.group(1)))
    return [(k, v) for k, v in found if snake_to_camel(k) == v]


def source_files() -> list[Path]:
    """Every TypeScript source file that could hold a rename map.

    Returns:
        The files to scan, build output and node_modules excluded.
    """
    out: list[Path] = []
    for root in TS_SRC:
        if not root.is_dir():
            continue
        out.extend(
            p
            for p in root.rglob("*.ts")
            if "node_modules" not in p.parts and "dist" not in p.parts
        )
    return sorted(out)


# One fixture per declaration form the codebase actually uses, plus the
# negatives. The first version of this gate matched only lines beginning
# with `const` and only bare keys, so `export const S3_BROWSER_RENAME` --
# added in the same change -- was invisible to it. A pattern this gate
# cannot see is worse than no gate: it reports success over a blind spot.
SELFTEST_CASES: tuple[tuple[str, str, bool], ...] = (
    (
        "a bare const map",
        "const RENAME: Record<string, string> = {\n  api_key: 'apiKey',\n}\n",
        True,
    ),
    (
        "an exported const map",
        "export const S3_RENAME: Record<string, string> = {\n"
        "  api_key: 'apiKey',\n}\n",
        True,
    ),
    (
        "a camelCase map name",
        "const renameMap = {\n  api_key: 'apiKey',\n}\n",
        True,
    ),
    (
        "a single-quoted key",
        "normalizeFields(input, {\n  rename: {\n"
        "    'api_key': 'apiKey',\n  },\n})\n",
        True,
    ),
    (
        "a double-quoted key",
        "normalizeFields(input, {\n  rename: {\n"
        '    "api_key": "apiKey",\n  },\n})\n',
        True,
    ),
    (
        "an inline rename property",
        "normalizeFields(input, {\n  rename: { api_key: 'apiKey' },\n})\n",
        True,
    ),
    (
        "a multi-line rename property",
        "normalizeFields(input, {\n  rename: {\n"
        "    board_ids: 'boardIds',\n  },\n})\n",
        True,
    ),
    (
        "a load-bearing override",
        "normalizeFields(input, {\n"
        "  rename: { endpoint_url: 'endpoint' },\n})\n",
        False,
    ),
    (
        "load-bearing overrides in a const",
        "export const R = {\n  timeout: 'timeoutMs',\n"
        "  aws_profile: 'profile',\n  path_style: 'forcePathStyle',\n}\n",
        False,
    ),
    (
        "an object that is not a rename map",
        "const opts = { mode: 'fast' }\n",
        False,
    ),
)


def selftest() -> int:
    """Prove the gate can see every declaration form before trusting it.

    Returns:
        0 when every fixture is classified as expected.
    """
    failures = 0
    for name, source, expected in SELFTEST_CASES:
        found = bool(redundant_pairs(source))
        if found == expected:
            print(f"  ok   {name}")
            continue
        failures += 1
        want = "flagged" if expected else "ignored"
        print(f"  FAIL {name}: should be {want}, was not")
    if failures:
        print(
            f"\n{failures} selftest case(s) failed; the gate is blind to "
            "a form in use."
        )
        return 1
    print(f"\nselftest OK: {len(SELFTEST_CASES)} declaration forms covered")
    return 0


def main() -> int:
    """Fail when a rename map restates what `snakeToCamel` already does.

    `normalizeFields` falls back to `snakeToCamel(key)` for every key no
    rename names, so `api_key: 'apiKey'` is not configuration, it is a
    second place for the same fact to be wrong -- and it hides the entries
    that *are* load-bearing (`endpoint_url: 'endpoint'`, `timeout:
    'timeoutMs'`, `aws_profile: 'profile'`) in a wall of noise.

    Returns:
        0 when every surviving rename entry is a real override.
    """
    if "--selftest" in sys.argv[1:]:
        return selftest()
    offenders: list[tuple[Path, list[tuple[str, str]]]] = []
    for path in source_files():
        if path.name == "normalize.test.ts":
            continue
        pairs = redundant_pairs(path.read_text())
        if pairs:
            offenders.append((path, pairs))
    if not offenders:
        return 0
    total = sum(len(p) for _, p in offenders)
    print(f"{total} rename entries only restate snakeToCamel:\n")
    for path, pairs in offenders:
        print(f"  {path.relative_to(REPO)}")
        for key, value in pairs:
            print(f"      {key}: '{value}'")
    print("\nDelete them: normalizeFields already maps these by default.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

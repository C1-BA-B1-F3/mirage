"""Compare VFS prompts after language escapes and formatting whitespace.

Node evaluates TypeScript string literals; Python's AST reads string constants.
Neither a second JS string parser nor backend imports are needed. Every prompt
and write prompt must have a peer. Runtime differences need named reasons, and
an exception that no longer describes a difference fails the gate.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
LOAD_TS = """
import { pathToFileURL } from 'node:url';
const result = {};
for (const path of process.argv.slice(1)) {
  result[path] = await import(pathToFileURL(path).href);
}
process.stdout.write(JSON.stringify(result));
"""


def normalize(value: str, *, python: bool = False) -> str:
    if python:
        value = value.replace('{{', '{').replace('}}', '}')
    return ' '.join(value.split())


def python_prompts(path: Path) -> dict[str, str]:
    prompts: dict[str, str] = {}
    for statement in ast.parse(path.read_text()).body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name) and target.id.endswith('PROMPT'):
                value = ast.literal_eval(statement.value)
                if not isinstance(value, str):
                    raise ValueError(f'{path}: {target.id} is not a string')
                prompts[target.id] = normalize(value, python=True)
    if not prompts:
        raise ValueError(f'{path}: no prompt constants found')
    return prompts


def typescript_prompts(paths: list[Path]) -> dict[str, dict[str, str]]:
    run = subprocess.run([
        'node', '--experimental-strip-types', '--input-type=module', '-e',
        LOAD_TS, *map(str, paths)
    ],
                         check=True,
                         capture_output=True,
                         text=True)
    loaded = json.loads(run.stdout)
    prompts: dict[str, dict[str, str]] = {}
    for path in paths:
        values = loaded[str(path)]
        prefix = path.parent.name.upper() + '_'
        found: dict[str, str] = {}
        for name, value in values.items():
            if not name.endswith('PROMPT'):
                continue
            if not name.startswith(prefix) or not isinstance(value, str):
                raise ValueError(f'{path}: unsupported prompt {name}')
            key = name[len(prefix):]
            if key == 'BROWSER_PROMPT':
                key = 'PROMPT'
            if key in found:
                raise ValueError(f'{path}: duplicate prompt {key}')
            found[key] = normalize(value)
        if not found:
            raise ValueError(f'{path}: no prompt constants found')
        prompts[str(path)] = found
    return prompts


def differences(repo: Path) -> dict[str, str]:
    py = {
        p.parent.name: python_prompts(p)
        for p in sorted((repo / 'python/mirage/vfs').glob('*/prompt.py'))
    }
    paths = sorted(
        (repo / 'typescript/packages').glob('*/src/vfs/*/prompt.ts'))
    if not py or not paths:
        raise ValueError('no VFS prompts discovered')
    ts = typescript_prompts(paths)
    gaps: dict[str, str] = {}
    seen: set[str] = set()
    for path in paths:
        backend = path.parent.name
        runtime = path.relative_to(repo / 'typescript/packages').parts[0]
        seen.add(backend)
        a, b = py.get(backend, {}), ts[str(path)]
        for name in sorted(a.keys() | b.keys()):
            key = f'{runtime}/{backend}/{name}'
            if name not in a:
                gaps[key] = 'missing Python prompt'
            elif name not in b:
                gaps[key] = 'missing TypeScript prompt'
            elif a[name] != b[name]:
                gaps[key] = 'prompt text differs'
    for backend in sorted(py.keys() - seen):
        for name in py[backend]:
            gaps[f'python/{backend}/{name}'] = 'missing TypeScript backend'
    return gaps


def violations(gaps: dict[str, str], exceptions: dict[str, str]) -> list[str]:
    errors = [
        f'{key}: {reason}' for key, reason in sorted(gaps.items())
        if key not in exceptions
    ]
    for key, reason in sorted(exceptions.items()):
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f'{key}: exception needs a reason')
        if key not in gaps:
            errors.append(f'{key}: stale exception')
    return errors


def selftest() -> None:
    assert normalize(' {prefix}  {{"x": 1}} ',
                     python=True) == '{prefix} {"x": 1}'
    assert normalize('a\\nb') != normalize('a\nb')
    assert normalize('a\n  b') == normalize('a b')
    assert violations({'core/a/WRITE_PROMPT': 'missing'}, {})
    assert not violations({'browser/a/PROMPT': 'diff'},
                          {'browser/a/PROMPT': 'runtime'})
    assert violations({}, {'browser/a/PROMPT': 'runtime'})
    assert violations({'browser/a/PROMPT': 'diff'}, {'browser/a/PROMPT': ''})
    with TemporaryDirectory() as directory:
        repo = Path(directory)
        py = repo / 'python/mirage/vfs/demo/prompt.py'
        ts = repo / 'typescript/packages/core/src/vfs/demo/prompt.ts'
        py.parent.mkdir(parents=True)
        ts.parent.mkdir(parents=True)
        # Literal backslash-n, a backtick, braces and Unicode must survive
        # language decoding without losing their meaning.
        value = '{prefix} {"x": "é\\n`"}'
        py.write_text('PROMPT = ' +
                      repr(value.replace('{"', '{{"').replace('"}', '"}}')) +
                      '\n')
        ts.write_text('export const DEMO_PROMPT: string = ' +
                      json.dumps(value) + '\n')
        assert differences(repo) == {}
        ts.write_text(ts.read_text() +
                      'export const DEMO_WRITE_PROMPT = `write`\n')
        assert differences(repo) == {
            'core/demo/WRITE_PROMPT': 'missing Python prompt'
        }
        ts.write_text('export const DEMO_PROMPT = `wrong`\n')
        assert differences(repo) == {'core/demo/PROMPT': 'prompt text differs'}
        ts.unlink()
        other = ts.parent.parent / 'other/prompt.ts'
        other.parent.mkdir()
        other.write_text('export const OTHER_PROMPT = "x"\n')
        assert differences(repo) == {
            'core/other/PROMPT': 'missing Python prompt',
            'python/demo/PROMPT': 'missing TypeScript backend',
        }
    print('Prompt parity self-tests passed')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        selftest()
    gaps = differences(REPO)
    exceptions = json.loads((REPO / 'spec/prompt_exceptions.json').read_text())
    errors = violations(gaps, exceptions)
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'VFS prompt parity passed ({len(exceptions)} runtime differences)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

import subprocess
import zlib

import pytest

from mirage.commands.cli.builtin.git import GIT

from .conftest import mounted, pack_everything


@pytest.mark.asyncio
@pytest.mark.parametrize('packed', [False, True])
async def test_fsck_real_objects_and_missing_blob(repo_path, packed):
    if packed:
        pack_everything(repo_path)
    with mounted(repo_path) as ws:
        ws.register_cli('git', GIT)
        result = await ws.shell('git -C /repo fsck --no-dangling')
        assert result.exit_code == 0, await result.stderr_str()
    if not packed:
        oid = subprocess.check_output(
            ['git', '-C',
             str(repo_path), 'rev-parse', 'HEAD:a.txt'],
            text=True).strip()
        (repo_path / '.git' / 'objects' / oid[:2] / oid[2:]).unlink()
        with mounted(repo_path) as ws:
            ws.register_cli('git', GIT)
            result = await ws.shell('git -C /repo fsck --no-dangling')
            assert result.exit_code != 0
            assert oid in await result.stderr_str()


@pytest.mark.asyncio
@pytest.mark.parametrize('damage',
                         ['hash', 'zlib', 'pack', 'pack_content', 'index'])
async def test_fsck_rejects_corrupt_objects(repo_path, damage):
    oid = subprocess.check_output(
        ['git', '-C', str(repo_path), 'rev-parse', 'HEAD:a.txt'],
        text=True).strip()
    if damage in ('pack', 'pack_content', 'index'):
        pack_everything(repo_path)
        suffix = 'idx' if damage == 'index' else 'pack'
        path = next((repo_path / '.git/objects/pack').glob(f'*.{suffix}'))
        content = bytearray(path.read_bytes())
        content[12 if damage == 'pack_content' else -1] ^= 0xff
        path.chmod(0o600)
        path.write_bytes(content)
        diagnostic = 'checksum'
    else:
        path = repo_path / '.git/objects' / oid[:2] / oid[2:]
        path.chmod(0o600)
        path.write_bytes(
            zlib.compress(b'blob 7\0damaged') if damage ==
            'hash' else b'broken zlib')
        diagnostic = oid
    native = subprocess.run(
        ['git', '-C', str(repo_path), 'fsck', '--no-dangling'],
        capture_output=True)
    assert native.returncode != 0
    with mounted(repo_path) as ws:
        ws.register_cli('git', GIT)
        result = await ws.shell('git -C /repo fsck --no-dangling')
        assert result.exit_code != 0
        assert diagnostic in (await result.stderr_str()).lower()

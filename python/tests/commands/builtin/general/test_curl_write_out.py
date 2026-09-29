import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from mirage.commands.builtin.errors import HttpConnectError, HttpTimeoutError
from mirage.commands.builtin.general.curl import curl
from mirage.commands.builtin.general.wget import wget
from mirage.commands.builtin.utils.http import HttpResponse
from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

CASES = json.loads((Path(__file__).resolve().parents[5] /
                    'integ/vfs/http/curl_write_out.json').read_text())['cases']


def response(url, **kwargs):
    if ':9/' in url:
        raise HttpConnectError('127.0.0.1', 9)
    status = 404 if url.endswith('/missing') else 200
    return HttpResponse(
        status,
        'Not Found' if status == 404 else 'OK',
        b'not found\n' if status == 404 else b'hello from http\n',
        url,
        headers=(('content-type', 'text/plain'), ))


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
async def test_http_shell_regressions(case, monkeypatch):
    monkeypatch.setitem(curl.__wrapped__.__globals__, 'http_request', response)
    monkeypatch.setitem(wget.__wrapped__.__globals__, 'http_get', response)
    with Workspace({'/data': RAMVFS()}, mode=MountMode.EXEC) as ws:
        result = await ws.shell(case['command'].replace(
            '{mount}', '/data').replace('{http}', 'https://example.test'))
        assert result.exit_code == case['expect']['exit']
        assert await result.stdout_str() == case['expect']['stdout']
        assert await result.stderr_str() == case['expect']['stderr']


@pytest.mark.asyncio
@pytest.mark.parametrize('argument,seconds', [('--timeout=0.25', 0.25),
                                              ('-T 0', None)])
async def test_wget_passes_timeout_and_classifies_failure(
        argument, seconds, monkeypatch):
    request = Mock(side_effect=HttpTimeoutError('example.test', 443, 250))
    monkeypatch.setitem(wget.__wrapped__.__globals__, 'http_get', request)
    with Workspace({}) as ws:
        result = await ws.shell(
            f'wget {argument} -q -O - https://example.test/hello')
        assert result.exit_code == 4
        assert not result.stderr
        assert request.call_args.kwargs['timeout'] == seconds

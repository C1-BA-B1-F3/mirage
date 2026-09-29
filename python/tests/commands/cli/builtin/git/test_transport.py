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

import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from mirage.commands.cli.builtin.git import GIT
from mirage.commands.cli.builtin.git.errors import GitError
from mirage.commands.cli.builtin.git.transport import (display_url,
                                                       extra_headers,
                                                       parse_advertisement,
                                                       pkt_line, pkt_lines)
from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

ENV = {
    **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "A",
    "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A",
    "GIT_COMMITTER_EMAIL": "a@example.com"
}


def test_pkt_lines_round_trip_with_flushes():
    stream = pkt_line(b"one\n") + b"0000" + pkt_line(b"two")
    assert list(pkt_lines(stream)) == [b"one\n", None, b"two"]


def test_a_bad_length_is_git_s_protocol_error():
    with pytest.raises(GitError, match="bad line length character: zz00"):
        list(pkt_lines(b"zz00"))


def test_an_advertisement_reads_refs_peeled_tags_and_the_head_symref():
    oid, tag, peeled = "a" * 40, "b" * 40, "c" * 40
    lines = [
        f"{oid} HEAD\0side-band-64k symref=HEAD:refs/heads/main\n".encode(),
        f"{oid} refs/heads/main\n".encode(), f"{tag} refs/tags/v1\n".encode(),
        f"{peeled} refs/tags/v1^{{}}\n".encode(), None
    ]
    adv = parse_advertisement(iter(lines))
    assert adv.refs == {
        "HEAD": oid,
        "refs/heads/main": oid,
        "refs/tags/v1": tag
    }
    assert adv.peeled == {"refs/tags/v1": peeled}
    assert adv.head == "refs/heads/main"


def test_an_empty_repository_advertises_nothing():
    zero = "0" * 40
    line = f"{zero} capabilities^{{}}\0agent=git/2\n".encode()
    assert parse_advertisement(iter([line, None])).refs == {}


@pytest.mark.parametrize("url,expected", [
    ("https://user:token@github.com/o/r.git", "https://github.com/o/r"),
    ("https://github.com/o/r/", "https://github.com/o/r"),
    ("/w/src/.git", "/w/src/"),
    ("../src", "../src"),
])
def test_a_url_is_displayed_without_credentials_or_git_suffix(url, expected):
    assert display_url(url) == expected


def test_extra_headers_split_name_and_value_later_ones_winning():
    assert extra_headers([
        b"Authorization: Bearer a", b"X-A:1", b"Authorization: Bearer b",
        b"broken"
    ]) == {
        "Authorization": "Bearer b",
        "X-A": "1"
    }


def _backend(root: Path) -> ThreadingHTTPServer:
    """git's own smart HTTP server, as a CGI behind a local listener.

    Args:
        root (Path): the directory holding the served repositories.
    """

    class Handler(BaseHTTPRequestHandler):

        def _cgi(self) -> None:
            parts = urlsplit(self.path)
            size = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(size)
            env = {
                **ENV, "GIT_PROJECT_ROOT": str(root),
                "GIT_HTTP_EXPORT_ALL": "1",
                "PATH_INFO": parts.path,
                "QUERY_STRING": parts.query,
                "REQUEST_METHOD": self.command,
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(len(body)),
                "REMOTE_ADDR": "127.0.0.1"
            }
            out = subprocess.run(["git", "http-backend"],
                                 input=body,
                                 env=env,
                                 capture_output=True).stdout
            head, _, payload = out.partition(b"\r\n\r\n")
            status, headers = 200, []
            for line in head.decode().split("\r\n"):
                name, _, value = line.partition(":")
                if name.lower() == "status":
                    status = int(value.split()[0])
                elif name:
                    headers.append((name, value.strip()))
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = _cgi

        def log_message(self, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def served(tmp_path) -> Iterator[tuple[Path, str]]:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    work, root = tmp_path / "work", tmp_path / "srv"
    subprocess.run([
        "bash", "-ec", f"git init -q -b main {work} && cd {work} && "
        "echo one > a && git add a && git commit -qm first && "
        "git tag -a -m t v1 && echo two > a && git commit -qam second && "
        f"git clone -q --bare {work} {root}/repo.git"
    ],
                   check=True,
                   capture_output=True,
                   env=ENV)
    server = _backend(root)
    yield work, f"http://127.0.0.1:{server.server_address[1]}/repo.git"
    server.shutdown()


@pytest.mark.asyncio
async def test_clone_and_fetch_over_smart_http(served):
    pytest.importorskip("httpx")
    work, url = served
    with Workspace({"/w/": RAMVFS()}, mode=MountMode.WRITE) as ws:
        ws.register_cli("git", GIT)
        result = await ws.shell(f"cd /w && git clone {url} c")
        assert (result.exit_code, result.stderr) == (0,
                                                     b"Cloning into 'c'...\n")
        result = await ws.shell("cd /w/c && git log --oneline --format=%s")
        assert result.stdout == b"second\nfirst\n"
        result = await ws.shell(
            "cd /w/c && git for-each-ref --format='%(refname)'")
        assert result.stdout == (b"refs/heads/main\nrefs/remotes/origin/HEAD\n"
                                 b"refs/remotes/origin/main\nrefs/tags/v1\n")
        subprocess.run([
            "bash", "-ec", "echo three > a && git commit -qam third && "
            "git tag v2 && git push -q ../srv/repo.git main v2"
        ],
                       cwd=work,
                       check=True,
                       capture_output=True,
                       env=ENV)
        result = await ws.shell("cd /w/c && git fetch")
        lines = (result.stderr or b"").decode().splitlines()
        assert lines[0] == f"From {display_url(url)}"
        assert lines[2] == " * [new tag]         v2         -> v2"
        result = await ws.shell("cd /w/c && git log -1 --format=%s origin/main"
                                )
        assert result.stdout == b"third\n"


@pytest.mark.asyncio
async def test_a_missing_http_repository_is_not_found(served):
    pytest.importorskip("httpx")
    _, url = served
    with Workspace({"/w/": RAMVFS()}, mode=MountMode.WRITE) as ws:
        ws.register_cli("git", GIT)
        result = await ws.shell(f"cd /w && git clone {url}/nope.git m")
        left = await ws.shell("test -e /w/m || echo removed")
    assert result.exit_code == 128
    assert result.stderr == (f"Cloning into 'm'...\nfatal: repository "
                             f"'{url}/nope.git/' not found\n").encode()
    assert left.stdout == b"removed\n"

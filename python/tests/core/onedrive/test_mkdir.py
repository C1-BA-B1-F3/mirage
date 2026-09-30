import pytest
from aioresponses import CallbackResult, aioresponses
from yarl import URL

from mirage.accessor.onedrive import OneDriveAccessor, OneDriveConfig
from mirage.core.onedrive.client import GraphError
from mirage.core.onedrive.mkdir import mkdir
from mirage.types import PathSpec

_BASE = "https://graph.microsoft.com/v1.0/me/drive"


def _accessor(**kw) -> OneDriveAccessor:
    return OneDriveAccessor(OneDriveConfig(access_token="tok", **kw))


@pytest.mark.asyncio
async def test_mkdir_posts_folder_with_fail_behavior():
    body = {}

    def _cb(url, **kwargs):
        body.update(kwargs.get("json") or {})
        return CallbackResult(status=201, payload={"id": "1"})

    with aioresponses() as m:
        m.post(_BASE + "/root:/parent:/children", callback=_cb)
        await mkdir(_accessor(), PathSpec.from_str_path("/parent/new"))
    assert body["name"] == "new"
    assert body["folder"] == {}
    assert body["@microsoft.graph.conflictBehavior"] == "fail"


@pytest.mark.asyncio
async def test_mkdir_tolerates_existing_item():
    with aioresponses() as m:
        m.post(
            _BASE + "/root:/parent:/children",
            status=409,
            payload={"error": {
                "code": "nameAlreadyExists",
                "message": "x"
            }})
        await mkdir(_accessor(), PathSpec.from_str_path("/parent/new"))
        # Tolerating the 409 means returning after the one POST, not
        # retrying it with a different conflict behavior.
        assert len(m.requests[("POST",
                               URL(_BASE + "/root:/parent:/children"))]) == 1


@pytest.mark.asyncio
async def test_mkdir_raises_on_other_errors():
    with aioresponses() as m:
        m.post(
            _BASE + "/root:/parent:/children",
            status=507,
            payload={"error": {
                "code": "insufficientStorage",
                "message": "x"
            }})
        with pytest.raises(GraphError):
            await mkdir(_accessor(), PathSpec.from_str_path("/parent/new"))


@pytest.mark.asyncio
async def test_mkdir_parents_creates_each_level():
    posts: list[str] = []

    def _cb(url, **kwargs):
        posts.append(str(url))
        return CallbackResult(status=201, payload={"id": "1"})

    with aioresponses() as m:
        m.post(_BASE + "/root/children", callback=_cb)
        m.post(_BASE + "/root:/a:/children", callback=_cb)
        await mkdir(_accessor(), PathSpec.from_str_path("/a/b"), parents=True)
    assert posts == [
        _BASE + "/root/children",
        _BASE + "/root:/a:/children",
    ]


_NOT_FOUND = {"error": {"code": "itemNotFound", "message": "x"}}


def _recording(posts: list[str], status: int = 201):

    def _cb(url, **kwargs):
        posts.append(f"{status} {url}")
        payload = {"id": "1"} if status < 400 else _NOT_FOUND
        return CallbackResult(status=status, payload=payload)

    return _cb


@pytest.mark.asyncio
@pytest.mark.parametrize("parents", [False, True])
async def test_mkdir_creates_a_missing_mount_root_then_retries(parents):
    posts: list[str] = []
    with aioresponses() as m:
        m.post(_BASE + "/root:/team/root:/children",
               callback=_recording(posts, 404))
        m.post(_BASE + "/root/children", callback=_recording(posts))
        m.post(_BASE + "/root:/team:/children", callback=_recording(posts))
        m.post(_BASE + "/root:/team/root:/children",
               callback=_recording(posts))
        await mkdir(_accessor(key_prefix="team/root"),
                    PathSpec.from_str_path("/lt"),
                    parents=parents)
    assert posts == [
        "404 " + _BASE + "/root:/team/root:/children",
        "201 " + _BASE + "/root/children",
        "201 " + _BASE + "/root:/team:/children",
        "201 " + _BASE + "/root:/team/root:/children",
    ]


@pytest.mark.asyncio
async def test_mkdir_does_not_retry_a_404_below_the_mount_root():
    posts: list[str] = []
    with aioresponses() as m:
        m.post(_BASE + "/root:/team/root/a:/children",
               callback=_recording(posts, 404))
        with pytest.raises(GraphError):
            await mkdir(_accessor(key_prefix="team/root"),
                        PathSpec.from_str_path("/a/b"))
    assert posts == ["404 " + _BASE + "/root:/team/root/a:/children"]


@pytest.mark.asyncio
async def test_mkdir_does_not_retry_a_404_without_a_key_prefix():
    posts: list[str] = []
    with aioresponses() as m:
        m.post(_BASE + "/root/children", callback=_recording(posts, 404))
        with pytest.raises(GraphError):
            await mkdir(_accessor(), PathSpec.from_str_path("/new"))
    assert posts == ["404 " + _BASE + "/root/children"]

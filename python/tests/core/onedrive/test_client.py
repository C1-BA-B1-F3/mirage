import pytest
from pydantic import ValidationError

from mirage.accessor.onedrive import OneDriveConfig
from mirage.core.onedrive.client import drive_base, drive_ref_path, item_url


def _cfg(**kw) -> OneDriveConfig:
    return OneDriveConfig(access_token="tok", **kw)


def test_drive_base_defaults_to_me_drive():
    assert drive_base(_cfg()) == "https://graph.microsoft.com/v1.0/me/drive"


def test_drive_base_uses_drive_id():
    base = drive_base(_cfg(drive_id="b!abc"))
    assert base == "https://graph.microsoft.com/v1.0/drives/b!abc"


def test_drive_base_uses_site_default_drive():
    base = drive_base(_cfg(site_id="site123"))
    assert base == "https://graph.microsoft.com/v1.0/sites/site123/drive"


def test_drive_base_uses_group_drive():
    base = drive_base(_cfg(group_id="grp123"))
    assert base == "https://graph.microsoft.com/v1.0/groups/grp123/drive"


def test_drive_base_uses_user_drive():
    base = drive_base(_cfg(user_id="usr@example.com"))
    assert base == (
        "https://graph.microsoft.com/v1.0/users/usr%40example.com/drive"
    )


def test_drive_base_escapes_a_guest_upn():
    # A guest's UPN carries `#EXT#`. Interpolated raw, that `#` opens a
    # URL fragment, so Graph receives `/users/guest_contoso.com` and
    # answers 404 for a user that exists.
    base = drive_base(_cfg(user_id="guest_contoso.com#EXT#@fabrikam.com"))
    assert base == (
        "https://graph.microsoft.com/v1.0/users/"
        "guest_contoso.com%23EXT%23%40fabrikam.com/drive"
    )


def test_drive_base_leaves_a_drive_id_bang_alone():
    # `quote` would escape `!`, `encodeURIComponent` does not, and drive
    # ids start `b!`. The ref path built off this base goes into a JSON
    # body Graph reads literally, so the two languages must agree.
    assert "b!" in drive_base(_cfg(drive_id="b!abc-_x"))


def test_graph_base_url_replaces_the_service_root():
    # How a mount reaches a sovereign cloud, a private endpoint, or a
    # test server. The trailing slash must not survive into the URL.
    cfg = _cfg(graph_base_url="http://127.0.0.1:8080/v1.0/")
    assert drive_base(cfg) == "http://127.0.0.1:8080/v1.0/me/drive"


def test_drive_ref_path_survives_a_custom_base():
    # ref paths are Graph-root-relative, so they must be the base stripped
    # off, never a hardcoded host stripped off.
    cfg = _cfg(drive_id="b!abc", graph_base_url="http://127.0.0.1:8080/v1.0")
    assert drive_ref_path(cfg, "sub/dir") == "/drives/b!abc/root:/sub/dir"


def test_config_rejects_two_drive_targets():
    # A fixed precedence would silently address one and ignore the other.
    with pytest.raises(ValidationError, match="names 2 drives"):
        _cfg(drive_id="b!abc", site_id="site123")


def test_item_url_root_children():
    url = item_url(_cfg(), "/", action="/children")
    assert url == "https://graph.microsoft.com/v1.0/me/drive/root/children"


def test_item_url_nested_metadata_no_action():
    url = item_url(_cfg(), "/Docs/report.docx")
    assert url == (
        "https://graph.microsoft.com/v1.0/me/drive/root:/Docs/report.docx"
    )


def test_item_url_nested_content():
    url = item_url(_cfg(), "/Docs/report.docx", action="/content")
    assert url == (
        "https://graph.microsoft.com/v1.0/me/drive"
        "/root:/Docs/report.docx:/content"
    )


def test_item_url_nested_children():
    url = item_url(_cfg(), "/Docs", action="/children")
    assert url == (
        "https://graph.microsoft.com/v1.0/me/drive/root:/Docs:/children"
    )


def test_item_url_applies_key_prefix():
    url = item_url(_cfg(key_prefix="team/files"), "/a.txt", action="/content")
    assert url == (
        "https://graph.microsoft.com/v1.0/me/drive"
        "/root:/team/files/a.txt:/content"
    )


def test_item_url_quotes_spaces():
    url = item_url(_cfg(), "/My Folder/a b.txt")
    assert url == (
        "https://graph.microsoft.com/v1.0/me/drive/root:/My%20Folder/a%20b.txt"
    )


def test_item_url_escapes_each_segment_like_encode_uri_component():
    url = item_url(_cfg(), "/a(1)/b!*'.txt")
    assert url == (
        "https://graph.microsoft.com/v1.0/me/drive/root:/a(1)/b!*'.txt"
    )

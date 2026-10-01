from mirage.accessor.sharepoint import SharePointConfig
from mirage.core.sharepoint.client import drive_ref_path, item_url


def _cfg(**kw) -> SharePointConfig:
    return SharePointConfig(access_token="tok", **kw)


_BASE = "https://graph.microsoft.com/v1.0"
_DRIVE = "b!drive123"


def test_item_url_root_no_path():
    url = item_url(_cfg(), _DRIVE, "/")
    assert url == f"{_BASE}/drives/{_DRIVE}/root"


def test_item_url_root_children():
    url = item_url(_cfg(), _DRIVE, "/", action="/children")
    assert url == f"{_BASE}/drives/{_DRIVE}/root/children"


def test_item_url_nested_file():
    url = item_url(_cfg(), _DRIVE, "/docs/report.docx")
    assert url == f"{_BASE}/drives/{_DRIVE}/root:/docs/report.docx"


def test_item_url_nested_content():
    url = item_url(_cfg(), _DRIVE, "/docs/report.docx", action="/content")
    assert url == f"{_BASE}/drives/{_DRIVE}/root:/docs/report.docx:/content"


def test_item_url_nested_children():
    url = item_url(_cfg(), _DRIVE, "/folder", action="/children")
    assert url == f"{_BASE}/drives/{_DRIVE}/root:/folder:/children"


def test_item_url_quotes_spaces():
    url = item_url(_cfg(), _DRIVE, "/My Folder/a b.txt")
    assert url == f"{_BASE}/drives/{_DRIVE}/root:/My%20Folder/a%20b.txt"


def test_drive_ref_path_root():
    assert drive_ref_path(_DRIVE) == f"/drives/{_DRIVE}/root:"


def test_drive_ref_path_folder():
    p = drive_ref_path(_DRIVE, "sub/dir")
    assert p == f"/drives/{_DRIVE}/root:/sub/dir"

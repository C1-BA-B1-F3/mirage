from opendal.exceptions import NotFound

from mirage.accessor.nextcloud import NextcloudAccessor
from mirage.cache.context import invalidate_subtree
from mirage.types import PathSpec
from mirage.utils.errors import enoent


async def rm_r(accessor: NextcloudAccessor, path: PathSpec) -> None:
    raw = path.mount_path
    key = raw.strip("/") + "/"
    op = accessor.operator()
    try:
        await op.remove_all(key)
    except NotFound as exc:
        raise enoent(path) from exc
    await invalidate_subtree(path)

from opendal.exceptions import NotFound

from mirage.accessor.nextcloud import NextcloudAccessor
from mirage.cache.context import invalidate_after_write
from mirage.core.nextcloud.util import nextcloud_key
from mirage.types import PathSpec
from mirage.utils.errors import enoent


async def copy(
    accessor: NextcloudAccessor, src: PathSpec, dst: PathSpec
) -> None:
    src_key = nextcloud_key(src)
    dst_key = nextcloud_key(dst)
    op = accessor.operator()
    try:
        await op.copy(src_key, dst_key)
    except NotFound as exc:
        raise enoent(src) from exc
    await invalidate_after_write(dst)

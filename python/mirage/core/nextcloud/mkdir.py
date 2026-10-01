from mirage.accessor.nextcloud import NextcloudAccessor
from mirage.cache.context import invalidate_after_write, invalidate_ancestors
from mirage.types import PathSpec


async def mkdir(
    accessor: NextcloudAccessor, path: PathSpec, parents: bool = False
) -> None:
    """Create a collection; opendal creates missing parents either way.

    ``parents`` is accepted for the op signature and ignored, because
    ``create_dir`` is MKCOL over every missing level whatever it says.
    That is also why the ancestor invalidation is unconditional: a bare
    ``mkdir a/b/c`` materializes a whole chain here, and gating the walk
    on ``parents`` (as the backends whose mkdir really does create one
    level correctly do) left every ancestor above the parent serving a
    cached listing that hid the new levels until the index TTL expired.

    Args:
        accessor (NextcloudAccessor): Nextcloud accessor.
        path (PathSpec): collection to create.
        parents (bool): ignored; opendal always creates parents.
    """
    key = path.mount_path.strip("/") + "/"
    op = accessor.operator()
    await op.create_dir(key)
    await invalidate_after_write(path)
    await invalidate_ancestors(path)

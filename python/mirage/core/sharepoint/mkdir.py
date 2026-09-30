import posixpath

from mirage.accessor.sharepoint import SharePointAccessor
from mirage.cache.context import invalidate_after_write, invalidate_ancestors
from mirage.core.msgraph.drive_ops import create_child_folder
from mirage.core.sharepoint.client import GraphError, item_url, split_path
from mirage.core.sharepoint.resolve import resolve
from mirage.types import PathSpec
from mirage.utils.errors import enoent


async def _create_dir(accessor: SharePointAccessor, drive_id: str,
                      stripped: str) -> None:
    parent = posixpath.dirname("/" + stripped).strip("/")
    url = item_url(accessor.config,
                   drive_id,
                   "/" + parent if parent else "/",
                   action="/children")
    await create_child_folder(accessor.config,
                              url,
                              posixpath.basename(stripped),
                              session=accessor.pool)


async def _create_chain(accessor: SharePointAccessor, drive_id: str,
                        item_p: str) -> None:
    """Create every level of a drive path, from the drive root down.

    Args:
        accessor (SharePointAccessor): the mount's accessor.
        drive_id (str): the drive the path lives in.
        item_p (str): the drive-relative path, key_prefix included.
    """
    parts = item_p.split("/")
    for i in range(len(parts)):
        await _create_dir(accessor, drive_id, "/".join(parts[:i + 1]))


def _scoped_prefix(accessor: SharePointAccessor) -> str:
    """The key_prefix a scoped mount's root folder chain lives at.

    Only a mount scoped to one site and drive places its paths under the
    prefix, so only there is the mount root a folder chain that a folder
    create can find missing. With parents the chain is already walked;
    without, a create right under the root has to make it first.

    Args:
        accessor (SharePointAccessor): the mount's accessor.
    """
    config = accessor.config
    if config.site is None or config.drive is None:
        return ""
    return (config.key_prefix or "").strip("/")


async def mkdir(accessor: SharePointAccessor,
                path: PathSpec,
                parents: bool = False) -> None:
    virtual = path.virtual if isinstance(path, PathSpec) else path
    _, stripped = split_path(path)
    if not stripped:
        return
    resolved = await resolve(accessor, path)
    if resolved.drive_id is None or resolved.item_path is None:
        raise enoent(virtual)
    drive_id = resolved.drive_id
    item_p = resolved.item_path
    if parents:
        await _create_chain(accessor, drive_id, item_p)
    else:
        try:
            await _create_dir(accessor, drive_id, item_p)
        except GraphError as exc:
            prefix = _scoped_prefix(accessor)
            if exc.status != 404 or not prefix or posixpath.dirname(
                    item_p) != prefix:
                raise
            await _create_chain(accessor, drive_id, item_p)
    await invalidate_after_write(path)
    if parents:
        await invalidate_ancestors(path)

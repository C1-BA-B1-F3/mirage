import re
from dataclasses import dataclass

from mirage.commands.cli.builtin.git.io import read_optional
from mirage.commands.cli.builtin.git.types import RepoLocation
from mirage.commands.spec.flag_view import FlagView
from mirage.runtime.types import DispatchFn


@dataclass(frozen=True, slots=True)
class MailmapEntry:
    email: str
    name: str | None
    mapped_name: str | None
    mapped_email: str | None


def parse_mailmap(text: str) -> tuple[MailmapEntry, ...]:
    """Read Git's four mailmap identity forms.

    Args:
        text (str): worktree mailmap contents.
    """
    entries = []
    for line in text.splitlines():
        if line.lstrip().startswith('#'):
            continue
        match = re.match(
            r"^\s*([^<>]*?)\s*<([^<>]+)>(?:\s*([^<>]*?)\s*<([^<>]+)>)?", line)
        if match is None:
            continue
        name, email, old_name, old_email = match.groups()
        entries.append(
            MailmapEntry((old_email or email).lower(),
                         old_name.strip().lower()
                         if old_name and old_name.strip() else None,
                         name.strip() or None, email if old_email else None))
    return tuple(entries)


def mapped_identity(identity: str, entries: tuple[MailmapEntry, ...]) -> str:
    """Apply email-wide mappings, then more specific name-and-email mappings.

    Args:
        identity (str): recorded name and email.
        entries (tuple[MailmapEntry, ...]): mailmap entries in file order.
    """
    match = re.match(r"(.*?)\s*<([^<>]*)>", identity)
    if match is None:
        return identity
    name, email = match.groups()
    chosen_name, chosen_email = name, email
    for specific in (False, True):
        for entry in entries:
            if (entry.name
                    is not None) != specific or entry.email != email.lower():
                continue
            if entry.name is not None and entry.name != name.lower():
                continue
            chosen_name = entry.mapped_name or chosen_name
            chosen_email = entry.mapped_email or chosen_email
    return f"{chosen_name} <{chosen_email}>"


async def load_mailmap(dispatch: DispatchFn,
                       location: RepoLocation) -> tuple[MailmapEntry, ...]:
    """Read the worktree mailmap through the workspace data plane.

    Args:
        dispatch (DispatchFn): op dispatcher.
        location (RepoLocation): discovered repository.
    """
    data = await read_optional(dispatch, f"{location.worktree}/.mailmap")
    return parse_mailmap((data or b"").decode('utf-8', 'replace'))


def use_mailmap(fl: FlagView, enabled: bool) -> bool:
    """Apply explicit mailmap switches in command-line order.

    Args:
        fl (FlagView): spec-bound options.
        enabled (bool): configured default.
    """
    for key, _ in fl.occurrences('mailmap', 'use_mailmap', 'no_mailmap',
                                 'no_use_mailmap'):
        enabled = not key.startswith('no_')
    return enabled

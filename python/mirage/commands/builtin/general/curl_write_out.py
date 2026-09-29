import re
from collections.abc import Mapping

TOKEN = re.compile(r"%\{([^}]*)\}|%%|\\([nrt\\])")
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\"}


def render_write_out(template: str,
                     values: Mapping[str, str]) -> tuple[bytes, bytes]:
    """Render curl's format language using observable transfer facts.

    Transport-private measurements are unavailable in both hosts and are
    reported as unknown variables, never fabricated. Unknown variables
    diagnose on stderr without changing the transfer's exit status.

    Args:
        template (str): literal or file-loaded write-out template.
        values (Mapping[str, str]): facts collected for this transfer.
    """
    streams: list[list[str]] = [[], []]
    stream = 0
    cursor = 0
    for match in TOKEN.finditer(template):
        streams[stream].append(template[cursor:match.start()])
        name = match.group(1)
        if name in ("stdout", "stderr"):
            stream = int(name == "stderr")
        elif name == "onerror":
            if values["exitcode"] == "0":
                return "".join(streams[0]).encode(), "".join(
                    streams[1]).encode()
        elif name is not None:
            if name in values:
                streams[stream].append(values[name])
            else:
                streams[1].append(
                    f"curl: unknown --write-out variable: '{name}'\n")
        elif match.group(2) is not None:
            streams[stream].append(ESCAPES[match.group(2)])
        else:
            streams[stream].append("%")
        cursor = match.end()
    streams[stream].append(template[cursor:])
    return "".join(streams[0]).encode(), "".join(streams[1]).encode()

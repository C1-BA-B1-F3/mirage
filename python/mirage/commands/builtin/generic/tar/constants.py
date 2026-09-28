from mirage.commands.builtin.generic.tar.types import (CompressionSuffix,
                                                       ReadMode, WriteMode)

WRITE_MODES: dict[CompressionSuffix, WriteMode] = {
    "": "w",
    ":gz": "w:gz",
    ":bz2": "w:bz2",
    ":xz": "w:xz",
}
READ_MODES: dict[CompressionSuffix, ReadMode] = {
    "": "r",
    ":gz": "r:gz",
    ":bz2": "r:bz2",
    ":xz": "r:xz",
}

# Every diagnostic below is GNU tar 1.35's own wording, pinned on
# debian:stable-slim; only the hint line is mirage's, for the reason
# usage.old_option_error gives (mirage's tar serves no --usage).
USAGE_HINT = "Try 'tar --help' for more information."
EMPTY_ARCHIVE = "tar: Cowardly refusing to create an empty archive"
# GNU normalizes an empty operand to `.` before it stats it, says so, and
# then still names the operand as typed when the stat fails (tar 1.35).
EMPTY_MEMBER = "tar: Substituting `.' for empty member name"
FATAL_TRAILER = "tar: Error is not recoverable: exiting now"
# What GNU adds when the archive opened but its first read failed (a
# directory given to -f).
TAPE_START = "tar: At beginning of tape, quitting now"
# What tar adds when its gzip -d child fails, after gzip's own lines.
CHILD_STATUS = "tar: Child returned status {}"
# With a compressor, the archive is opened by tar's child, which names
# itself so on every line it prints (tar 1.35).
CHILD_NAME = "tar (child)"
# What the compressor the child already spawned says when the child dies
# before feeding it, which happens for every open failure but a missing
# name (gzip 1.13, xz 5.4). bzip2's complaint is a paragraph of recovery
# advice that mirage does not reproduce.
EMPTY_PIPE = {
    ":gz": ("", "gzip: stdin: unexpected end of file"),
    ":xz": ("xz: (stdin): File format not recognized", ),
}
INVALID_ARCHIVE = ("tar: This does not look like a tar archive",
                   "tar: Skipping to next header")
ERROR_TRAILER = "tar: Exiting with failure status due to previous errors"
SELF_DUMP = "archive cannot contain itself; not dumped"
# The exit GNU gives an operand it could not read, and a -C it could not
# enter. Both are fatal for the whole run, not per-operand.
CREATE_ERROR_EXIT = 2

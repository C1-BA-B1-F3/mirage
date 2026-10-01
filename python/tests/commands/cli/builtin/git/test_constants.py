import stat

from dulwich.refs import Ref

from mirage.commands.cli.builtin.git.constants import (
    EXECUTABLE,
    GIT_DIR,
    HEAD,
    HEAD_REF,
    OWNER_EXECUTE,
    REGULAR,
    SYMLINK,
)


def test_tree_modes_are_gits_own():
    assert stat.S_ISREG(REGULAR)
    assert stat.S_ISREG(EXECUTABLE)
    assert stat.S_ISLNK(SYMLINK)
    assert EXECUTABLE == REGULAR | 0o111
    assert OWNER_EXECUTE == stat.S_IXUSR


def test_head_spellings_agree():
    assert HEAD_REF == Ref(b"HEAD")
    assert HEAD_REF.decode() == HEAD
    assert GIT_DIR == ".git"

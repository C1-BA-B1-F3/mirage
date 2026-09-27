# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

from mirage.commands.cli.builtin.git.add import add
from mirage.commands.cli.builtin.git.branch import branch
from mirage.commands.cli.builtin.git.checkout import checkout
from mirage.commands.cli.builtin.git.commit import commit
from mirage.commands.cli.builtin.git.diff import diff
from mirage.commands.cli.builtin.git.inspect import (config, remote, rev_list,
                                                     rev_parse, show_ref,
                                                     version)
from mirage.commands.cli.builtin.git.log import log
from mirage.commands.cli.builtin.git.mv import mv
from mirage.commands.cli.builtin.git.reset import reset
from mirage.commands.cli.builtin.git.restore import restore
from mirage.commands.cli.builtin.git.rm import rm
from mirage.commands.cli.builtin.git.shortlog import shortlog
from mirage.commands.cli.builtin.git.show import diff_tree, show
from mirage.commands.cli.builtin.git.status import status
from mirage.commands.cli.builtin.git.switch import switch
from mirage.commands.cli.builtin.git.tag import tag
from mirage.commands.cli.types import CLISpec, UsageStyle
from mirage.commands.spec.types import Operand, Option

# `-C` is git's own before-anything-else option, so it sits on the root
# and every verb inherits it. The "." default is load-bearing: a PATH
# default lands as if typed, so an absent -C resolves to the session cwd
# and the leaves need no separate working-directory fact.
DIRECTORY_OPTION = Option(short="-C",
                          type="path",
                          default=".",
                          description="Run as if git was started in <path>")

REVISION = Operand(type="str")

# --pretty and --format set the same variable in git; both take git's
# optional-value form, so a bare --pretty means medium and a detached
# next word is a revision, never a format. A bare --format stays
# parseable too, but only so pretty_value can answer it with git's own
# fatal (pretty.c reads --format in its =value form alone).
PRETTY_OPTION = Option(long="--pretty",
                       type="str",
                       value_optional=True,
                       description="Commit display format: oneline, short, "
                       "medium, full, fuller, or a format:/tformat:/%-string")
FORMAT_OPTION = Option(long="--format",
                       type="str",
                       value_optional=True,
                       description="Alias of --pretty (requires =value)")

DATE_OPTION = Option(long="--date",
                     type="str",
                     choices=('default', 'iso', 'iso8601', 'iso-strict',
                              'iso8601-strict', 'short', 'unix', 'raw'),
                     description="Date display format")

DIFF_OPTIONS = (
    Option(short="-U",
           long="--unified",
           type="int",
           description="Number of context lines"),
    Option(long="--name-status", description="Show changed paths and status"),
    Option(long="--name-only",
           description="Show changed paths instead of the patch"),
    Option(long="--stat",
           description="Show the diffstat table instead of the patch"),
    Option(long="--numstat",
           description="Show added and deleted line counts per path"),
    Option(long="--shortstat",
           description="Show only the diffstat summary line"),
    Option(long="--summary",
           description="Summarize creations, deletions and mode changes"),
    Option(short="-p", long="--patch", description="Show the patch"),
    Option(short="-s",
           long="--no-patch",
           description="Suppress all diff output"),
    Option(long="--no-ext-diff",
           description="Accepted for compatibility; there are no external "
           "diff drivers to disable"),
    Option(short="-M",
           long="--find-renames",
           type="str",
           value_optional=True,
           description="Detect renames with an optional similarity threshold"),
    Option(long="--no-renames", description="Turn off rename detection"),
    Option(long="--raw", description="Show the raw diff format"),
)

MERGE_OPTIONS = (
    Option(short="-m",
           description="Show merge diffs separately against each parent"),
    Option(short="-c", description="Show combined merge diffs"),
    Option(long="--cc", description="Show dense combined merge diffs"),
    Option(long="--first-parent",
           description="Follow and compare only the first parent"),
    Option(long="--diff-merges",
           type="str",
           description="Select merge diff mode"),
)

LOG_OPTIONS = (
    Option(long="--author",
           type="str",
           multiple=True,
           description="Limit commits to matching authors"),
    *MERGE_OPTIONS,
    Option(long="--after",
           type="str",
           description="Commits more recent than a date, like --since"),
    Option(long="--before",
           type="str",
           description="Commits older than a date, like --until"),
    Option(long="--max-parents",
           type="int",
           description="Show only commits with at most this many parents"),
    Option(long="--min-parents",
           type="int",
           description="Show only commits with at least this many parents"),
    Option(long="--merges", description="Show only merge commits"),
    Option(long="--no-merges", description="Leave out merge commits"),
    DATE_OPTION,
    Option(long="--decorate", description="Print ref names on commits"),
    Option(short="-n",
           type="int",
           numeric_shorthand=True,
           description="Limit the number of commits shown"),
    Option(long="--oneline", description="One abbreviated line per commit"),
    Option(long="--reverse", description="Print commits oldest first"),
    Option(long="--graph",
           description="Draw the commit history beside the log "
           "(implies --topo-order)"),
    Option(long="--topo-order",
           description="Show no parent before all its children, one line "
           "of history at a time"),
    Option(long="--date-order",
           description="Show no parent before all its children, otherwise "
           "newest first"),
    Option(long="--all",
           description="Start from every ref as well as the revision"),
    PRETTY_OPTION,
    FORMAT_OPTION,
    # The pickaxe, and the reason `git log -S <name> --reverse` answers
    # "which commit introduced this": it selects commits that changed
    # how many times the string occurs, not commits that mention it.
    Option(short="-S",
           type="str",
           description="Show commits that change the number of occurrences "
           "of the string"),
    Option(long="--since",
           type="str",
           description="Commits more recent than a date (ISO-8601 or epoch)"),
    Option(long="--until",
           type="str",
           description="Commits older than a date (ISO-8601 or epoch)"),
)

SHOW_OPTIONS = (Option(long="--oneline",
                       description="One abbreviated line per commit"),
                *DIFF_OPTIONS, *MERGE_OPTIONS, DATE_OPTION, PRETTY_OPTION,
                FORMAT_OPTION)

# git's ref-filter options, which `branch` and `tag` share. The four
# commit filters take the next word as their commit, whatever it looks
# like (`--merged --no-merged` names a commit called `--no-merged`),
# except as the line's last word, where they read HEAD: parse-options'
# LASTARG_DEFAULT. The spec has no word for that, so they are declared
# with an optional value (a bare one is HEAD, `--merged=main` is main)
# and `filter_words` reattaches a detached value from the verbatim argv.
# `--points-at` always takes a value.
REF_FILTER_OPTIONS = (
    Option(long="--contains",
           type="str",
           value_optional=True,
           multiple=True,
           metavar="commit",
           description="List only refs that contain the commit (HEAD if "
           "omitted)"),
    Option(long="--no-contains",
           type="str",
           value_optional=True,
           multiple=True,
           metavar="commit",
           description="List only refs that don't contain the commit "
           "(HEAD if omitted)"),
    Option(long="--merged",
           type="str",
           value_optional=True,
           multiple=True,
           metavar="commit",
           description="List only refs reachable from the commit (HEAD if "
           "omitted)"),
    Option(long="--no-merged",
           type="str",
           value_optional=True,
           multiple=True,
           metavar="commit",
           description="List only refs not reachable from the commit (HEAD "
           "if omitted)"),
    Option(long="--points-at",
           type="str",
           multiple=True,
           metavar="object",
           description="List only refs that point at the object"),
)

BRANCH_OPTIONS = (
    Option(long="--show-current", description="Show the current branch name"),
    Option(short="-v",
           long="--verbose",
           count=True,
           description="Show commit and upstream details"),
    Option(short="-a", description="List local and remote-tracking branches"),
    Option(short="-r", description="List remote-tracking branches"),
    Option(short="-d",
           long="--delete",
           description="Delete a fully merged branch"),
    Option(short="-D", description="Delete a branch even if not merged"),
    Option(short="-l",
           long="--list",
           description="List branches matching the patterns"),
    *REF_FILTER_OPTIONS,
)

PATHSPEC = Operand(type="str")

ADD_OPTIONS = (
    Option(short="-A", long="--all", description="Stage every change"),
    Option(short="-u",
           long="--update",
           description="Stage changes to tracked files only"),
    Option(short="-f",
           long="--force",
           description="Stage paths an ignore rule covers"),
    Option(short="-v",
           long="--verbose",
           description="Name each path as it is added or removed"),
)

COMMIT_OPTIONS = (
    Option(short="-a",
           long="--all",
           description="Stage modified and deleted tracked files first"),
    # Required, not defaulted: git would open an editor without it, and
    # a mount has none to open.
    Option(short="-m",
           long="--message",
           type="str",
           description="Commit message"),
    Option(long="--author",
           type="str",
           description="Override the recorded author"),
)

CHECKOUT_OPTIONS = (Option(short="-b",
                           description="Create the branch and switch to it"), )

SWITCH_OPTIONS = (
    Option(short="-c",
           long="--create",
           type="str",
           description="Create the branch and switch to it"),
    Option(short="-d",
           long="--detach",
           description="Detach HEAD at the named commit"),
)

RESTORE_OPTIONS = (
    Option(short="-S", long="--staged", description="Restore the index"),
    Option(short="-W",
           long="--worktree",
           description="Restore the working tree (default)"),
    Option(short="-s",
           long="--source",
           type="str",
           description="Which tree-ish to restore from"),
)

RM_OPTIONS = (
    Option(short="-r", description="Allow recursive removal"),
    Option(long="--cached",
           description="Only remove from the index, keeping the file"),
    Option(short="-f",
           long="--force",
           description="Override the up-to-date check"),
    Option(short="-q", long="--quiet",
           description="Do not list removed files"),
    Option(long="--ignore-unmatch",
           description="Exit with a zero status even if nothing matched"),
)

MV_OPTIONS = (
    Option(short="-f",
           long="--force",
           description="Force move/rename even if target exists"),
    Option(short="-k", description="Skip move/rename errors"),
    Option(short="-n", long="--dry-run", description="Dry run"),
    Option(short="-v", long="--verbose", description="Be verbose"),
)

TAG_OPTIONS = (
    Option(short="-l", long="--list", description="List tag names"),
    # git spells the count attached (`-n2`) or not at all, never as a
    # separate token, which is what value_optional says: a bare -n means
    # one line and the next word is left alone to be a pattern.
    Option(short="-n",
           type="int",
           value_optional=True,
           description="Print <n> lines of each tag message"),
    Option(short="-d", long="--delete", description="Delete tags"),
    Option(short="-a",
           long="--annotate",
           description="Annotated tag, needs a message"),
    Option(short="-m",
           long="--message",
           type="str",
           multiple=True,
           description="Tag message (repeatable, one paragraph each)"),
    Option(short="-f", long="--force",
           description="Replace the tag if exists"),
    *REF_FILTER_OPTIONS,
)

STATUS_OPTIONS = (
    Option(long="--porcelain",
           type="str",
           value_optional=True,
           description="Machine-readable output, stable across versions"),
    Option(short="-s",
           long="--short",
           description="Give the output in the "
           "short format"),
    Option(short="-b",
           long="--branch",
           description="Show the branch line even in short format"),
    # git spells the mode attached (`-uall`) or not at all, never as a
    # separate token, which is what value_optional says: a bare -u means
    # "all" and the next word is left alone to be an operand.
    Option(short="-u",
           long="--untracked-files",
           type="str",
           value_optional=True,
           choices=("no", "normal", "all"),
           description="Show untracked files: no, normal or all"),
)

# The git program tree. No config_model: local git needs no credentials,
# which is what makes it installable with a bare `cli: git`.
GIT = CLISpec(
    name="git",
    description="Content tracker",
    usage_style=UsageStyle.GIT,
    options=(DIRECTORY_OPTION, ),
    subcommands=(
        CLISpec(name="version",
                aliases=("--version", "-v"),
                fn=version,
                description="Show the Mirage Git implementation version"),
        CLISpec(name="remote",
                description="List remotes",
                fn=remote,
                options=(Option(short="-v",
                                long="--verbose",
                                description="Show remote URLs"), )),
        CLISpec(name="config",
                description="Read repository configuration",
                fn=config,
                options=(Option(long="--get",
                                description="Get a configuration value"),
                         Option(short="-l",
                                long="--list",
                                description="List every variable and value"),
                         Option(long="--show-origin",
                                description="Show the file each value comes "
                                "from"),
                         Option(long="--get-regexp",
                                description="Get the variables whose names "
                                "match a regular expression")),
                positional=(Operand(type="str", name="name"), )),
        CLISpec(name="show-ref",
                description="List references",
                fn=show_ref,
                rest=REVISION),
        CLISpec(name="shortlog",
                fn=shortlog,
                description="Summarize commit history",
                options=(*(opt for opt in LOG_OPTIONS if opt.short != "-n"),
                         Option(short="-s",
                                long="--summary",
                                description="Show only commit counts"),
                         Option(short="-e",
                                long="--email",
                                description="Show author email addresses"),
                         Option(short="-n",
                                long="--numbered",
                                description="Sort by commit count")),
                rest=REVISION),
        CLISpec(name="rev-parse",
                fn=rev_parse,
                description="Resolve revisions",
                options=(Option(
                    long="--abbrev-ref",
                    description="Show abbreviated reference names"), ),
                rest=REVISION),
        CLISpec(name="rev-list",
                description="List reachable commits",
                fn=rev_list,
                options=(*LOG_OPTIONS,
                         Option(long="--count",
                                description="Print commit count")),
                rest=REVISION),
        CLISpec(name="diff-tree",
                description="Compare a commit with its parent",
                fn=diff_tree,
                options=(*SHOW_OPTIONS,
                         Option(long="--no-commit-id",
                                description="Suppress commit ID"),
                         Option(short="-r",
                                description="Recurse into subtrees")),
                positional=(Operand(type="str", name="commit",
                                    required=True), )),
        CLISpec(
            name="status",
            description="Show the working tree status",
            fn=status,
            options=STATUS_OPTIONS,
        ),
        CLISpec(
            name="log",
            description="Show commit logs",
            fn=log,
            options=(*LOG_OPTIONS, *DIFF_OPTIONS),
            rest=REVISION,
        ),
        CLISpec(
            name="show",
            description="Show a commit and its diff",
            fn=show,
            options=SHOW_OPTIONS,
            rest=REVISION,
        ),
        CLISpec(
            name="diff",
            description="Show changes between commits",
            fn=diff,
            options=(*DIFF_OPTIONS,
                     Option(long="--cached",
                            description="Compare the index with a commit"),
                     Option(long="--staged", description="Alias of --cached")),
            rest=REVISION,
        ),
        CLISpec(
            name="branch",
            description="List, create or delete branches",
            fn=branch,
            options=BRANCH_OPTIONS,
            rest=Operand(type="str"),
            write=True,
        ),
        CLISpec(
            name="add",
            description="Stage working tree content",
            fn=add,
            options=ADD_OPTIONS,
            rest=PATHSPEC,
            write=True,
        ),
        CLISpec(
            name="reset",
            description="Unstage, putting the index back to HEAD",
            fn=reset,
            options=(Option(short="-q",
                            long="--quiet",
                            description="Only report errors"), ),
            rest=PATHSPEC,
            write=True,
        ),
        CLISpec(
            name="commit",
            description="Record the index as a new commit",
            fn=commit,
            options=COMMIT_OPTIONS,
            write=True,
        ),
        CLISpec(
            name="checkout",
            description="Switch branches",
            fn=checkout,
            options=CHECKOUT_OPTIONS,
            rest=REVISION,
            write=True,
        ),
        CLISpec(
            name="switch",
            description="Switch branches",
            fn=switch,
            options=SWITCH_OPTIONS,
            rest=REVISION,
            write=True,
        ),
        CLISpec(
            name="restore",
            description="Restore working tree files",
            fn=restore,
            options=RESTORE_OPTIONS,
            rest=PATHSPEC,
            write=True,
        ),
        CLISpec(
            name="rm",
            description="Remove files from the working tree and the index",
            fn=rm,
            options=RM_OPTIONS,
            rest=PATHSPEC,
            write=True,
        ),
        CLISpec(
            name="mv",
            description="Move or rename a file, a directory, or a symlink",
            fn=mv,
            options=MV_OPTIONS,
            rest=PATHSPEC,
            write=True,
        ),
        CLISpec(
            name="tag",
            description="Create, list or delete a tag",
            fn=tag,
            options=TAG_OPTIONS,
            rest=Operand(type="str"),
            write=True,
        ),
    ),
)

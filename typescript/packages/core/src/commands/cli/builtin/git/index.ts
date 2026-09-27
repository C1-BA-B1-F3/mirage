// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import { Operand, Option } from '../../../spec/types.ts'
import { CLISpec } from '../../types.ts'
import { UsageStyle } from '../../../spec/types.ts'
import { add } from './add.ts'
import { branch } from './branch.ts'
import { checkout } from './checkout.ts'
import { commit } from './commit.ts'
import { diff } from './diff.ts'
import { log } from './log.ts'
import { mv } from './mv.ts'
import { reset } from './reset.ts'
import { restore } from './restore.ts'
import { rm } from './rm.ts'
import { revParse } from './inspect.ts'
import { shortlog } from './shortlog.ts'
import { config, remote, revList, version, showRef } from './inspect.ts'
import { show, diffTree } from './show.ts'
import { status } from './status.ts'
import { switchBranch } from './switch.ts'
import { tag } from './tag.ts'

// `-C` is git's own before-anything-else option, so it sits on the root and
// every verb inherits it. The "." default is load-bearing: a PATH default lands
// as if typed, so an absent -C resolves to the session cwd and the leaves need
// no separate working-directory fact.
const DIRECTORY_OPTION = new Option({
  short: '-C',
  type: 'path',
  default: '.',
  description: 'Run as if git was started in <path>',
})

const REVISION = new Operand({ type: 'str' })

// --pretty and --format set the same variable in git; both take git's
// optional-value form, so a bare --pretty means medium and a detached next
// word is a revision, never a format. A bare --format stays parseable too,
// but only so prettyValue can answer it with git's own fatal (pretty.c reads
// --format in its =value form alone).
const PRETTY_OPTION = new Option({
  long: '--pretty',
  type: 'str',
  valueOptional: true,
  description:
    'Commit display format: oneline, short, medium, full, fuller, or a format:/tformat:/%-string',
})
const FORMAT_OPTION = new Option({
  long: '--format',
  type: 'str',
  valueOptional: true,
  description: 'Alias of --pretty (requires =value)',
})

const DATE_OPTION = new Option({
  long: '--date',
  type: 'str',
  choices: ['default', 'iso', 'iso8601', 'iso-strict', 'iso8601-strict', 'short', 'unix', 'raw'],
  description: 'Date display format',
})

const DIFF_OPTIONS = [
  new Option({
    short: '-U',
    long: '--unified',
    type: 'int',
    description: 'Number of context lines',
  }),
  new Option({ long: '--name-status', description: 'Show changed paths and status' }),
  new Option({ long: '--name-only', description: 'Show changed paths instead of the patch' }),
  new Option({ long: '--stat', description: 'Show the diffstat table instead of the patch' }),
  new Option({ long: '--numstat', description: 'Show added and deleted line counts per path' }),
  new Option({ long: '--shortstat', description: 'Show only the diffstat summary line' }),
  new Option({ long: '--summary', description: 'Summarize creations, deletions and mode changes' }),
  new Option({ short: '-p', long: '--patch', description: 'Show the patch' }),
  new Option({ short: '-s', long: '--no-patch', description: 'Suppress all diff output' }),
  new Option({
    long: '--no-ext-diff',
    description: 'Accepted for compatibility; there are no external diff drivers to disable',
  }),
  new Option({
    short: '-M',
    long: '--find-renames',
    type: 'str',
    valueOptional: true,
    description: 'Detect renames with an optional similarity threshold',
  }),
  new Option({ long: '--no-renames', description: 'Turn off rename detection' }),
  new Option({ long: '--raw', description: 'Show the raw diff format' }),
]

const MERGE_OPTIONS = [
  new Option({ short: '-m', description: 'Show merge diffs separately against each parent' }),
  new Option({ short: '-c', description: 'Show combined merge diffs' }),
  new Option({ long: '--cc', description: 'Show dense combined merge diffs' }),
  new Option({ long: '--first-parent', description: 'Follow and compare only the first parent' }),
  new Option({ long: '--diff-merges', type: 'str', description: 'Select merge diff mode' }),
]

const LOG_OPTIONS = [
  new Option({
    long: '--author',
    type: 'str',
    multiple: true,
    description: 'Limit commits to matching authors',
  }),
  ...MERGE_OPTIONS,
  new Option({
    long: '--after',
    type: 'str',
    description: 'Commits more recent than a date, like --since',
  }),
  new Option({
    long: '--before',
    type: 'str',
    description: 'Commits older than a date, like --until',
  }),
  new Option({
    long: '--max-parents',
    type: 'int',
    description: 'Show only commits with at most this many parents',
  }),
  new Option({
    long: '--min-parents',
    type: 'int',
    description: 'Show only commits with at least this many parents',
  }),
  new Option({ long: '--merges', description: 'Show only merge commits' }),
  new Option({ long: '--no-merges', description: 'Leave out merge commits' }),

  DATE_OPTION,
  new Option({ long: '--decorate', description: 'Print ref names on commits' }),
  new Option({
    short: '-n',
    type: 'int',
    numericShorthand: true,
    description: 'Limit the number of commits shown',
  }),
  new Option({ long: '--oneline', description: 'One abbreviated line per commit' }),
  new Option({ long: '--reverse', description: 'Print commits oldest first' }),
  new Option({
    long: '--graph',
    description: 'Draw the commit history beside the log (implies --topo-order)',
  }),
  new Option({
    long: '--topo-order',
    description: 'Show no parent before all its children, one line of history at a time',
  }),
  new Option({
    long: '--date-order',
    description: 'Show no parent before all its children, otherwise newest first',
  }),
  new Option({ long: '--all', description: 'Start from every ref as well as the revision' }),
  PRETTY_OPTION,
  FORMAT_OPTION,
  // The pickaxe, and the reason `git log -S <name> --reverse` answers "which
  // commit introduced this": it selects commits that changed how many times the
  // string occurs, not commits that mention it.
  new Option({
    short: '-S',
    type: 'str',
    description: 'Show commits that change the number of occurrences of the string',
  }),
  new Option({
    long: '--since',
    type: 'str',
    description: 'Commits more recent than a date (ISO-8601 or epoch)',
  }),
  new Option({
    long: '--until',
    type: 'str',
    description: 'Commits older than a date (ISO-8601 or epoch)',
  }),
]

const SHOW_OPTIONS = [
  new Option({ long: '--oneline', description: 'One abbreviated line per commit' }),
  ...DIFF_OPTIONS,
  ...MERGE_OPTIONS,
  DATE_OPTION,
  PRETTY_OPTION,
  FORMAT_OPTION,
]

const STATUS_OPTIONS = [
  new Option({
    long: '--porcelain',
    type: 'str',
    valueOptional: true,
    description: 'Machine-readable output, stable across versions',
  }),
  new Option({ short: '-s', long: '--short', description: 'Give the output in the short format' }),
  new Option({
    short: '-b',
    long: '--branch',
    description: 'Show the branch line even in short format',
  }),
  // git spells the mode attached (`-uall`) or not at all, never as a separate
  // token, which is what valueOptional says: a bare -u means "all" and the next
  // word is left alone to be an operand.
  new Option({
    short: '-u',
    long: '--untracked-files',
    type: 'str',
    valueOptional: true,
    choices: ['no', 'normal', 'all'],
    description: 'Show untracked files: no, normal or all',
  }),
]

const PATHSPEC = new Operand({ type: 'str' })

const ADD_OPTIONS = [
  new Option({ short: '-A', long: '--all', description: 'Stage every change' }),
  new Option({
    short: '-u',
    long: '--update',
    description: 'Stage changes to tracked files only',
  }),
  new Option({ short: '-f', long: '--force', description: 'Stage paths an ignore rule covers' }),
  new Option({
    short: '-v',
    long: '--verbose',
    description: 'Name each path as it is added or removed',
  }),
]

const COMMIT_OPTIONS = [
  new Option({
    short: '-a',
    long: '--all',
    description: 'Stage modified and deleted tracked files first',
  }),
  // Required, not defaulted: git would open an editor without it, and a mount
  // has none to open.
  new Option({ short: '-m', long: '--message', type: 'str', description: 'Commit message' }),
  new Option({ long: '--author', type: 'str', description: 'Override the recorded author' }),
]

const CHECKOUT_OPTIONS = [
  new Option({ short: '-b', description: 'Create the branch and switch to it' }),
]

const SWITCH_OPTIONS = [
  new Option({
    short: '-c',
    long: '--create',
    type: 'str',
    description: 'Create the branch and switch to it',
  }),
  new Option({ short: '-d', long: '--detach', description: 'Detach HEAD at the named commit' }),
]

const RESTORE_OPTIONS = [
  new Option({ short: '-S', long: '--staged', description: 'Restore the index' }),
  new Option({
    short: '-W',
    long: '--worktree',
    description: 'Restore the working tree (default)',
  }),
  new Option({
    short: '-s',
    long: '--source',
    type: 'str',
    description: 'Which tree-ish to restore from',
  }),
]

const RM_OPTIONS = [
  new Option({ short: '-r', description: 'Allow recursive removal' }),
  new Option({ long: '--cached', description: 'Only remove from the index, keeping the file' }),
  new Option({ short: '-f', long: '--force', description: 'Override the up-to-date check' }),
  new Option({ short: '-q', long: '--quiet', description: 'Do not list removed files' }),
  new Option({
    long: '--ignore-unmatch',
    description: 'Exit with a zero status even if nothing matched',
  }),
]

const MV_OPTIONS = [
  new Option({
    short: '-f',
    long: '--force',
    description: 'Force move/rename even if target exists',
  }),
  new Option({ short: '-k', description: 'Skip move/rename errors' }),
  new Option({ short: '-n', long: '--dry-run', description: 'Dry run' }),
  new Option({ short: '-v', long: '--verbose', description: 'Be verbose' }),
]

// git's ref-filter options, which `branch` and `tag` share. The four commit
// filters take the next word as their commit, whatever it looks like
// (`--merged --no-merged` names a commit called `--no-merged`), except as the
// line's last word, where they read HEAD: parse-options' LASTARG_DEFAULT. The
// spec has no word for that, so they are declared with an optional value (a
// bare one is HEAD, `--merged=main` is main) and `filterWords` reattaches a
// detached value from the verbatim argv. `--points-at` always takes a value.
const REF_FILTER_OPTIONS = [
  new Option({
    long: '--contains',
    type: 'str',
    valueOptional: true,
    multiple: true,
    metavar: 'commit',
    description: 'List only refs that contain the commit (HEAD if omitted)',
  }),
  new Option({
    long: '--no-contains',
    type: 'str',
    valueOptional: true,
    multiple: true,
    metavar: 'commit',
    description: "List only refs that don't contain the commit (HEAD if omitted)",
  }),
  new Option({
    long: '--merged',
    type: 'str',
    valueOptional: true,
    multiple: true,
    metavar: 'commit',
    description: 'List only refs reachable from the commit (HEAD if omitted)',
  }),
  new Option({
    long: '--no-merged',
    type: 'str',
    valueOptional: true,
    multiple: true,
    metavar: 'commit',
    description: 'List only refs not reachable from the commit (HEAD if omitted)',
  }),
  new Option({
    long: '--points-at',
    type: 'str',
    multiple: true,
    metavar: 'object',
    description: 'List only refs that point at the object',
  }),
]

const TAG_OPTIONS = [
  new Option({ short: '-l', long: '--list', description: 'List tag names' }),
  // git spells the count attached (`-n2`) or not at all, never as a separate
  // token, which is what valueOptional says: a bare -n means one line and the
  // next word is left alone to be a pattern.
  new Option({
    short: '-n',
    type: 'int',
    valueOptional: true,
    description: 'Print <n> lines of each tag message',
  }),
  new Option({ short: '-d', long: '--delete', description: 'Delete tags' }),
  new Option({ short: '-a', long: '--annotate', description: 'Annotated tag, needs a message' }),
  new Option({
    short: '-m',
    long: '--message',
    type: 'str',
    multiple: true,
    description: 'Tag message (repeatable, one paragraph each)',
  }),
  new Option({ short: '-f', long: '--force', description: 'Replace the tag if exists' }),
  ...REF_FILTER_OPTIONS,
]

const BRANCH_OPTIONS = [
  new Option({ long: '--show-current', description: 'Show the current branch name' }),
  new Option({
    short: '-v',
    long: '--verbose',
    count: true,
    description: 'Show commit and upstream details',
  }),
  new Option({ short: '-a', description: 'List local and remote-tracking branches' }),
  new Option({ short: '-r', description: 'List remote-tracking branches' }),
  new Option({ short: '-d', long: '--delete', description: 'Delete a fully merged branch' }),
  new Option({ short: '-D', description: 'Delete a branch even if not merged' }),
  new Option({ short: '-l', long: '--list', description: 'List branches matching the patterns' }),
  ...REF_FILTER_OPTIONS,
]

/**
 * The git program tree. No configModel: local git needs no credentials, which is
 * what makes it installable with a bare `cli: git`.
 *
 * Lives in core rather than node because nothing here touches a runtime API: the
 * verbs read and write through the workspace dispatcher, and isomorphic-git
 * reaches the object database through the same bridge, so a repository mounted
 * in a browser works exactly as one mounted over disk.
 */
export const GIT = new CLISpec({
  name: 'git',
  description: 'Content tracker',
  usageStyle: UsageStyle.GIT,
  options: [DIRECTORY_OPTION],
  subcommands: [
    new CLISpec({
      name: 'version',
      aliases: ['--version', '-v'],
      fn: version,
      description: 'Show the Mirage Git implementation version',
    }),
    new CLISpec({
      name: 'remote',
      description: 'List remotes',
      fn: remote,
      options: [new Option({ short: '-v', long: '--verbose', description: 'Show remote URLs' })],
    }),
    new CLISpec({
      name: 'config',
      description: 'Read repository configuration',
      fn: config,
      options: [
        new Option({ long: '--get', description: 'Get a configuration value' }),
        new Option({ short: '-l', long: '--list', description: 'List every variable and value' }),
        new Option({ long: '--show-origin', description: 'Show the file each value comes from' }),
        new Option({
          long: '--get-regexp',
          description: 'Get the variables whose names match a regular expression',
        }),
      ],
      positional: [new Operand({ type: 'str', name: 'name' })],
    }),
    new CLISpec({ name: 'show-ref', description: 'List references', fn: showRef, rest: REVISION }),
    new CLISpec({
      name: 'shortlog',
      fn: shortlog,
      description: 'Summarize commit history',
      options: [
        ...LOG_OPTIONS.filter((opt) => opt.short !== '-n'),
        new Option({ short: '-s', long: '--summary', description: 'Show only commit counts' }),
        new Option({ short: '-e', long: '--email', description: 'Show author email addresses' }),
        new Option({ short: '-n', long: '--numbered', description: 'Sort by commit count' }),
      ],
      rest: REVISION,
    }),
    new CLISpec({
      name: 'rev-parse',
      fn: revParse,
      description: 'Resolve revisions',
      options: [
        new Option({ long: '--abbrev-ref', description: 'Show abbreviated reference names' }),
      ],
      rest: REVISION,
    }),
    new CLISpec({
      name: 'rev-list',
      description: 'List reachable commits',
      fn: revList,
      options: [...LOG_OPTIONS, new Option({ long: '--count', description: 'Print commit count' })],
      rest: REVISION,
    }),
    new CLISpec({
      name: 'diff-tree',
      description: 'Compare a commit with its parent',
      fn: diffTree,
      options: [
        ...SHOW_OPTIONS,
        new Option({ long: '--no-commit-id', description: 'Suppress commit ID' }),
        new Option({ short: '-r', description: 'Recurse into subtrees' }),
      ],
      positional: [new Operand({ type: 'str', name: 'commit', required: true })],
    }),
    new CLISpec({
      name: 'status',
      description: 'Show the working tree status',
      fn: status,
      options: STATUS_OPTIONS,
    }),
    new CLISpec({
      name: 'log',
      description: 'Show commit logs',
      fn: log,
      options: [...LOG_OPTIONS, ...DIFF_OPTIONS],
      rest: REVISION,
    }),
    new CLISpec({
      name: 'show',
      description: 'Show a commit and its diff',
      fn: show,
      options: SHOW_OPTIONS,
      rest: REVISION,
    }),
    new CLISpec({
      name: 'diff',
      description: 'Show changes between commits',
      fn: diff,
      options: [
        ...DIFF_OPTIONS,
        new Option({ long: '--cached', description: 'Compare the index with a commit' }),
        new Option({ long: '--staged', description: 'Alias of --cached' }),
      ],
      rest: REVISION,
    }),
    new CLISpec({
      name: 'branch',
      description: 'List, create or delete branches',
      fn: branch,
      options: BRANCH_OPTIONS,
      rest: new Operand({ type: 'str' }),
      write: true,
    }),
    new CLISpec({
      name: 'add',
      description: 'Stage working tree content',
      fn: add,
      options: ADD_OPTIONS,
      rest: PATHSPEC,
      write: true,
    }),
    new CLISpec({
      name: 'reset',
      description: 'Unstage, putting the index back to HEAD',
      fn: reset,
      options: [new Option({ short: '-q', long: '--quiet', description: 'Only report errors' })],
      rest: PATHSPEC,
      write: true,
    }),
    new CLISpec({
      name: 'commit',
      description: 'Record the index as a new commit',
      fn: commit,
      options: COMMIT_OPTIONS,
      write: true,
    }),
    new CLISpec({
      name: 'checkout',
      description: 'Switch branches',
      fn: checkout,
      options: CHECKOUT_OPTIONS,
      rest: REVISION,
      write: true,
    }),
    new CLISpec({
      name: 'switch',
      description: 'Switch branches',
      fn: switchBranch,
      options: SWITCH_OPTIONS,
      rest: REVISION,
      write: true,
    }),
    new CLISpec({
      name: 'restore',
      description: 'Restore working tree files',
      fn: restore,
      options: RESTORE_OPTIONS,
      rest: PATHSPEC,
      write: true,
    }),
    new CLISpec({
      name: 'rm',
      description: 'Remove files from the working tree and the index',
      fn: rm,
      options: RM_OPTIONS,
      rest: PATHSPEC,
      write: true,
    }),
    new CLISpec({
      name: 'mv',
      description: 'Move or rename a file, a directory, or a symlink',
      fn: mv,
      options: MV_OPTIONS,
      rest: PATHSPEC,
      write: true,
    }),
    new CLISpec({
      name: 'tag',
      description: 'Create, list or delete a tag',
      fn: tag,
      options: TAG_OPTIONS,
      rest: new Operand({ type: 'str' }),
      write: true,
    }),
  ],
})

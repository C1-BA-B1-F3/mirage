#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$1"
cd "$1"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME='A U Thor' GIT_AUTHOR_EMAIL=author@example.com
export GIT_COMMITTER_NAME='C O Mitter' GIT_COMMITTER_EMAIL=committer@example.com
at() {
  export GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="${2:-$1}"
}
git init -q -b main
git config maintenance.auto false
git config gc.auto 0
printf '%s\n' 'Alice Author <author@example.com>' > .mailmap
at 2020-01-01T12:00:00+0000
printf 'one\n' > a.txt
git add a.txt
git commit -qm First
git tag v1.0
git tag v1.9
at 2020-03-15T09:30:00+0530 2020-03-16T10:00:00-0800
printf 'two\n' > b.txt
git add b.txt
git commit -qm 'Second' -m 'Body line one.
Body line two.'
git tag -a v1.10 -m Ten
git tag -a v2.0-rc1 -m 'Release candidate' -m 'Notes.'
git switch -q -c feature
at 2021-06-01T12:00:00+0000
printf 'three\n' > c.txt
git add c.txt
git commit -qm Third
git tag -a v2.0 -m Two
git tag -a nested -m 'Tag of a tag' v2.0
git tag -a quoted -m "It's \$HOME [a] {b} \"q\" !! back\\slash"
git tag tree-tag 'HEAD^{tree}'
git tag blob-tag HEAD:c.txt
git switch -q main
git branch Upper
git update-ref refs/remotes/origin/main main
git update-ref refs/remotes/origin/feature feature~1
git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
git branch topic main~1
git config remote.origin.url https://example.com/repo.git
git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git config branch.topic.remote .
git config branch.topic.merge refs/heads/main
git config branch.main.remote origin
git config branch.main.merge refs/heads/main
git config branch.feature.remote origin
git config branch.feature.merge refs/heads/feature
git config branch.Upper.remote origin
git config branch.Upper.merge refs/heads/gone
git pack-refs --all
at 2022-02-02T02:02:02+0100
git tag feature feature
git update-ref refs/notes/commits HEAD

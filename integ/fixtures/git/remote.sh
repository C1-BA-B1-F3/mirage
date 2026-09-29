#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$1"
cd "$1"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=A GIT_AUTHOR_EMAIL=a@example.com
export GIT_COMMITTER_NAME=A GIT_COMMITTER_EMAIL=a@example.com
export GIT_AUTHOR_DATE=2024-01-01T00:00:00Z GIT_COMMITTER_DATE=2024-01-01T00:00:00Z
git init -q -b main src
cd src
printf 'one\n' > a
mkdir docs
printf 'notes\n' > docs/readme.md
git add -A
git commit -qm first
git tag v1
git tag -a -m annotated v1a
printf 'two\n' > a
git commit -qam second
git branch topic HEAD~1
cd ..
git init -q --bare empty.git

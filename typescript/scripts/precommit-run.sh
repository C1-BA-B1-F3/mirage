#!/usr/bin/env bash
set -euo pipefail

tool="$1"
shift

# Leading dash args are tool flags; the rest are repo-relative files from
# pre-commit, rebased to the typescript/ package root.
flags=()
files=()
for a in "$@"; do
  if [[ "$a" == -* ]]; then
    flags+=("$a")
  else
    files+=("${a#typescript/}")
  fi
done

cd "$(dirname "$0")/.."
# The installed bin, not `pnpm exec`: pnpm stays resident as a second node
# process per batch and picks its own version through corepack.
bin="node_modules/.bin/$tool"

# Every eslint process builds the TypeScript program of each package it
# lints, so the hook is require_serial and a large batch is halved here
# instead: pre-commit's split into one batch per CPU rebuilt core's program
# fourteen times. Over every file that took 87 s and peaked at 18 GB; two
# halves take 39 s and 6 GB.
if [[ "$tool" == eslint && ${#files[@]} -gt 500 ]]; then
  half=$(((${#files[@]} + 1) / 2))
  "$bin" "${flags[@]}" "${files[@]:0:half}" &
  first=$!
  rc=0
  "$bin" "${flags[@]}" "${files[@]:half}" || rc=$?
  wait "$first" || rc=$?
  exit "$rc"
fi
exec "$bin" "${flags[@]}" "${files[@]}"

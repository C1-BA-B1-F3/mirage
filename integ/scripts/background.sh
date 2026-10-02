#!/usr/bin/env bash
set -euo pipefail

# Runs a long CI step behind the steps after it, on a runner whose other
# cores would otherwise sit idle. `start NAME SCRIPT` runs SCRIPT under bash,
# detached, keeping its output and exit status; `wait NAME`, in a later step,
# blocks until it ends, prints the output and exits with that status, so the
# step that waits reports exactly what the step it replaced did.
dir="${RUNNER_TEMP:-/tmp}/integ-background"

case "${1:-}" in
  start)
    name="${2:?start needs a name}"
    script="${3:?start needs a script}"
    mkdir -p "$dir"
    rm -f "$dir/$name.exit"
    # The script runs under the options a run: step gets (-eo pipefail), and
    # its status lands through a rename, so `wait` never reads a half-written
    # file and takes an empty one for a pass.
    nohup bash -c 'bash -eo pipefail -c "$1"; echo $? > "$2.tmp"; mv "$2.tmp" "$2"' \
      _ "$script" "$dir/$name.exit" > "$dir/$name.log" 2>&1 < /dev/null &
    ;;
  wait)
    name="${2:?wait needs a name}"
    if [ ! -f "$dir/$name.log" ]; then
      echo "background step '$name' was never started" >&2
      exit 2
    fi
    while [ ! -f "$dir/$name.exit" ]; do
      sleep 2
    done
    cat "$dir/$name.log"
    exit "$(cat "$dir/$name.exit")"
    ;;
  *)
    echo "usage: background.sh start NAME SCRIPT | wait NAME" >&2
    exit 2
    ;;
esac

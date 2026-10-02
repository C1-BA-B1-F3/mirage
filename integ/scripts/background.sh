#!/usr/bin/env bash
set -euo pipefail

dir="${RUNNER_TEMP:-/tmp}/integ-background"

# Prints whatever the worker logged since the last call, so a wait that a
# step timeout cuts short has already shown everything up to that moment.
# The new bytes go through a file rather than a pipe: the worker may still
# be writing, and the offset advances by exactly what was printed.
shown=0
show_new() {
  local log="$1" chunk="$1.chunk"
  tail -c "+$((shown + 1))" "$log" > "$chunk"
  cat "$chunk"
  shown=$((shown + $(wc -c < "$chunk")))
}

case "${1:-}" in
  # Runs SCRIPT detached, behind the steps after this one, on a runner whose
  # other cores would otherwise sit idle. It runs under the options a run:
  # step gets (-eo pipefail), and its status lands through a rename, so
  # `wait` never reads a half-written file and takes an empty one for a pass.
  start)
    name="${2:?start needs a name}"
    script="${3:?start needs a script}"
    mkdir -p "$dir"
    rm -f "$dir/$name.exit"
    nohup bash -c 'bash -eo pipefail -c "$1"; echo $? > "$2.tmp"; mv "$2.tmp" "$2"' \
      _ "$script" "$dir/$name.exit" > "$dir/$name.log" 2>&1 < /dev/null &
    echo "$!" > "$dir/$name.pid"
    ;;
  # Streams the worker's output until it ends, then exits with its status,
  # so the step that waits reports exactly what the step it replaced did. A
  # worker that died without writing a status fails at once.
  wait)
    name="${2:?wait needs a name}"
    log="$dir/$name.log"
    if [ ! -f "$log" ]; then
      echo "background step '$name' was never started" >&2
      exit 2
    fi
    pid=$(cat "$dir/$name.pid")
    until [ -f "$dir/$name.exit" ]; do
      show_new "$log"
      if ! kill -0 "$pid" 2>/dev/null && [ ! -f "$dir/$name.exit" ]; then
        show_new "$log"
        echo "background step '$name' ended without an exit status" >&2
        exit 1
      fi
      sleep 2
    done
    show_new "$log"
    exit "$(cat "$dir/$name.exit")"
    ;;
  *)
    echo "usage: background.sh start NAME SCRIPT | wait NAME" >&2
    exit 2
    ;;
esac

#!/usr/bin/env sh
set -eu

ensure_writable_dir() {
  target="$1"
  mkdir -p "$target"
  chown -R appuser:appuser "$target"
}

ensure_writable_dir /home/appuser/.temodar-agent
ensure_writable_dir /app/Plugins
ensure_writable_dir /app/semgrep_results

exec gosu appuser "$@"

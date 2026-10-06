#!/usr/bin/env bash
# Derive per-worktree dev/e2e ports so parallel checkouts never collide
# (docs/ARCHITECTURE.md section 3). Values already set in the environment win.
#
#   BACKEND_PORT  = 20000 + (int(repo_hash, 16) % 20000)
#   FRONTEND_PORT = BACKEND_PORT + 1
#
# Usage:
#   scripts/ports.sh              print "BACKEND_PORT=<n>" and "FRONTEND_PORT=<n>" lines
#   scripts/ports.sh --export     print "export BACKEND_PORT=<n> FRONTEND_PORT=<n>" (for eval)
#   scripts/ports.sh backend      print only the backend port
#   scripts/ports.sh frontend     print only the frontend port
#   source scripts/ports.sh       export both variables into the current shell
#
# Written for bash 3.2 (macOS default) and later; sourcing also works from zsh.

if [ -n "${ZSH_VERSION:-}" ]; then
  eval '_HS_PORTS_SELF=${(%):-%x}' # zsh-only syntax, hidden from bash's parser
else
  _HS_PORTS_SELF="${BASH_SOURCE[0]}"
fi
_HS_PORTS_DIR="$(cd "$(dirname "$_HS_PORTS_SELF")" && pwd -P)"

_hs_ports_valid() {
  case "$1" in
    '' | *[!0-9]*) return 1 ;;
  esac
  [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

_hs_ports_compute() {
  local hash backend frontend
  if [ -n "${BACKEND_PORT:-}" ]; then
    backend="$BACKEND_PORT"
  else
    hash="$("$_HS_PORTS_DIR/repo-hash.sh")" || return 1
    backend=$((20000 + (16#$hash % 20000)))
  fi
  if ! _hs_ports_valid "$backend"; then
    echo "ports: BACKEND_PORT must be an integer in 1..65535 (got '$backend')" >&2
    return 1
  fi
  if [ -n "${FRONTEND_PORT:-}" ]; then
    frontend="$FRONTEND_PORT"
  else
    frontend=$((backend + 1))
  fi
  if ! _hs_ports_valid "$frontend"; then
    echo "ports: FRONTEND_PORT must be an integer in 1..65535 (got '$frontend')" >&2
    return 1
  fi
  _HS_BACKEND_PORT="$backend"
  _HS_FRONTEND_PORT="$frontend"
}

if [ -n "${ZSH_VERSION:-}" ] || [ "${BASH_SOURCE[0]}" != "$0" ]; then
  # Sourced: export into the caller without changing its shell options.
  if _hs_ports_compute; then
    export BACKEND_PORT="$_HS_BACKEND_PORT" FRONTEND_PORT="$_HS_FRONTEND_PORT"
  else
    return 1
  fi
else
  set -euo pipefail
  _hs_ports_compute
  case "${1:-}" in
    '') printf 'BACKEND_PORT=%s\nFRONTEND_PORT=%s\n' "$_HS_BACKEND_PORT" "$_HS_FRONTEND_PORT" ;;
    --export) printf 'export BACKEND_PORT=%s FRONTEND_PORT=%s\n' "$_HS_BACKEND_PORT" "$_HS_FRONTEND_PORT" ;;
    backend) printf '%s\n' "$_HS_BACKEND_PORT" ;;
    frontend) printf '%s\n' "$_HS_FRONTEND_PORT" ;;
    *)
      echo "usage: $0 [--export|backend|frontend]" >&2
      exit 2
      ;;
  esac
fi

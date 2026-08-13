#!/usr/bin/env bash

# This file is sourced by deploy_to_server.sh and is also executable so the
# non-mutating production profile can be verified without contacting a server.
AICHECK_RUNTIME_ENABLE_DEMO_DATA=false
AICHECK_RUNTIME_BOOTSTRAP_LOCAL_ROLES=false

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    --json)
      printf '%s\n' '{"bootstrapLocalRoles": false, "enableDemoData": false}'
      ;;
    *)
      echo "usage: $0 --json" >&2
      exit 64
      ;;
  esac
fi

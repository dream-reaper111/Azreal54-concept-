#!/usr/bin/env bash
# Read-only diagnostics for AZRAEL Compose containers. This script does not
# start, stop, remove, or modify containers, images, volumes, or host settings.
set -uo pipefail

if ! command -v podman >/dev/null 2>&1; then
  printf '%s\n' 'podman is not available in PATH.' >&2
  exit 2
fi

printf '%s\n' '== Rootless Podman identity and graphroot (read-only) =='
podman info --format 'rootless={{.Host.Security.Rootless}} graphroot={{.Store.GraphRoot}} runtime={{.Host.OCIRuntime.Name}}' || {
  printf '%s\n' 'podman info failed; stopping without changing anything.' >&2
  exit 2
}

containers="$(podman ps -a --format '{{.ID}} {{.Names}}')" || {
  printf '%s\n' 'podman ps failed; stopping without changing anything.' >&2
  exit 2
}

found=0
while read -r container_id container_name; do
  [[ -n "${container_id:-}" && "${container_name:-}" == azrael54_* ]] || continue
  found=1
  printf '\n== %s (%s) ==\n' "$container_name" "$container_id"
  if ! podman inspect --format \
    'userns={{.HostConfig.UsernsMode}} configured_user={{.Config.User}} state={{.State.Status}} started_at={{.State.StartedAt}} error={{.State.Error}}' \
    "$container_id"; then
    printf '%s\n' 'inspect failed'
  fi
  printf '%s\n' '-- last 20 log lines --'
  if ! podman logs --tail 20 "$container_id" 2>&1; then
    printf '%s\n' 'podman logs failed or no logs are available'
  fi
  printf '%s\n' '-- writable-layer diff --'
  if ! podman diff "$container_id"; then
    printf '%s\n' 'podman diff failed'
  fi
done <<<"$containers"

if (( ! found )); then
  printf '%s\n' 'No containers with names beginning azrael54_ were found.'
fi

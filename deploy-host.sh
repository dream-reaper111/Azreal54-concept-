#!/usr/bin/env bash
# Safe AZRAEL host deployment. Existing project containers are preserved by default.
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

if [[ "${EUID}" -eq 0 ]]; then
  printf '%s\n' 'Run as your ordinary Pop!_OS user, not with sudo.' >&2
  exit 2
fi

gpu_requested=0
gpu=0
gpu_failed=0
gpu_preflight_log=""
verify_providers=0
recreate=0
trap 'if [[ -n "$gpu_preflight_log" ]]; then rm -f -- "$gpu_preflight_log"; fi' EXIT
for arg in "$@"; do
  case "$arg" in
    --gpu) gpu_requested=1 ;;
    --verify-providers) verify_providers=1 ;;
    --recreate-project-containers) recreate=1 ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

if ! command -v podman >/dev/null || ! command -v podman-compose >/dev/null; then
  printf '%s\n' 'Podman and podman-compose must both be installed and available in PATH.' >&2
  exit 2
fi

printf '%s\n' '== Rootless Podman and storage inspection =='
podman info --format 'rootless={{.Host.Security.Rootless}} graphroot={{.Store.GraphRoot}} driver={{.Store.GraphDriverName}} runtime={{.Host.OCIRuntime.Name}}'
graphroot="$(podman info --format '{{.Store.GraphRoot}}')"
df -h -- "$graphroot" /data/work
printf '\n%s\n' '== Existing AZRAEL containers (read-only inspection) =='
podman ps -a --filter label=com.docker.compose.project=azrael54 \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
while IFS= read -r container_id; do
  [[ -n "$container_id" ]] || continue
  podman inspect --format \
    'name={{.Name}} status={{.State.Status}} error={{.State.Error}} image={{.Config.Image}} user={{.Config.User}} userns={{.HostConfig.UsernsMode}}' \
    "$container_id"
done < <(podman ps -aq --filter label=com.docker.compose.project=azrael54)

printf '\n%s\n' '== Rootless OCI, mount, user namespace, and AZRAEL storage preflight =='
python3 setup_lab.py --runtime podman --preflight

printf '\n%s\n' '== Host storage write/read and private-permission check =='
python3 setup_lab.py --runtime podman --storage-check

if (( gpu_requested )); then
  printf '\n%s\n' '== RTX 3080 rootless CDI probe (CPU deployment remains available on failure) =='
  gpu_preflight_log="$(mktemp /tmp/azrael54-gpu-preflight.XXXXXX)"
  if python3 setup_lab.py --runtime podman --gpu-preflight >"$gpu_preflight_log" 2>&1; then
    cat -- "$gpu_preflight_log"
    gpu=1
  else
    cat -- "$gpu_preflight_log"
    gpu_failed=1
    printf '%s\n' 'GPU preflight failed; continuing with the CPU deployment and recording the GPU blocker.' >&2
  fi
fi

if (( gpu_failed && recreate )); then
  printf '%s\n' 'GPU preflight failed; refusing explicit container recreation. No AZRAEL containers were changed.' >&2
  exit 3
fi

if (( recreate )); then
  printf '\n%s\n' '== Read-only writable-layer audit for the five AZRAEL services =='
  layer_changes=0
  inspected_services=0
  while IFS= read -r container_id; do
    [[ -n "$container_id" ]] || continue
    service="$(podman inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$container_id")"
    if [[ -z "$service" ]]; then
      service="$(podman inspect --format '{{ index .Config.Labels "io.podman.compose.service" }}' "$container_id")"
    fi
    case "$service" in
      tools|imports|web-lab|external-tools|dashboard) ;;
      "")
        printf 'Could not identify Compose service for project container %s; refusing recreation.\n' "$container_id" >&2
        exit 3
        ;;
      *)
        printf 'Project container %s belongs to service %s, outside this recreation set; it will be preserved.\n' "$container_id" "$service"
        continue
        ;;
    esac
    inspected_services=$((inspected_services + 1))
    started_at="$(podman inspect --format '{{.State.StartedAt}}' "$container_id")" || {
      printf 'Could not inspect StartedAt for %s (%s); refusing recreation.\n' "$service" "$container_id" >&2
      exit 3
    }
    started_kind="$(python3 writable_layer_audit.py "$started_at" --started-only)" || {
      printf 'Could not classify StartedAt for %s (%s); refusing recreation.\n' "$service" "$container_id" >&2
      exit 3
    }
    if [[ "$started_kind" == never_started ]]; then
      printf 'Skipping writable-layer diff for never-started container %s (%s), StartedAt=%s.\n' "$service" "$container_id" "$started_at"
      continue
    fi
    changes="$(podman diff "$container_id")" || {
      printf 'Could not inspect writable layer for %s (%s); refusing recreation.\n' "$service" "$container_id" >&2
      exit 3
    }
    if audit_result="$(python3 writable_layer_audit.py "$started_at" <<<"$changes")"; then
      printf '%s: %s\n' "$service" "$audit_result"
    else
      layer_changes=1
      printf 'Unexpected writable-layer changes detected in %s (%s):\n%s\n' "$service" "$container_id" "$audit_result" >&2
    fi
  done < <(podman ps -aq --filter label=com.docker.compose.project=azrael54)
  if (( layer_changes )); then
    printf '%s\n' 'Refusing recreation because it would discard detected container writable-layer changes. Preserve/review those changes before retrying.' >&2
    exit 3
  fi
  printf 'Audit complete for %s existing AZRAEL service container(s); no unexpected started-container changes were reported.\n' "$inspected_services"
  printf '%s\n' 'Recreation is limited to tools, imports, web-lab, external-tools, and dashboard. Bind data and volumes are not removed.'
fi

printf '\n%s\n' '== Build and start AZRAEL services =='
args=(--runtime podman --build --start --verify --verify-slm)
(( gpu )) && args+=(--verify-gpu)
(( verify_providers )) && args+=(--verify-providers)
(( recreate )) && args+=(--recreate-project-containers)
python3 setup_lab.py "${args[@]}"

if (( gpu_failed )); then
  python3 - "$gpu_preflight_log" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
report_path=Path('DEPLOYMENT-VERIFICATION.json')
report=json.loads(report_path.read_text())
report['deployment_status']=report.get('status')
report['status']='passed_cpu_fallback_gpu_unavailable' if report.get('status')=='passed' else report.get('status')
report['gpu_preflight']={'status':'failed; CPU fallback used','details':Path(sys.argv[1]).read_text()[-4000:]}
report['recorded_at']=datetime.now(timezone.utc).isoformat()
report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
PY
fi

printf '\n%s\n' 'AZRAEL deployment checks completed. The report records any verification failures.'

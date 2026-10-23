# AZRAEL-54 host recovery checklist

Run the steps from a normal Pop!_OS terminal as the `deadbyte` user, except for the single CDI generation command marked `sudo`. Do not continue past a failed step. The project files, deployment report, and healthcheck fixes are prepared, but host verification is still required.

## 1. Capture the current keep-id error (read-only)

```bash
cd /home/deadbyte/azrael54
./diagnose-keepid.sh
```

Pass: the script lists each `azrael54_*` container with userns mode, configured user, state, `State.Error`, `StartedAt`, the last 20 log lines, and `podman diff`. It must not change any container. Paste the complete output back, especially any nonempty `error=` field and log lines around the failure. If `podman info` or `podman ps` fails, paste that error and stop.

## 2. Review writable layers before removing any current containers

This loop only inspects. It prints the start time and diff, then classifies each container using the same conservative rule as the deployment wrapper:

```bash
cd /home/deadbyte/azrael54
while read -r id name; do
  [[ "$name" == azrael54_* ]] || continue
  started="$(podman inspect --format '{{.State.StartedAt}}' "$id")" || { echo "inspect failed for $id" >&2; break; }
  diff="$(podman diff "$id")" || { echo "podman diff failed for $id" >&2; break; }
  printf '\n== %s %s StartedAt=%s ==\n%s\n' "$name" "$id" "$started" "$diff"
  python3 writable_layer_audit.py "$started" <<<"$diff"
done < <(podman ps -a --format '{{.ID}} {{.Names}}')
```

Pass for a started container: the classifier prints `"status": "clean"`; the only tolerated entries are `C /etc` and `A` or `C` for `/etc/hosts`, `/etc/resolv.conf`, and `/etc/hostname`. The operator can still see a never-started container's read-only `podman diff` output, while the deploy audit skips that container. If any started container prints `blocked`, do not remove or recreate it; paste that container's full diff first.

Only after reviewing the diagnostics and confirming the container is clean, you may remove that specific AZRAEL container to discard its now-verified disposable layer. Replace the placeholder with the exact audited ID; repeat only for IDs that passed:

```bash
podman rm -f CONTAINER_ID
```

This affects that one container and its writable layer only. It does not remove Compose networks, volumes, datasets, model files, checkpoints, evidence databases, or Docker resources. Do not use a broad prune command.

## 3. Redeploy CPU services

```bash
cd /home/deadbyte/azrael54
./deploy-host.sh --recreate-project-containers
```

Pass: preflight and storage checks pass; the layer audit permits recreation; all four independent services become healthy; then dashboard starts and the script reports dashboard/API checks and an actual CPU SLM inference as passed. If it stops at a preflight, diff, healthcheck, or inference error, paste the complete output and `DEPLOYMENT-VERIFICATION.json`, then stop.

## 4. Independently verify CPU health

```bash
cd /home/deadbyte/azrael54
podman ps --filter label=com.docker.compose.project=azrael54
curl -i --max-time 5 http://127.0.0.1:8765/healthz
```

Pass: the five project services are running/healthy, and `curl` returns HTTP 200 with the health response. Also confirm the deployment command reported CPU SLM inference passed. If not, paste the command output and stop before GPU preparation.

## 5. Prepare and test NVIDIA CDI on the host

Do this only after CPU health and inference pass. The agent has not generated CDI or changed `/etc`.

```bash
nvidia-smi
nvidia-ctk --version
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
nvidia-ctk cdi list
```

Pass: `nvidia-smi` lists the RTX 3080; `nvidia-ctk cdi list` prints at least one `nvidia.com/gpu=<index>` entry. If `nvidia-ctk` is missing or generation/listing fails, paste the full error and stop.

Run the actual rootless `keep-id` check for the RTX 3080 selected by name:

```bash
gpu_index="$(nvidia-smi --query-gpu=index,name --format=csv,noheader | awk -F, 'tolower($2) ~ /rtx 3080/ { gsub(/[[:space:]]/, "", $1); print $1; exit }')"
test -n "$gpu_index" || { echo 'RTX 3080 index not found'; exit 1; }
printf 'Selected RTX 3080 index: %s\n' "$gpu_index"
podman run --rm --pull=missing --network=none --device "nvidia.com/gpu=${gpu_index}" --userns keep-id docker.io/library/ubuntu:24.04 nvidia-smi
```

Pass: the container exits zero and its `nvidia-smi` output includes the RTX 3080. If it fails, paste the CDI list and complete Podman error; do not start a GPU build.

## 6. Deploy CUDA only after all earlier checks pass

```bash
cd /home/deadbyte/azrael54
./deploy-host.sh --gpu --recreate-project-containers
```

Pass: the 60 GiB graphroot reserve, CDI listing, selected-device Podman `keep-id` probe, writable-layer audit, CUDA image build, dashboard/API health, CUDA PyTorch loading, and actual SLM inference all pass. The report must show CUDA inference and GPU telemetry; a host `nvidia-smi` check alone is not sufficient. If the graphroot gate fails, paste the reported path and free space; moving graphroot is a separate change that needs mapped-ID traversal access on its ancestors.

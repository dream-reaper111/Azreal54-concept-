# AZRAEL-54 Deployment and GPU Status

**Verified:** 20 October 2026 (Pop!_OS host local time, MDT)  
**Profile:** rootless Podman with CUDA enabled; all six required services healthy  
**Dashboard:** [http://127.0.0.1:8765](http://127.0.0.1:8765)  
**Health:** `GET /healthz` returns HTTP 200

## Deployment result

AZRAEL-54 is running with the CUDA dashboard image. The frontend is published only on `127.0.0.1:8765`. The dashboard uses the RTX 3080 by default and can select GPUs by UUID. CPU inference remains available and was verified through the authenticated API.

The deployment passed the full test suite (**170 tests**), host and rootless-container GPU checks, authenticated GPU inference, CPU fallback, dashboard/API checks, CTF model practice, and persistent-data checks. No extended training job was started. The idle trainer remains operator-approved and does not train automatically.

## Host GPU inventory

Host: Pop!_OS 24.04 LTS, x86_64. NVIDIA driver: `580.173.02`; Container Toolkit: `1.20.1`; Podman: `4.9.3`; CUDA framework build: PyTorch `2.11.0+cu128` / CUDA `12.8`.

| GPU | UUID | VRAM | Compute capability | PCI bus | Container test |
|---|---|---:|---:|---|---|
| GeForce RTX 3060 Ti | `GPU-ef312e7d-5cf1-e04c-eeff-2f1c1c80ce6e` | 8192 MiB | 8.6 | `01:00.0` | Pass |
| GeForce RTX 5060 | `GPU-5aa46030-9e89-432f-ecfe-90daf9d56e30` | 8151 MiB | 12.0 | `02:00.0` | Pass |
| GeForce RTX 3080 | `GPU-e6a4de67-74d6-38f7-e185-214a092dd995` | 10240 MiB | 8.6 | `04:00.0` | Pass |

The RTX 5060 was tested with the installed CUDA 12.8/PyTorch build; its compute capability 12.0 completed CUDA operations. PCIe topology reports host bridges between GPUs and no NVLink.

## Rootless CDI and container isolation

The system-owned CDI files were left untouched. AZRAEL generates a user-owned private CDI 0.5 spec at `.runtime/cdi-compat/nvidia.yaml` (directory mode `0700`, spec mode `0600`) and loads it in a private mount namespace through `container/podman-cdi-compat.sh`. The compatibility transform removes display-only DRM nodes and filesystem-mutating symlink/ld-cache hooks, converts eligible driver-library aliases to read-only binds, and retains NVIDIA device nodes and CUDA memory hooks. The `nvidia-smi` utility is mounted read-only for real UUID telemetry.

GPU probes ran as the rootless project user with `keep-id`, no network, a read-only container root, all capabilities dropped, `no-new-privileges`, and a bounded temporary filesystem. No privileged container or unrestricted host device mount was used.

## Runtime and inference evidence

Every device passed an isolated container CUDA matrix operation and a real forward/backward/SGD optimizer update. An all-device run exposed all three GPUs and completed those operations on each visible CUDA device. This validates CUDA execution and a bounded training step; it does **not** claim distributed model training or model sharding.

The optimizer probe uses ephemeral randomized tensors and an in-memory linear layer solely to validate CUDA backward/optimizer execution; it does not train on a project dataset or alter persistent weights. No admitted, labeled train/validation/test manifest set was available under the persistent dataset/checkpoint paths, so no non-synthetic fine-tuning run is claimed.

| Check | Result |
|---|---|
| RTX 3060 Ti selected by UUID | CUDA operation and optimizer update passed |
| RTX 5060 selected by UUID | CUDA operation and optimizer update passed |
| RTX 3080 selected by UUID | CUDA operation and optimizer update passed |
| All three visible together | CUDA operation and optimizer update passed on all three |
| Authenticated SLM inference | Qwen2.5-Coder-1.5B-Instruct on RTX 3080; `cuda:0`; 3,097,950,720 bytes allocated; 7,707.8 ms in the final verification sample |
| CPU fallback | Explicit CPU inference passed |
| Authenticated CTF model practice | Completed on CUDA; 3,097,954,816 bytes allocated; no evidence or training data written |

Inference latency is one request sample, not an average benchmark. CUDA devices are ordered by discovered UUID; the default worker is assigned only to the RTX 3080. CUDA telemetry is read from host GPU data. Multi-GPU visibility is validated, while model sharding is not enabled.

An authenticated dashboard telemetry sample exposed all three UUIDs and live utilization, VRAM, temperature, and power fields. At that sample: 3060 Ti `22% / 2316 of 8192 MiB / 60 C / 40.4 W`; 5060 `0% / 82 of 8151 MiB / 30 C / 10.47 W`; 3080 `1% / 21 of 10240 MiB / 42 C / 19.87 W`. These readings vary with host activity.

## CTF, directive, and idle training status

The authenticated offline practice lab contains 20 sourced challenges from the MIT-licensed [CTFd Challenge Assets project](https://github.com/zachflower/ctfd-challenge-assets), pinned in the project metadata. The set is self-contained and makes no network calls or target probes. Answers remain private; attempts are stored separately from operational evidence and datasets. One model-practice request completed on CUDA; it did not submit a correct flag in that run. These are challenge artifacts, not incident telemetry.

The shared SLM directive now asks roles to think beyond the obvious, examine assumptions and edge cases, and identify challenge loopholes within the authorized AZRAEL range and supplied CTF scope. It explicitly preserves target allowlists, human approvals, evidence rules, data protections, and stop controls. A challenge or directive cannot grant execution authority.

The idle trainer waits for an operator-approved job and idle shared worker. It uses existing frozen datasets and the bounded classifier-training pipeline; it does not launch automatically, promote role weights, or resume queued jobs after restart. No prolonged training job was started for this deployment.

## Health, storage, and backups

`podman ps --filter label=com.docker.compose.project=azrael54` showed all six required services running and healthy: tools, imports, Juice Shop, external-tools, dashboard, and frontend. Only the frontend publishes a host port, on `127.0.0.1:8765`; no unexpected listener was found on that port.

SQLite integrity checks returned `ok` for:

- Juice Shop database: 22 tables.
- Evidence database: 14 tables.
- CTF progress database: 2 tables.

The active Qwen model remains the project’s read-only `.slm-model` asset; all nine files match `slm-model-manifest.json`, including `model.safetensors` SHA-256 `c1b9b30e907950516ba3c646bdf570d8084c25a6410a0cdca80cf04b11bc13a8`. The read-only research corpus under `data/` remains present (805 files, about 164 MiB). The shared `/data/work/azrael54/datasets` and `checkpoints` directories were empty at verification; no checkpoint was generated by this deployment.

Verified pre-deployment backups remain at `/data/work/azrael54-backups/host-recovery-20261020T172811Z`. The installer rechecked `SHA256SUMS`, the archived project-state checksum, and the archive listing before deployment. The preserved Juice Shop image snapshot, writable-layer files, SQLite database, logs, datasets, models, and evidence archive remain outside containers. This run did not need a new Juice Shop migration or container recreation.

All deployment operations were scoped to Compose project `azrael54`. The separate NeoCortex/HellPot deployment was not modified. Its existing containers were not targeted.

## Persistent service management

The rootless user unit is `/home/deadbyte/.config/systemd/user/azrael54.service`; it is enabled and active. User lingering is enabled, and reboot persistence is recorded as verified. Containers use Compose `unless-stopped`; the systemd unit does not add a competing restart loop (`Restart=no`). Services were left running.

## Recovery and operator commands

```bash
cd /home/deadbyte/azrael54
./azraelctl status
./azraelctl verify
./azraelctl logs
./azraelctl doctor
./azraelctl restart
./azraelctl start
./azraelctl stop
```

Regenerate the private CDI compatibility spec and verify GPUs before a planned GPU redeployment with:

```bash
cd /home/deadbyte/azrael54
./azraelctl doctor
./azraelctl verify
AZRAEL_GPU_MIN_FREE_GB=40 ./azraelctl bootstrap --gpu auto
```

The 40 GiB reserve override was used for this rollout because the Podman graphroot had about 45 GiB free and the CUDA build layers were already cached. After the build, the root filesystem reports 37 GiB free. The deployed images and CPU rollback image are being retained; no image prune or backup cleanup was run. The normal 60 GiB preflight reserve remains unchanged, so a future GPU rebuild/update should wait until more root filesystem space is available. No driver reinstall or host reboot was performed.

## Current host lifecycle status — 2026-10-20

This section supersedes the earlier all-healthy and active-unit status above for the current runtime. The full verification and GPU inference described earlier passed before a subsequent systemd restart check. That restart exposed a rootless networking failure, and current full-stack operation is **not verified**.

- Five services are running and healthy: tools, imports, Juice Shop, external-tools, and dashboard. Their container health checks pass.
- The frontend container is running and serves the static AZRAEL artwork/UI at `http://127.0.0.1:8765/` (HTTP 200), but its proxy health check and `/healthz` time out. Authenticated API requests through the frontend are therefore unavailable.
- `azrael54.service` remains enabled and user lingering remains enabled, but the latest restart attempt failed; systemd reports the unit as `failed`. Do not treat restart persistence as verified.
- The failure evidence is rootless networking: nginx cannot resolve the `dashboard` upstream; the Aardvark DNS configuration has stale/missing service records and logs `Cannot assign requested address`; targeted `podman network reload azrael54_dashboard_1` fails with `unknown FS magic` for the rootless network namespace followed by `setns: Invalid argument`.
- The failed frontend container had no writable-layer changes and no mounts; its local image was preserved. Only that stateless frontend container was recreated. No Juice Shop, model, dataset, evidence, or unrelated container data was removed.
- Read-only `PRAGMA quick_check` after the restart returned `ok` for the live Juice Shop, evidence, and CTF progress SQLite databases. The verified backup set remains at `/data/work/azrael54-backups/host-recovery-20261020T172811Z`.
- No host reboot, driver change, backup cleanup, image prune, or NeoCortex/HellPot operation was performed.

Repair the rootless Podman/netavark network namespace before treating the API, GPU-backed dashboard, restart lifecycle, or deployment as operational again. After repair, run `./azraelctl start`, `./azraelctl verify`, and `curl -i --max-time 5 http://127.0.0.1:8765/healthz`; do not force-recreate Juice Shop as part of this recovery.

## Rootless Podman network namespace recovery — 2026-10-20

This follow-up supersedes the current-runtime notes above. The full-stack repair is **blocked**; do not treat AZRAEL as healthy.

### Diagnosis

- Podman inspect initially reported frontend `10.89.3.190` and dashboard `10.89.3.187` on `azrael54_lab`, with separate netns inodes (`4026536553` and `4026535974`). Both had a connected `10.89.3.0/24` route and `eth0`; the dashboard address was not stale in the container inspect data.
- Aardvark's active `azrael54_lab` file had no dashboard record and retained old web-lab `.186` and frontend `.188` records alongside current `.189` and `.190` records. Its UDP listener was bound to `10.89.3.1:53` in netns inode `4026534899`, but frontend queries got `ECONNREFUSED`; dashboard IP requests from frontend got `Host is unreachable`.
- The rootless network namespace held `podman4` (`10.89.3.1/24`) and lacked `podman5`/`podman6`, despite Aardvark config entries for gateways `10.89.4.1` and `10.89.5.1`. Existing Aardvark logs report `Cannot assign requested address` for those missing gateways.
- The Netavark IPAM database and Libpod inspect state disagree: `podman network disconnect --force azrael54_lab azrael54_dashboard_1` reported it could not find the dashboard's IP lease for subnet `10.89.3.0/24`. This is a Netavark state inconsistency, not an NGINX-only issue.
- The namespace paths in `/run/user/1000/netns/` are empty regular files on tmpfs, not mounted namespace handles. The journal records Netavark `setns: Invalid argument` and failed namespace unmounts for the frontend and dashboard. `podman network reload` also fails on this stale rootless namespace path.
- `azrael54.service` is a rootless `Type=oneshot` unit. There is no installed or active `podman-compose@azrael54.service`; that string is only a container label. At the previous failed start, systemd's default `KillMode=control-group` killed conmon after the frontend health timeout. This was a secondary lifecycle hazard; it did not create the already stale DNS/IPAM state.

### Safe changes and attempted recovery

- Updated the AZRAEL unit generator and current user unit to `KillMode=process` with `TimeoutStopSec=360`, so a failed oneshot will not kill detached conmon processes in its control group. The previous unit file is preserved at `/data/work/azrael54-backups/host-recovery-20261020T172811Z/azrael54.service.pre-network-fix`. This mitigation is not a network repair and has not passed a systemd restart test.
- Tried a targeted dashboard network disconnect; Netavark rejected it before applying the disconnect because the IPAM lease was missing.
- A targeted dashboard restart then hit the stale namespace cleanup error. `podman container cleanup azrael54_dashboard_1` returned success without removing its container or writable layer, but Podman remains inconsistent: `crun state` says `stopped`, while `podman inspect` reports `stopping` and `podman start` rejects the state as improper. The dashboard container ID and its seven bind mounts remain present. No container was removed or recreated.
- Five other AZRAEL containers remain running: tools, imports, web-lab, external-tools, and frontend. The dashboard runtime is stopped/stuck. Frontend DNS still fails and its direct request to the former dashboard address is unreachable. The localhost port remains bound to `127.0.0.1:8765`, but `/healthz` and `/api/state` both time out with curl HTTP status `000`.

### Data and GPU checks

- After the targeted attempt, read-only SQLite `PRAGMA quick_check` returned `ok` for `/data/work/azrael54/juice-shop-data/juiceshop.sqlite`, `/data/work/azrael54/evidence/evidence.sqlite3`, and `/data/work/azrael54/training/ctf/progress.sqlite3`. The existing verified host-recovery backups remain available at `/data/work/azrael54-backups/host-recovery-20261020T172811Z`.
- Host CUDA remains available on all three GPUs with PyTorch `2.11.0+cu128` / CUDA `12.8`; a small CUDA matrix operation and synchronization passed on RTX 3080, RTX 3060 Ti, and RTX 5060. The dashboard is stopped, so authenticated service-level inference was not verifiable in this follow-up.
- No Podman reset, network removal/pruning, container removal/recreation, driver change, reboot, or unrelated deployment operation was performed. NeoCortex/HellPot and Snap Docker were not targeted.

### Blocker

Podman cannot transition the existing dashboard container from its stale `stopping` state, and its network/IPAM cleanup cannot enter the stale namespace path. Recovery now requires either supported Podman state repair or a backed-up container replacement; the latter is explicitly excluded by this task. Do not attempt a Podman reset, edit the IPAM database, remove the network, or force-recreate the dashboard/other containers to bypass this gate. The systemd stop/restart cycle, healthy DNS, authenticated API, HTTP 200 `/healthz`, and containerized CUDA inference remain unverified. Preserve the four healthy backend/lab services and wait for a safe Podman state-repair path before continuing.

## Rootless Podman read-only recovery recheck — 2026-10-20

This is a newer read-only snapshot than the diagnosis above. No container, network, host networking, GPU, or systemd state was changed during this recheck. The only write authorized in this turn was this documentation update.

### Current evidence and diagnosis

- The original dashboard container is still present with ID `ec79c5054492f50f5bdb87a76a0d0c652436dbaf2dd22408433a9cc09cf0addd`. Podman reports `Status=stopping`, `Running=false`, PID `944506`, and ConmonPid `944503`; `ps` finds neither process. Its current `SandboxKey` points at `/proc/944506/ns/net`, which is no longer available. Unlike the earlier inspect snapshot, the current `NetworkSettings` has no dashboard IP and lists only an empty `bridge` attachment, not `azrael54_lab`.
- The frontend is running as PID `956122` in netns inode `4026536553`, has `10.89.3.190/24` on `azrael54_lab`, a route through `10.89.3.1`, and `nameserver 10.89.3.1`. Its healthcheck is failing due to timeout. A direct `busybox nslookup dashboard 10.89.3.1` returns connection refused and then times out. This confirms DNS is not serving the frontend in its current network context.
- `azrael54_lab` still exists as an internal, DNS-enabled Netavark bridge for `10.89.3.0/24` with gateway `10.89.3.1` and host-side interface name `podman4`. The four other backend/lab containers remain running and healthy. The frontend remains running but unhealthy; the dashboard is stuck. No other AZRAEL container was restarted.
- Aardvark process PID `939372` is alive, but it is in netns inode `4026534899`; the frontend is in a different netns. The Aardvark directory was listed only and its contents were not read or edited. Host `ss` showed only loopback DNS stub sockets, so it does not prove Aardvark's listener state in its own namespace. An attempt to inspect that namespace with `nsenter` was denied (`Operation not permitted`). Thus the process is alive, but its listener and bridge reachability from inside its namespace could not be verified.
- `/run/user/1000/netns/` contains eight zero-byte regular files and one `rootless-netns-*` file. `findmnt -t nsfs` showed only Snap namespace mounts; the candidate `netns-bd33ecdb-4d59-0960-9537-b2a0038161db` resolves to the user runtime tmpfs, not an nsfs mount. Its timestamp is near the dashboard's recorded start time, but the available Podman inspect data does not map that filename to the dashboard with certainty. `lsns` could not enumerate namespaces (`Unsupported ioctl NS_GET_USERNS`). No path is identified as safe to delete or unmount; do not do so without approval of that exact path.
- The user unit is `azrael54.service`; there is no separate dashboard unit. Its current definition retains `KillMode=process` and `TimeoutStopSec=360`. The journal shows the prior stack stop timed out and systemd logged SIGKILLs for conmon processes, including dashboard conmon PID `944503`, after which the unit failed. With `KillMode=process`, systemd does not clean up stray children after a failed start, so orphaned processes are possible. No live manual Podman Compose lifecycle command was found in the process listing; Aardvark and the frontend conmon remain alive.
- Likely root cause, based on these observations: the previous failed stack stop left Podman's dashboard record in `stopping` after its conmon/init process exited, while its network sandbox reference and network attachment/IPAM state no longer agree. This stale per-container runtime/network state explains why `podman start` is rejected and why DNS cleanup/connectivity is broken. The precise orphaned netns filename and the exact internal Netavark/Aardvark failure point remain unproven; no network state files were inspected or changed.

### Which recovery steps are justified

- The next safe step is the gated, per-container Step 2 recovery, targeting the actual Podman name `azrael54_dashboard_1` so the same container ID and its mounts are retained. `podman container cleanup azrael54_dashboard_1` was already attempted earlier and returned success without clearing the stuck inspect state; repeating the prescribed sequence remains the only currently justified targeted recovery. It has not been rerun in this recheck and still requires the user's `go`.
- Do not proceed to Step 3 unless the approved cleanup reports the namespace error; even then, identify and propose the exact path only, and wait for approval before deleting or unmounting it. Step 4 (`podman system migrate` or a user-session cycle) is not yet justified and would disturb the four healthy services. Step 5 waits until the dashboard starts; frontend restart, endpoint checks, service CUDA inference, and the systemd lifecycle test have not been run.
- The original dashboard container ID and seven bind mounts have not been changed. SQLite checks and host CUDA evidence recorded above remain the latest applicable data/GPU checks; service-level CUDA inference remains unverified.

### Commands run during this read-only recheck

The following are the shell command lines run for this turn's inspection, in order. Commands that returned errors are documented above; none of those errors changed state.

```sh
sed -n '100,190p' docs/GPU_DEPLOYMENT_STATUS.md
sed -n '1215,1245p' azraelctl
podman inspect azrael54_dashboard_1 --format '{{.Id}} {{json .State}} {{json .NetworkSettings}}'
printenv XDG_RUNTIME_DIR
podman ps -a --filter label=com.docker.compose.project=azrael54
podman network ls
systemctl --user list-units --all --no-legend
findmnt -t nsfs
ps -p 944506,944503 -o pid,ppid,stat,lstart,cmd
ls -la /run/user/1000/netns/
ls -lh /run/user/1000/containers/networks/aardvark-dns/
systemctl --user list-units --all --no-legend | rg 'azrael|ec79|podman-compose'
journalctl --user -u azrael54.service -n 100 --no-pager
systemctl --user status azrael54.service --no-pager
podman inspect azrael54_frontend_1 --format '{{.Id}} {{json .State}} {{json .NetworkSettings}}'
podman inspect azrael54_tools_1 azrael54_imports_1 azrael54_web-lab_1 azrael54_external-tools_1 --format '{{.Name}} {{.State.Pid}} {{.State.ConmonPid}} {{.NetworkSettings.SandboxKey}} {{json .NetworkSettings.Networks}}'
podman network inspect azrael54_lab
podman exec azrael54_frontend_1 sh -c 'printf "netns="; readlink /proc/1/ns/net; printf "resolv.conf="; cat /etc/resolv.conf; printf "routes="; cat /proc/net/route; printf "interfaces="; cat /proc/net/dev'
pgrep -af aardvark
ss -lunp | rg '(:53\s|:53$)'
ip -d addr show
readlink /proc/956122/ns/net /proc/939358/ns/net /proc/939372/ns/net /proc/951267/ns/net
lsns -t net -o NS,TYPE,NPROCS,PID,COMMAND
findmnt -T /run/user/1000/netns/netns-bd33ecdb-4d59-0960-9537-b2a0038161db -o TARGET,SOURCE,FSTYPE,OPTIONS
ps -eo pid,ppid,stat,args | rg 'podman|conmon|netavark|aardvark|podman-compose'
systemctl --user cat azrael54.service
podman exec azrael54_frontend_1 busybox nslookup dashboard 10.89.3.1
nsenter -t 939372 -n sh -c 'printf "namespace="; readlink /proc/self/ns/net; ip -br addr show; ss -lunp'
tail -n 35 docs/GPU_DEPLOYMENT_STATUS.md
```

## Operator recovery attempt and runtime-refresh proposal — 2026-10-20

### Operator-reported commands and results

The user ran these commands interactively after the read-only recheck:

```sh
podman container cleanup azrael54_dashboard_1
# output: azrael54_dashboard_1
podman stop -t 0 --ignore azrael54_dashboard_1
# output: azrael54_dashboard_1
podman start azrael54_dashboard_1
# error: container ec79c5054492f50f5bdb87a76a0d0c652436dbaf2dd22408433a9cc09cf0addd must be in Created or Stopped state to be started: container state improper
```

The first two commands returned the container name, but the third confirms Podman's persisted dashboard state is still not startable. Cleanup did not report `setns`, so the conditional for Step 3 was not met; no namespace path is proposed for deletion or unmount. Stop here until explicit approval for Step 4.

### Runtime-refresh impact and recovery plan (proposal only)

The installed Podman version is `4.9.3`. The current rootless Podman inventory contains five running containers: `azrael54_tools_1`, `azrael54_imports_1`, `azrael54_web-lab_1`, `azrael54_external-tools_1`, and `azrael54_frontend_1`. The dashboard is stuck and not running; two `node-research-lab` containers are already exited. No other rootless Podman container is running in the current inventory.

Option A, `podman system migrate`: Podman's documented rootless migration path stops the running containers associated with the user and the rootless pause process; it does not remove containers or volumes. It will interrupt the five running containers listed above, but does not automatically restart them. Afterward, a manual recovery would start the same existing containers one at a time in AZRAEL's configured start order: tools, imports, external-tools, web-lab, dashboard, frontend. The dashboard is expected to fail again with the current improper-state error; if so, stop that sequence and start the frontend separately so the existing frontend is not left down. Rollback is to start the five containers that were running before migration, one by one, in that order (dashboard remains excluded because it is already stuck); if any start command fails unexpectedly, stop and report its output. The two exited `node-research-lab` containers are not part of the running set. Snap Docker and NeoCortex/HellPot are separate and are not targeted by rootless Podman migration. See the [official Podman system migrate documentation](https://docs.podman.io/en/stable/markdown/podman-system-migrate.1.html).

Option B, a full AZRAEL user-unit cycle (`systemctl --user restart azrael54.service`): the loaded unit's stop hook calls Compose `stop`, which targets the AZRAEL services without removing containers. If the unit runs its configured stop/start pair, the currently running AZRAEL containers tools, imports, external-tools, web-lab, and frontend will be stopped; dashboard is already stuck. The start hook processes services serially in this order: tools, imports, external-tools, web-lab, dashboard, frontend. Because dashboard currently fails to start and the hook aborts on a command error, frontend may not be reached. Rollback is to start the five previously running AZRAEL container IDs individually in the same order, skipping the already-stuck dashboard; stop after each command and inspect any error. This option is limited to the AZRAEL unit, unlike the rootless Podman-wide migration, but it still interrupts the five running services and can leave the frontend stopped if dashboard startup fails.

Neither option has been approved or run. Both preserve container identity and bind mounts by design, but both cause service interruption. The exact order in which the Podman-wide migration stops containers is controlled internally by Podman and is not promised by its documentation; only the subsequent AZRAEL start order above is explicit in `azraelctl` (`START_ORDER`).

### Additional inspection commands run by the assistant

```sh
rg -n '_service-start|_service-stop|def .*start|def .*stop|compose (up|down|stop|start)' azraelctl
sed -n '1150,1215p' azraelctl
rg -n 'START_ORDER|SERVICE_ORDER|COMPOSE_SERVICES' azraelctl
podman ps -a --format '{{.ID}} {{.Names}} {{.Status}}'
podman version --format '{{.Client.Version}}'
```

## Persistent source rebuild and verification

The source tree was recovered after the former temporary working directory was
lost. The persistent recovery location is `AZRAEL_HOME=$HOME/azrael54`; it contains
the Git history, recovered source, new recovery documentation and bounded
verification artifacts. The historical commands above are retained evidence, not
instructions or permission to run them in this recovery.

The image supplied 152 baseline files. Successful logged changes were replayed
by timestamp, with already-applied checks and unresolved conflicts retained.
The manifest currently records 192 FULL, zero PARTIAL, five CONFLICT and sixteen
LOST file/content-group entries. No application implementation was reconstructed
from a specification. The seventeen surviving specialist checkpoint files do not
replace the missing shared SLM weights or genuine datasets.

The azraelctl unit-generator update remains a source conflict: its expected
ExecStop context differs from the reconstructed base. The recovered document's
historical KillMode=process and TimeoutStopSec=360 account is preserved, but those
settings were not inserted into a different generator definition by guessing.
The existing installed unit and all containers, images and network state were
left untouched.

Recovery checks compiled 77 Python files and parsed four Compose YAML files.
Forty-four of forty-seven offline tests passed; the three unsuccessful CTF tests
require the absent original catalog/source/answer bundle. All twenty-one AZRAEL
artwork files match their originals and manifest hashes. No source download,
service startup, GPU operation, real inference, training or container lifecycle
operation was performed. See RECOVERY_VERIFICATION.md for exact scope and limits.

Original data, SLM files, evidence/CTF databases and authentication tokens were
not recovered by these tests. Required sources and fresh credential generation
are listed in RECOVERY_MANIFEST.md and GAPS.md. A future clean install must not
recreate the existing stuck dashboard under the existing project name; it needs
a different project name or an explicit later decision concerning that deployment.

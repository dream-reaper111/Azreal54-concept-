# AZRAEL-54 shared storage

## Current finding

The execution sandbox reports `/data/work` as `/dev/sdb1`, ext4, mounted `ro`, and blocks writes outside `/tmp`. The operator independently verified on Pop!_OS that `/data/work/azrael54` is writable (`AZRAEL STORAGE READY`) and that a rootless Alpine container runs successfully (`PODMAN_OK`). These host checks do not yet verify the AZRAEL-specific bind mount or `keep-id` access. No ownership change, chmod, move, or copy was attempted under `/data/work`.

The project currently occupies about 3.4 GB under `/home/deadbyte/azrael54`; the existing SLM directory is about 2.9 GB, `data/` about 164 MB, and `artifacts/` about 3.5 MB. The existing evidence database and model/data files remain at their original paths. They are mounted read-only in the new dashboard; AZRAEL will write new records and outputs to the shared store. Historical evidence is not automatically copied or migrated.

## Storage layout

`AZRAEL_STORAGE_ROOT` defaults to `/data/work/azrael54`. Each role reads from the same dataset and model locations; role count does not create dataset copies. New downloads/caches and writes are routed as follows:

| Purpose | Shared path |
|---|---|
| Downloaded and collected datasets | `datasets/` |
| Shared SLM weights | `models/slm/` |
| Role/classifier checkpoint weights | `checkpoints/<training-family>/` |
| Training reports and generated outputs | `training/<training-family>/` |
| Evidence SQLite database and raw evidence | `evidence/` |
| Tool downloads, extraction results, live-feed snapshots | `artifacts/` |
| Council, role research, candidate and setup state | `council/`, `role-research/`, `poc-candidates/`, `setup/` |
| Hugging Face, Torch and pip caches | `cache/` |
| Temporary training/download space | `tmp/` |

The installer creates only missing directories with mode `0700`, requires the storage root and its AZRAEL directories to be owned by the invoking user, rejects symlinks and read-only mounts, and performs a temporary write/read/fsync test. It does not chmod or chown existing directories. The compose mount is read/write inside the dashboard; existing project `data/`, `.slm-model/`, and `artifacts/` are mounted read-only for legacy reads.

## Check the host mount

Run these in a normal terminal as `deadbyte`:

```bash
id
findmnt -T /data/work -o TARGET,SOURCE,FSTYPE,OPTIONS
df -h / /data/work
stat -c '%A %a %U:%G %n' /data /data/work
python3 -c 'import os; p="/data/work"; print({"path":p,"writable":os.access(p,os.W_OK|os.X_OK),"uid":os.stat(p).st_uid,"mode":oct(os.stat(p).st_mode & 0o777)})'
```

If the normal host shows `ro`, inspect the kernel messages and filesystem/mount configuration before remounting:

```bash
sudo journalctl -k -b --no-pager | tail -n 100
findmnt --verify --verbose
```

If the drive is healthy and intended to be writable, correct the host mount using the established Pop!_OS storage procedure. Do not run a filesystem repair on a mounted drive and do not remount it read/write while kernel logs indicate filesystem errors.

Once `/data/work` is `rw`, create the AZRAEL target if it does not already exist and run the application preflight:

```bash
if [ ! -e /data/work/azrael54 ]; then mkdir -m 700 /data/work/azrael54; fi
python3 /home/deadbyte/azrael54/setup_lab.py --storage-check
```

If the target already exists, inspect it first with `stat -c '%A %a %U:%G %n' /data/work/azrael54`. The preflight intentionally fails if its mode is not private; adjust only this AZRAEL target directory after confirming it is the intended location. Never apply recursive ownership or permission changes to `/data/work`.

## Capacity, retention and persistence

The authenticated admin state reports mount, capacity, write access and the configured free-space warning threshold. Set these variables before running Compose or the installer:

```bash
export AZRAEL_STORAGE_ROOT=/data/work/azrael54
export AZRAEL_STORAGE_MIN_FREE_GB=20
export AZRAEL_EVIDENCE_RETENTION_DAYS=30
export AZRAEL_EVIDENCE_MAX_RECORDS=10000
```

Evidence expiry is configurable and remains an explicit, admin-confirmed action. There is no automatic dataset, model, checkpoint, artifact, or evidence deletion. Preserve older evidence/model files until a reviewed migration or retention request is approved.

To verify that a container restart preserves a harmless marker in the mounted store, after the stack is healthy run this as one shell block. It creates and removes a unique marker, so it does not overwrite existing setup data:

```bash
marker=".persistence-check-$(date +%s)-$$"
podman-compose --file /home/deadbyte/azrael54/compose.yaml --file /home/deadbyte/azrael54/compose.podman.yaml --project-name azrael54 exec dashboard /app/.slm-venv/bin/python -c 'from pathlib import Path; import sys; p=Path("/var/lib/azrael54/setup")/sys.argv[1]; p.write_text("AZRAEL persistence check\n"); print(p.read_text().strip())' "$marker"
podman-compose --file /home/deadbyte/azrael54/compose.yaml --file /home/deadbyte/azrael54/compose.podman.yaml --project-name azrael54 restart dashboard
podman-compose --file /home/deadbyte/azrael54/compose.yaml --file /home/deadbyte/azrael54/compose.podman.yaml --project-name azrael54 exec dashboard /app/.slm-venv/bin/python -c 'from pathlib import Path; import sys; p=Path("/var/lib/azrael54/setup")/sys.argv[1]; assert p.read_text()=="AZRAEL persistence check\n"; p.unlink(); print("PERSISTENCE_OK")' "$marker"
```

## Podman image storage audit

The Codex process cannot initialize Podman at `/run/user/1000/libpod`, so graphroot usage cannot be measured here. On the host, collect this read-only inventory before considering any move:

```bash
podman info --format '{{.Store.GraphRoot}} {{.Store.GraphDriverName}}'
podman system df -v
df -h / /data/work
```

For now, keep the existing graphroot unchanged. If the audit shows image layers threaten root-disk headroom, plan a separate maintenance window: stop only AZRAEL containers, record `podman ps -a` and `podman images`, make a verified copy of the rootless graphroot with ownership/xattrs/ACLs preserved, point the user's Podman `storage.conf` at a new dedicated directory on `/data/work`, then verify the image inventory and start AZRAEL before retiring the original copy. Do not prune, reset, move, or alter Docker/Snap storage, `ncpatch-hellpot-1`, or `ncpatch_hellpot-logs` as part of that plan.

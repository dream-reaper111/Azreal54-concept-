# AZRAEL-54 test results

**Run:** 2026-10-20, from `/home/deadbyte/azrael54`.

## Passed locally

- `/home/deadbyte/azrael54/.slm-venv/bin/python -m unittest discover -v`: **102 tests run; passed; 2 skipped** because the sandbox prohibits local listening sockets. Latest run completed in 11.779 seconds.
- New healthcheck test parses all five exec-form test arrays and fails on any argument containing parentheses, semicolons, or quote characters; it confirms the dashboard Python path and read-only Juice Shop script mount.
- New writable-layer tests cover zero-`StartedAt` skip, the exact Podman-injected `/etc` allowlist, and refusal for `A /app/x`.
- New GPU preflight tests cover missing `nvidia-ctk`, missing CDI devices, insufficient graphroot space, and construction of the selected-device `--userns keep-id` probe command. These are mocked tests, not host GPU execution.
- `.slm-venv/bin/python -m py_compile *.py`: passed.
- `bash -n deploy-host.sh install.sh run.sh diagnose-keepid.sh`: passed.
- PyYAML parsed `compose.yaml`, `compose.podman.yaml`, `compose.gpu.yaml`, and `compose.docker-gpu.yaml`.
- `node --check healthcheck.js`: passed.
- Upstream podman-compose 1.0.6 issue #866 documents that `condition: service_healthy` is not enforced. The project uses staged startup plus explicit Podman health polling instead.

## Host checks not run by the agent

- `podman-compose --version` printed `podman-compose version: 1.0.6` but exited after Podman failed to access `/run/user/1000/libpod` (`chmod ... read-only file system`). This does not verify host Compose behavior.
- `./diagnose-keepid.sh` was attempted here and exited before container inspection for the same sandbox restriction: Podman could not initialize `/run/user/1000/libpod` because it is read-only. No host container details were obtained.
- Merged `podman-compose config`, healthcheck execution inside images, service health, dashboard creation, API response, and SLM inference were not run from this sandbox.
- The operator reports four services running but unhealthy from the inline-healthcheck syntax issue; dashboard was not created. The replacement healthchecks have not yet been exercised on the host.
- The current keep-id error from running containers has not been captured. The read-only `diagnose-keepid.sh` script is ready; no configuration fix was made without evidence.
- The operator reports CDI is unavailable. The agent did not run `nvidia-ctk cdi generate`, invoke `sudo`, write `/etc`, run a GPU container, build a CUDA image, or perform GPU inference.
- The local test suite does not constitute a host deployment pass. Follow [RESUME-ON-HOST.md](RESUME-ON-HOST.md) in order and return failures with their full output.

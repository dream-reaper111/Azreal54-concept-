# AZRAEL-54 deployment status

**Updated:** 2026-10-20. **Current state:** CPU deployment is unhealthy according to the operator's latest host report. Four services (`tools`, `imports`, `web-lab`, and `external-tools`) are running but their healthchecks fail with `/bin/sh: 1: Syntax error: word unexpected (expecting ")")`; the dashboard was not created because the deployment waits for dependency health before starting it. This state has not been independently observed from the sandbox.

| Workstream | Status | Evidence and remaining work |
|---|---|---|
| Rootless preflight and shared storage | Operator-reported pass | Eight Podman preflight checks and storage check pass; `/data/work/azrael54` is `0700`; graphroot ancestor execute permissions were applied by the operator. The agent did not change host permissions. |
| Healthchecks | Code updated; host verification pending | Inline Python/Node snippets were replaced with argv-safe script paths. Python checks retain their `/healthz` URLs and 3 second timeout; Juice Shop retains `/`. Existing intervals, retry counts, and start periods are unchanged. |
| Dependency startup | Staged health gate implemented; host verification pending | The installer starts four independent services, polls Podman health, and starts dashboard only after they are healthy. Do not rely on `depends_on: condition: service_healthy` in podman-compose 1.0.6; upstream issue #866 reports that version starts dependents before health. |
| Writable-layer audit | False positive corrected; host verification pending | Never-started containers (`StartedAt` zero) are skipped. Started containers ignore only `C /etc` and `A`/`C` for `/etc/hosts`, `/etc/resolv.conf`, and `/etc/hostname`; any other diff still blocks recreation. |
| Keep-id failure on running services | Unresolved; host diagnostic still needed | The operator reported a separate keep-id issue but has not captured its error. The read-only diagnostic was attempted in this sandbox, but Podman stopped during initialization because `/run/user/1000/libpod` is read-only; no containers were inspected and no configuration change was made. Run `diagnose-keepid.sh` on Pop!_OS. |
| GPU/CDI | Fail-closed checks implemented; host preparation pending | The operator reports CDI is currently unresolved (`nvidia.com/gpu=all`). GPU work now requires an NVIDIA CDI device, a selected-device `podman run --userns keep-id ... nvidia-smi` probe, and at least 60 GiB free on the runtime graphroot filesystem. No CDI generation or GPU probe was run by the agent. |
| CPU deployment and inference | Failed on host; rerun required | Existing host report shows build/pull succeeded, startup failed at health checks, and inference did not run. Rerun CPU deployment after reviewing diagnostics and the writable-layer audit. |
| Local regression suite | Passed locally | 102 tests run, 2 skipped due sandbox socket restrictions, no failures; Python, shell, Compose YAML, and healthcheck JavaScript syntax checks passed. Host deployment remains separate. |
| Training status | Not trained | Service configuration, research retrieval, and simulation outputs are not model training. No claim of 54 independently trained models is made. |

The host's reported root filesystem has about 93 GB free. The default GPU gate reserves 60 GiB (`AZRAEL_GPU_MIN_FREE_GB` is configurable); its actual check reads the selected container runtime's graphroot filesystem immediately before any build or recreation. Moving graphroot to `/data/work` would require the same mapped-ID ancestor-traversal access as before and is not automated.

The ordered Pop!_OS recovery commands and pass/fail evidence to return are in [RESUME-ON-HOST.md](RESUME-ON-HOST.md). After the read-only diagnosis and clean layer audit, the CPU command is:

```bash
cd /home/deadbyte/azrael54 && ./deploy-host.sh --recreate-project-containers
```

Only after CPU health and inference pass, prepare NVIDIA CDI on the host and run the documented GPU command. See [PODMAN-SETUP.md](PODMAN-SETUP.md), [TEST-RESULTS.md](TEST-RESULTS.md), [KNOWN-ISSUES.md](KNOWN-ISSUES.md), and [DEPLOYMENT-VERIFICATION.json](DEPLOYMENT-VERIFICATION.json).

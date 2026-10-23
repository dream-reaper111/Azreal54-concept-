# CTF practice and idle training

## Offline CTF practice

AZRAEL stages 20 self-contained beginner encoding and cipher exercises from the [CTFd Challenge Assets project](https://github.com/zachflower/ctfd-challenge-assets), pinned to commit `bb8ce4ed14f02eea85e84273e537b865c707e332` under its MIT license. The source CSV and license are retained in `ctf_assets/source/`; the public catalog is sanitized, and the answer key is stored separately.

The authenticated dashboard's **CTF practice lab** panel lists challenges, accepts submitted flags, and can send one selected prompt to the shared local SLM using a chosen role context. The challenge request contains no answer key and makes no network requests. Attempts are stored in a separate `progress.sqlite3`; only a submission hash, correctness bit, role, and timestamp are recorded. CTF attempts never enter the incident evidence database or model-training datasets. These are authored contest puzzles, not real incident telemetry.

The service initializes `/data/work/azrael54/training/ctf` once. It refuses to overwrite a partial or integrity-invalid store. The runtime directory is mode `0700`; organizer data and the progress database are mode `0600`. The API does not return answers:

- `GET /api/ctf` — authenticated, answer-free catalog and progress.
- `POST /api/ctf/attempt` — authenticated flag check.
- `POST /api/ctf/practice` — authenticated, queued SLM practice request.

The directive engine encourages the SLM to think beyond the obvious, inspect assumptions and edge cases, and identify loopholes in these supplied challenges and other explicitly authorized AZRAEL lab tasks. This reasoning guidance cannot expand target scope or bypass operator approval, data protection, evidence, or stop controls. The sourced challenge bundle is offline puzzle data; it does not deploy or probe online targets.

## Idle trainer

The idle worker is available as soon as the dashboard starts and reports `idle` while it has no approved job. It does not start training automatically. An operator must select three existing, frozen manifests and confirm candidate training in the dashboard. The worker validates dataset provenance and split isolation, then waits for the shared inference/command lock to become free before running the existing `PocTraining` pipeline.

That pipeline trains two small outcome classifiers for 60 optimizer steps each. CUDA is selected through the UUID-aware runtime when usable; CPU fallback remains enabled. Candidate checkpoints remain separate from the 57 role models. Jobs left queued at service restart are marked interrupted and are not resumed automatically. No CTF prompt, answer, or attempt is eligible for this trainer.

Use `./azraelctl status` to inspect services and GPU state, `./azraelctl logs` for service logs, and `./azraelctl restart` to restart the managed rootless deployment without deleting data.

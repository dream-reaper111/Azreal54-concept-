# AZRAEL live readiness reviews

The training console provides operator-supervised, read-only analysis of the running AZRAEL deployment. It does not replace the existing training fixtures, quarantined research corpora, datasets, model weights, checkpoints, Juice Shop database, or unrelated lab deployments.

## What a mission measures

At start, the authenticated dashboard captures:

- In-network HTTP health checks for dashboard dependencies and the isolated Juice Shop service.
- Dashboard-container CPU affinity, process memory, cgroup memory and persistent-storage capacity.
- NVIDIA/PyTorch status visible inside the dashboard container. A missing value remains unavailable; host-only readings are not represented as container GPU access.
- Existing model inventory, evidence counts and dataset metadata.

The captured JSON is immutable mission provenance and receives a SHA-256 hash. Training roles review that same observation record through separate contexts of the shared local SLM. Their outputs remain unverified proposals. The evaluator's model-assisted comments and the workflow-completeness score do not establish response quality or accuracy.

There is no synthetic endpoint, command-channel event, attack execution, network discovery, host command execution, covert persistence, or endpoint control. Current service health can describe a healthy state; it does not invent an incident to make an exercise appear complete.

## Operator flow

1. Sign in to `http://127.0.0.1:8765` and open **Live Training Coordinator**.
2. Review the priority and explicitly approve the live, read-only mission.
3. Observe the single-worker queue, dependencies and per-role completion timeline.
4. Open a mission to replay its exact stored observations and role output. Replay is read-only.
5. Review the evidence, outputs, source hash and confidence. Accept to a chosen train/validation/test split or reject. A rejected or pending record cannot be exported.
6. Export is available only for accepted human-reviewed records. Exporting does not train, validate, promote or replace any model.

The serialized worker has a concurrency limit of one because all role prompts share the same local SLM. Urgent/high/normal/low missions use a bounded priority queue. If the dashboard restarts during a mission, the record is marked interrupted and is not resumed automatically. The emergency stop terminates the active SLM subprocess and cancels queued coordinator work; it does not stop AZRAEL containers.

## Data and review rules

Mission, task, audit, role-metric and dataset-version tables are added to the existing private evidence SQLite database. The schema change is additive. Each task stores its dependency list, input and output hashes, state, latency and structured model provenance. Human review stores decision, reviewer, confidence and a note. Accepted snapshots with identical source hashes cannot cross train/validation/test splits. Dataset-version hashes cover the split and complete member identities.

The existing synthetic benchmark workflows and placeholder fixtures remain intact for regression tests. They are not ingested by the live coordinator and are never labeled as live telemetry. This pipeline only stages reviewed records; it does not run a prolonged training job.

## Current runtime limit

The host has three NVIDIA devices, but rootless Podman CDI is currently blocked by invalid system CDI specifications. The dashboard therefore uses the verified CPU path; its GPU values should say unavailable. Host-side CUDA tests do not imply container GPU access. Resolve and verify CDI before selecting a GPU workload.

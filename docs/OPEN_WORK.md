# Open work at loss of the temporary tree

This list separates requested work, historical reports, and current recovery gaps.
Nothing here authorizes execution. Sources A–E are indexed in PROJECT_HISTORY.md.

## Highest-priority unresolved runtime work

| Work | Last useful evidence | Remaining requirement |
|---|---|---|
| Preserve and recover the original dashboard | E, user 2026-10-21 04:20:18.009Z; reported start error 04:28:32.205Z. | Resolve stale Podman state while retaining the same container and mounts; currently prohibited lifecycle actions must not be attempted. |
| Internal DNS and direct connectivity | E, 04:04:54.830Z request and 04:20:42.057Z compacted context. | Establish working frontend-to-dashboard DNS/routing, then authenticated API and HTTP 200 health checks; static frontend availability is insufficient. |
| Service-level CUDA after failure | E, 04:20:18.009Z explicitly distinguishes host CUDA from service verification. | Perform a genuine service inference only after recovery is separately authorized; earlier host/probe success does not verify current service state. |
| Persistent restart lifecycle | E, 17:33:38.706Z prior-day request and next-day failure summaries. | Validate restart persistence only after the dashboard/API are healthy; keep installed KillMode/process mitigation untouched now. |

## Model, data and UI work lacking final operational qualification

- **Training:** genuine task-compatible labeled train/validation/test splits were
  still unavailable in the final compacted context (E, 2026-10-21 04:20:42.057Z).
  No supervised training completion should be inferred from role registration,
  collection, mission review, or fixture tests.
- **Idle trainer:** requested at E, 02:37:51.275Z; recovered code/tests specify a
  confirmation-gated queue, but a real-data training run is not established.
- **CTF:** requested at E, 02:40:25.062Z; historical summary reports 20 exercises
  installed and an unsuccessful model attempt. The source bundle is missing from
  the image and has not been regenerated.
- **GPU optimization:** E's 17:29:37.632Z and 02:05:09.280Z requests include actual
  multi-GPU benchmarking, memory/performance measurements, and scheduling. The
  recovered source does not establish current three-GPU service operation or a
  performance improvement.
- **Role learning:** task-specific corpora and query catalogs are reference inputs;
  they do not establish independently trained capable models for every named role.
- **Council:** planner/critic/chair are contexts of one SLM in the recovered design;
  historical smoke reports do not establish independent-agent judgment quality.
- **Visual verification:** early summaries identify blocked browser/visual checks;
  later static frontend checks do not prove every mission, topology, playback,
  accessibility, and artwork interaction completed browser QA.
- **Collection:** genuine operational observations, final reviewed datasets, license
  review, and poisoning/leakage evaluation remain separate from downloaded metadata.

## Interrupted turns

The following explicit turn_aborted records were found; an interruption is evidence
of an interrupted turn, not proof that every task in that turn remained unfinished.

| Timestamp UTC | Session | Nearby work |
|---|---|---|
| 2026-10-20 09:26:22.758Z | A | Early dashboard/SLM continuation. |
| 2026-10-20 09:26:52.728Z | A | Early dashboard/SLM continuation. |
| 2026-10-20 10:24:31.670Z | B | Capability discussion; not implementation evidence. |
| 2026-10-20 10:49:53.102Z | C | Separate NeoCortex inspection chat, explicitly paused. |
| 2026-10-20 13:29:13.049Z | A | Artwork/council/topology expansion. |
| 2026-10-20 13:31:33.652Z | A | Same expansion period; exact completion must be checked by file/event evidence. |
| 2026-10-20 14:00:05.809Z | D | Architecture/task-list and hive context review. |
| 2026-10-20 14:03:18.617Z | X2 | Pet-related interaction, outside AZRAEL. |
| 2026-10-20 14:43:47.248Z | D | Role research/search implementation. |
| 2026-10-20 14:43:53.420Z | D | Role research/search implementation. |
| 2026-10-20 15:10:48.504Z | D | Runtime-aware installer replacement period. |
| 2026-10-20 16:10:01.722Z | D | GPU/storage/deployment verification work. |
| 2026-10-20 16:52:19.227Z | D | Deployment-status continuation before healthcheck/CDI requests. |

## Recovery work still open now

- Resolve five conflicted files through evidence; the first is setup_lab.py at
  2026-10-20 16:01:34.032Z. azraelctl's unit-generator change is also unresolved.
- Review the standing-rule draft and product-scope ambiguities.
- Restore or reacquire genuine datasets, exact SLM files, historical artifacts,
  and the consistent CTF source bundle; regenerate authentication tokens fresh.
- Complete the earlier Compose/history comparison, non-installed unit template,
  and clean-install guide after its separate approval gate. A new install must not
  recreate the existing stuck dashboard; it needs a different project name or an
  explicit later decision concerning the old deployment.
- Approve any specification reconstruction one file at a time; none is authorized
  or implemented merely by this list.

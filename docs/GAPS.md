# AZRAEL recovery gaps and specification evidence

This is a specification and provenance review, not permission to implement or
deploy. No LOST application file has been regenerated. No recovered FULL or PARTIAL
file has been overwritten with a replacement implementation. Paths are relative
to `AZRAEL_HOME=$HOME/azrael54`.

The current manifest has five CONFLICT files, sixteen LOST file/content-group
entries, and no PARTIAL files. FULL describes recovered bytes, not correctness.
Exact source events and all thirty conflict events are indexed in
`../recovery/file-inventory.json` and `../recovery/replay-events.json`.
Source-session references A–E resolve through PROJECT_HISTORY.md.

## Conflicted files

### setup_lab.py — CONFLICT, thirteen events

- **Intent sources:** D, 2026-10-20 15:05:12.159Z (runtime-aware installation),
  15:29:40.165Z (rootless recovery), 15:57:32.686Z (GPU validation),
  16:54:02.415Z (script health checks and GPU gates); E, 17:33:38.706Z (unified deployment).
- **Known interface:** `select_runtime`, `compose_prefix`, `plan`, `prepare_secrets`,
  `_env`, `execute`, rootless/CDI/disk preflight, staged health checks, SLM checks,
  storage integration, `main`, and verification-report persistence.
- **Tests/callers read:** test_installation.py covers dry plans, ordered dependency
  startup, explicit recreation flags, gate failures before execution, timing/report
  records, GPU selection, health-check arguments, and preserved operator diagnosis;
  azraelctl and installation.py call the installer helpers.
- **Missing:** first unresolved Update at 16:01:34.032Z adds verification reporting
  around a base that does not match exactly; later report/timing and runtime
  changes depend on intermediate content. The recovered source contains 1,066
  lines, but its complete final interface cannot be claimed.
- **Proposal:** first seek an authoritative later file snapshot or complete
  successful intermediate writes. Do not replace the conflicted file from spec;
  review one conflict at a time. Any approved clean-room implementation must use
  a separate new path until its replacement scope is explicitly decided.

### azraelctl — CONFLICT, thirteen events

- **Intent sources:** E, 2026-10-20 17:33:38.706Z (one-command installer and CLI),
  2026-10-21 04:20:18.009Z (preserve the same dashboard and unit mitigation).
- **Known interface:** `bootstrap`, `start`, `stop`, `restart`, `status`, `logs`,
  `doctor`, `verify`, `update`, and internal service-start/service-stop entry points;
  preservation audits, environment generation, GPU/CPU handling, and unit generation.
- **Tests/callers read:** test_azraelctl.py specifies command help, explicit/scoped
  recreation, verified backup and mount preservation, stable configuration signatures,
  CUDA probes through mocked runners, CPU fallback, unit generation, and verification
  results; test_installation.py and setup_lab.py specify shared installer contracts.
- **Missing:** successful updates depend on unmatched migration, verification, and
  lifecycle contexts. The 2026-10-21 04:10:12.405Z patch expects `_service-stop` in
  ExecStop; the recovered generator still has a different ExecStop definition.
  Therefore `KillMode=process` and `TimeoutStopSec=360` were not inserted by guessing.
- **Proposal:** resolve recorded provenance gaps before considering new code;
  preserve the existing installed unit, which this recovery has neither read for
  adoption nor modified. A source-derived unit template remains pending the earlier
  Compose/unit review gate. Do not invoke this launcher for deployment now.

### compose.yaml — CONFLICT, one event

- **Intent sources:** D, 2026-10-20 15:05:12.159Z, 15:29:40.165Z,
  15:36:00.605Z, 16:54:02.415Z; E, 17:33:38.706Z.
- **Known interface:** six declared services in the later design: tools, imports,
  web-lab, external-tools, dashboard, and frontend; loopback public binding, persistent
  storage, script health checks, isolated networks, and runtime/GPU overrides.
- **Tests/callers read:** test_installation.py asserts six exec-form health checks,
  exact health timing, expected mounts, frontend proxy/temp paths, and startup order;
  setup_lab.py and azraelctl derive commands and signatures from Compose files.
- **Missing:** one exact-base update; actual deployment flags may also differ from
  the recovered declaration. Source YAML alone does not establish running state.
- **Proposal:** compare the conflict with an authoritative later source; reconcile
  sanitized history commands only after approval of the earlier Step 4 gate. Never
  test this by launching Compose or touching existing containers.

### SLM.md — CONFLICT, one event

- **Intent sources:** A, 2026-10-20 09:18:50.594Z–09:19:36.156Z;
  D, 15:57:32.686Z; E, 17:29:37.632Z.
- **Known purpose/interface:** describe the shared local coding/admin model, pinned
  model assets, role contexts, inference, and later GPU versus CPU behavior;
  slm.py points users here when weights are unavailable.
- **Tests/callers read:** test_azraelctl.py tests one-time CPU fallback through mocked
  worker responses; setup_slm.py and slm-model-manifest.json specify model identity
  and files. No test establishes the missing documentation paragraph's exact wording.
- **Missing:** an update to documentation whose old/new context does not match.
- **Proposal:** recover the exact source if possible; otherwise approve a separate
  new supplemental guide, leaving this recovered file intact.

### DEPLOYMENT-VERIFICATION.json — CONFLICT, two events

- **Intent sources:** D, 2026-10-20 15:29:40.165Z, 15:51:38.708Z,
  16:55:25.436Z; E, 17:29:37.632Z.
- **Known purpose/interface:** historical runtime facts, host diagnosis, step
  results, timings, and honest not-run markers; setup_lab.py produces this report.
- **Tests/callers read:** test_installation.py requires preserved `host_diagnosis`
  when saving new reports and checks timing success/failure records.
- **Missing:** conflicting report revisions and four post-image generated-write
  results that static replay could not reproduce as original observed facts.
- **Proposal:** retain historical content as conflicted evidence; obtain the original
  report or create a differently named new report from separately authorized checks.
  Never fabricate historical pass results from tests or prompts.

## Lost files and content groups

| Manifest entry | Known purpose/interface and evidence | Tests/callers | Missing content and proposed source |
|---|---|---|---|
| `ctf_assets/catalog.json` | E, 2026-10-21 02:40:25.062Z requested online-sourced lab exercises; CtfLab expects schema `azrael-ctf-catalog/1`, pinned source metadata, unique bounded IDs, and self-contained descriptions. | test_ctf_lab.py requires 20 challenges, hidden answers, offline prompts and isolated progress; ctf_lab.py and setup_lab.py consume it. | Exact selected challenge records and provenance; recover the pinned source bundle or approve a new derivation from that source, not invented replacement challenges. |
| `ctf_assets/organizer-answer-key.json` | CtfLab expects schema `azrael-ctf-answer-key/1`, matching source hash, and exactly one answer per challenge ID. | test_ctf_lab.py verifies correct/wrong submissions, answer-free prompts and progress storage, private file mode, and corruption preservation. | Exact matching exercise answers; restore together with the catalog from the same original bundle. No answer values are copied into this report. |
| `ctf_assets/source/SOURCE.json` | E, logged generation at 2026-10-21 02:47:43.044Z; its object must exactly equal catalog.source. | CtfLab._read_template, persisted integrity metadata. | Original source hash, selection/provenance metadata and any source count facts; recover from original assets or derive only from actual pinned bytes after approval. |
| `ctf_assets/source/dailies.csv` | E, 2026-10-21 02:42:12.320Z source reference; upstream `zachflower/ctfd-challenge-assets`, commit `bb8ce4ed14f02eea85e84273e537b865c707e332`. | CtfLab verifies its hash if present; catalog/key provenance depends on it. | Original CSV bytes; obtain from verified backup or the exact pinned upstream revision, with explicit later network approval if needed. |
| `ctf_assets/source/LICENSE.md` | E, 2026-10-21 02:43:24.427Z source reference; CtfLab requires the license and hashes the persisted copy. | CtfLab._read_template/_initialize and test_ctf_lab.py. | Exact upstream license text; recover from the pinned revision, never author a substitute license. |
| `collection-inbox/software/manifest.json` | A, 2026-10-20 10:32:20.755Z requested a software-evidence worker; logged output destination at 10:33:28.493Z. | No direct recovered test reads this path; collection.py and evidence_store.py define nearby collection/provenance semantics. | Original retrieval facts are absent; obtain the historical report from backup, or approve a new separately dated collection. It is not safe to infer counts or retrieval timestamps. |
| `collection-inbox/operational/manifest.json` | A, 2026-10-20 10:32:20.755Z and logged generation at 10:33:54.105Z; records awaiting explicitly designated operational input, handling requirements and zero training. | No direct file caller; test_collection.py checks awaiting-authorized-input reporting. | Exact historical timestamp/report bytes; a fresh status-only manifest is reconstructible after approval, but must not claim original retrieval or evidence. |
| `coordination-validation.json` | A, 2026-10-20 13:28:54.879Z council intent; D logged generation at 14:25:33.209Z. | validate_coordination.py writes it; council protocol tests use mocked generation and do not recreate actual inference evidence. | Original inference outputs/timings; restore original report or obtain new separately authorized inference evidence, not a spec-generated success record. |
| `data/` | A, 2026-10-20 09:12:07.217Z task-specific public training; D 15:36:00.605Z shared-store preservation. | knowledge.py, live_data.py, public_training.py, domains.py, automotive.py, research.py and their tests expect distinct schemas. | Dataset/reference snapshots, labels, source manifests and hashes; restore backups or reacquire documented sources. Tests cannot supply genuine operational datasets. |
| `.slm-model/` | A, 2026-10-20 09:18:50.594Z; slm-model-manifest.json identifies Qwen/Qwen2.5-Coder-1.5B-Instruct revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`. | setup_slm.py, slm.py and slm_worker.py need weights/config/tokenizer; mocked tests do not verify real inference. | The nine manifest-listed files, including model.safetensors; restore exact hash-verified files from backup or the original model source. No training from scratch is implied. |
| `artifacts/` | A, 2026-10-20 13:28:54.879Z; E, 2026-10-21 02:05:09.280Z mission/history intent. | EvidenceStore, Council, training_coordinator.py, idle_trainer.py and related tests define local stores and interfaces. | Original SQLite databases, frozen datasets, mission/council records, candidates and reports; recover verified backups. Newly generated test artifacts do not replace historical records. |
| `.runtime/broker-token` | Current recovery 2026-10-21 05:14:17Z requires fresh credentials; setup_lab.prepare_secrets describes intended generation. | Broker authentication consumers; no current credential is read or retained. | Generate fresh only during a separately approved installation; do not reconstruct from logs. |
| `.runtime/admin-token` | Same current no-secret-copy rule; administrator authentication requires a fresh value. | Dashboard login and setup verification consumers. | Generate fresh; recover no old value and do not print it into reports. |
| `.runtime/external-token` | Same current no-secret-copy rule; external broker authentication requires a fresh value. | External broker consumers and permission tests. | Generate fresh; restore no old credential from logs. |
| `Dockerfile` | Historical successful deletion during the move to container/Dockerfile.* on 2026-10-20 10:21:32.785Z. | Current Compose uses container-specific definitions. | Intentionally removed obsolete root file; do not reconstruct. |
| `isolated.sh` | Historical successful deletion on 2026-10-20 10:21:32.785Z during the container workflow change. | Current launchers supersede it. | Intentionally removed obsolete launcher; do not reconstruct. |

## Partial outputs and unknown expressions

Thirty-nine printed excerpts are recorded as partial source observations in the
replay ledger; they were not promoted to complete replacement files. Three full
printed observations likewise remain source evidence where a base already existed.
The 191 unrecovered static-write expressions are not 191 missing files: many
precede the image mtimes or attempt to write dynamically computed evidence.

## Proposed reconstruction order — no approval assumed

1. Decide how to resolve the first setup_lab.py conflict using authoritative
   source evidence; this is conflict resolution, not permission to replace it.
2. Obtain the exact pinned CTF source bundle; then review catalog/key derivation
   one output file at a time. The license and source CSV must come from upstream
   or a verified backup, not a new implementation.
3. If useful, approve a new operational-awaiting-input status manifest; preserve
   its new date and RECONSTRUCTED-FROM-SPEC classification.
4. Do not reconstruct historical verification reports, operational datasets, model
   weights, or SQLite records from specification. They require original sources
   or new separately identified observations.

Any approved reconstructed file requires its own commit and manifest label. FULL
and PARTIAL recovered files remain protected from replacement implementations.
